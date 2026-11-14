/* ============================================================
 * i2s_audio.c —— I2S2 + DMA 音频输出实现
 *
 * 设计要点：
 *  1) DMA 用【循环模式】(DMA_CIRCULAR)：缓冲填一次，硬件自动反复播放，
 *     CPU 完全不参与 → 无中断、无 gap、对"流畅"零负担。
 *  2) 正弦波用「32 点查表 + 32 位相位累加器 + 线性插值」纯整数生成，
 *     不依赖 math.h / libm，任何编译配置下都能过。
 *  3) 缓冲区 50ms（2205 立体声帧 = 8820 字节），足够覆盖任何短暂的
 *     主循环停顿；将来接 USB 时改成分块双缓冲即可。
 *  4) 【不开启 DMA 中断、不配 NVIC】：本工程 stm32f4xx_it.c 没有
 *     DMA1_Stream4_IRQHandler，若开 NVIC 会落到 Default_Handler 死循环。
 *     循环播放模式下也完全不需要中断。
 * ============================================================ */
#include "i2s_audio.h"
#include <string.h>

I2S_HandleTypeDef g_i2s2_handle;
DMA_HandleTypeDef g_i2s2_tx_dma;

/* 立体声交错缓冲：L,R,L,R,... */
static int16_t s_tone_buf[AUDIO_TONE_BUF_LEN];
static uint8_t s_tone_playing = 0;

/* ---- Phase 4 流播放缓冲 ---- */
/* 双缓冲（half1 + half2），DMA 循环播放整块，HT/TC 回调 refill 刚播完的半区。
 * 🔴 以 16bit 样本(halfword)为单位：总长 2×HALF_LEN 样本 = 8192 字节。
 *    HAL_I2S_Transmit_DMA 的 Size 单位也是"样本数"，两者必须一致；
 *    若声明成 uint8_t[2×HALF_LEN]=4096 字节却按 4096 样本传，会越界读相邻内存 → 刺耳噪声。 */
static uint16_t s_stream_buf[AUDIO_STREAM_HALF_LEN * 2u];
/* 字节环形缓冲：小端 16bit 交错立体声 PCM */
static uint8_t  s_ring[AUDIO_RING_SIZE];
static volatile uint32_t s_ring_w = 0;
static volatile uint32_t s_ring_r = 0;
static uint8_t  s_stream_on = 0;
/* LCD 歌词时间轴：DMA 累计消费的 PCM 字节数（只在 DMA 回调里累加，主循环只读）
 * 用 uint32_t 保证 32 位 MCU 上读/写原子；176400 B/s 下约 6.7 小时才回绕，够用。 */
static volatile uint32_t s_consumed_bytes = 0;

/* ---- 歌词同步（见 stream_fill_half）----------------------------------
 * 问题：DMA 从开机就在跑（没数据时播静音），若只按"已消费字节"计时，
 * 点播放之前的时间也被算进去 → 歌词全程提前。
 * 解法：s_pos_bytes 只累计真实 PCM 字节（静音不计），断流 >1.5s 视为重新播放。 */
static volatile uint32_t s_pos_bytes  = 0;    /* 真实 PCM 累计字节（歌词时间轴） */
/* 软件音量：Q8 定点（256 = 0dB）。默认 0xB0≈0.69，先给功放留余量，治"炸"。 */
static volatile uint16_t s_sw_gain    = 0x61u;   /* 38/100 -> 0.38x，默认别太吵 */
static volatile uint8_t  s_sw_vol     = 38u;
static volatile uint8_t  s_idle_cnt   = 0;    /* 连续欠载的 refill 次数 */

#define AUDIO_IDLE_RESYNC   65u               /* 65 × 23ms ≈ 1.5s 断流后清零重来 */

/* 32 点正弦表：sin(2πk/32) × 32767，末位补一个 0 便于插值取 idx+1 */
static const int16_t s_sin_tab[33] = {
        0,   6393,  12539,  18204,  23170,  27245,  30273,  32137,
    32767,  32137,  30273,  27245,  23170,  18204,  12539,   6393,
        0,  -6393, -12539, -18204, -23170, -27245, -30273, -32137,
   -32767, -32137, -30273, -27245, -23170, -18204, -12539,  -6393,
        0
};

/* ============================================================
 * HAL_I2S_MspInit —— 引脚 / 时钟 / DMA 配置
 * 由 HAL_I2S_Init() 自动回调（HAL 里是 __weak，这里提供强定义）
 * ============================================================ */
void HAL_I2S_MspInit(I2S_HandleTypeDef *hi2s)
{
    GPIO_InitTypeDef gpio = {0};

    if (hi2s->Instance != SPI2) return;

    /* ---- 外设时钟 ---- */
    __HAL_RCC_SPI2_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_DMA1_CLK_ENABLE();

    /* ---- 引脚：PB12=WS, PB13=CK, PC3=SD, PC6=MCK，全部 AF5 ---- */
    gpio.Mode      = GPIO_MODE_AF_PP;
    gpio.Pull      = GPIO_NOPULL;
    gpio.Speed     = GPIO_SPEED_FREQ_HIGH;
    gpio.Alternate = GPIO_AF5_SPI2;

    gpio.Pin = GPIO_PIN_12 | GPIO_PIN_13;      /* WS + CK */
    HAL_GPIO_Init(GPIOB, &gpio);

    gpio.Pin = GPIO_PIN_3 | GPIO_PIN_6;        /* SD + MCK */
    HAL_GPIO_Init(GPIOC, &gpio);

    /* ---- DMA：DMA1_Stream4 / Channel0 = SPI2_TX ---- */
    g_i2s2_tx_dma.Instance                 = DMA1_Stream4;
    g_i2s2_tx_dma.Init.Channel             = DMA_CHANNEL_0;
    g_i2s2_tx_dma.Init.Direction           = DMA_MEMORY_TO_PERIPH;
    g_i2s2_tx_dma.Init.PeriphInc           = DMA_PINC_DISABLE;
    g_i2s2_tx_dma.Init.MemInc              = DMA_MINC_ENABLE;
    g_i2s2_tx_dma.Init.PeriphDataAlignment = DMA_PDATAALIGN_HALFWORD;
    g_i2s2_tx_dma.Init.MemDataAlignment    = DMA_MDATAALIGN_HALFWORD;
    g_i2s2_tx_dma.Init.Mode                = DMA_CIRCULAR;      /* 循环播放 */
    g_i2s2_tx_dma.Init.Priority            = DMA_PRIORITY_HIGH;
    g_i2s2_tx_dma.Init.FIFOMode            = DMA_FIFOMODE_DISABLE; /* 直连模式最稳 */
    g_i2s2_tx_dma.Init.FIFOThreshold       = DMA_FIFO_THRESHOLD_FULL;
    g_i2s2_tx_dma.Init.MemBurst            = DMA_MBURST_SINGLE;
    g_i2s2_tx_dma.Init.PeriphBurst         = DMA_PBURST_SINGLE;

    if (HAL_DMA_Init(&g_i2s2_tx_dma) != HAL_OK) { while (1); }

    __HAL_LINKDMA(hi2s, hdmatx, g_i2s2_tx_dma);

    /* Phase 4：必须开 DMA 中断 —— 双缓冲 refill 靠 HT/TC 回调。
     * 优先级 1（低于 USB OTG 的 0），保证 USB 能抢占喂数据。 */
    HAL_NVIC_SetPriority(DMA1_Stream4_IRQn, 1, 0);
    HAL_NVIC_EnableIRQ(DMA1_Stream4_IRQn);
}

/* ============================================================
 * 初始化 I2S2
 * ============================================================ */
uint8_t audio_i2s_init(void)
{
    RCC_PeriphCLKInitTypeDef periph = {0};

    /* ---- 1. 配 PLLI2S：271MHz VCO，/2 = 135.5MHz ---- */
    periph.PeriphClockSelection = RCC_PERIPHCLK_I2S;
    periph.PLLI2S.PLLI2SN       = 271;
    periph.PLLI2S.PLLI2SR       = 2;
    if (HAL_RCCEx_PeriphCLKConfig(&periph) != HAL_OK) return 1;

    /* ---- 2. I2S2：主模式发送 / 飞利浦标准 / 16bit / 44.1k / MCLK 输出 ---- */
    g_i2s2_handle.Instance               = SPI2;
    g_i2s2_handle.Init.Mode              = I2S_MODE_MASTER_TX;
    g_i2s2_handle.Init.Standard          = I2S_STANDARD_PHILIPS;
    g_i2s2_handle.Init.DataFormat        = I2S_DATAFORMAT_16B;
    g_i2s2_handle.Init.MCLKOutput        = I2S_MCLKOUTPUT_ENABLE;
    g_i2s2_handle.Init.AudioFreq         = I2S_AUDIOFREQ_44K;
    g_i2s2_handle.Init.CPOL              = I2S_CPOL_LOW;
    g_i2s2_handle.Init.ClockSource       = I2S_CLOCK_PLL;
    g_i2s2_handle.Init.FullDuplexMode    = I2S_FULLDUPLEXMODE_DISABLE;

    if (HAL_I2S_Init(&g_i2s2_handle) != HAL_OK) return 2;

    return 0;
}

/* ============================================================
 * 用整数相位累加器填正弦波
 *   step = freq × (32×65536) / 44100
 *   phase 的 bit16 以上是表索引，bit15..0 是插值小数
 * ============================================================ */
static void tone_fill(uint32_t freq_hz, uint16_t amp)
{
    const uint32_t PHASE_FULL = 32u * 65536u;              /* 一整周 = 2^21 */
    uint32_t step  = (uint32_t)(((uint64_t)freq_hz * PHASE_FULL) / AUDIO_SAMPLE_RATE);
    uint32_t phase = 0;
    uint32_t i;

    for (i = 0; i < AUDIO_TONE_FRAMES; i++) {
        uint32_t idx  = phase >> 16;                        /* 0..31 */
        int32_t  frac = (int32_t)(phase & 0xFFFFu);
        int32_t  s0   = s_sin_tab[idx];
        int32_t  s1   = s_sin_tab[idx + 1];
        int32_t  v    = s0 + (((s1 - s0) * frac) >> 16);     /* 线性插值 */

        v = (v * (int32_t)amp) / 32767;                     /* 幅度缩放 */

        s_tone_buf[i * 2u]      = (int16_t)v;               /* 左 */
        s_tone_buf[i * 2u + 1u] = (int16_t)v;               /* 右 */

        phase += step;
        if (phase >= PHASE_FULL) phase -= PHASE_FULL;
    }
}

static void tone_fill_silence(void)
{
    uint32_t i;
    for (i = 0; i < AUDIO_TONE_BUF_LEN; i++) s_tone_buf[i] = 0;
}

/* ============================================================
 * 开始播放（DMA 循环，永不返回数据）
 * ============================================================ */
void audio_tone_start(uint32_t freq_hz)
{
    if (freq_hz == 0) tone_fill_silence();
    else              tone_fill(freq_hz, 12000);   /* 12000/32767 ≈ -8.7dBFS */

    if (s_tone_playing) {
        /* 已经在播：直接停掉 DMA 再重启，让新波形立即生效 */
        HAL_I2S_DMAStop(&g_i2s2_handle);
        s_tone_playing = 0;
    }

    if (HAL_I2S_Transmit_DMA(&g_i2s2_handle,
                             (uint16_t *)s_tone_buf,
                             (uint16_t)AUDIO_TONE_BUF_LEN) == HAL_OK) {
        s_tone_playing = 1;
    }
}

void audio_tone_stop(void)
{
    tone_fill_silence();
    if (s_tone_playing) {
        HAL_I2S_DMAStop(&g_i2s2_handle);
        s_tone_playing = 0;
    }
}

/* ============================================================
 * Phase 4：环形缓冲 → 双缓冲 PCM 流播放
 *
 * 设计要点：
 *   - 环形缓冲 s_ring：字节流，由 USB 接收中断（CDC_Receive_FS）写入，
 *     由 DMA 的 HT/TC 中断（消费者）读出填进 I2S 双缓冲。
 *   - 双缓冲 s_stream_buf：DMA 以【循环模式】播整块；播到一半(HT)时第一半
 *     已空闲、播完(TC)时第二半已空闲，分别 refill —— 永远写"不在播"的那半。
 *   - 单生产者(USB)/单消费者(DMA)环形：索引 32 位对齐读写天然原子，
 *     最坏情况只是偶发静音/丢包，不会破坏数据。
 *   - 环形写满时丢弃最旧数据（推进读指针），限制延迟、避免堆积。
 * ============================================================ */

/* 把环形缓冲的数据填进指定半区（字节→uint16 交错，小端）；
 * 数据不足则填静音(0)。dst 为 halfword 数组首地址。 */
static void stream_fill_half(uint16_t *dst, uint32_t half_len)
{
    uint32_t need  = half_len * 2u;     /* 需要的字节数 */
    uint32_t avail = (s_ring_w - s_ring_r) & AUDIO_RING_MASK;  /* 恒为 4 的倍数 */
    uint32_t n     = (avail < need) ? avail : need;
    uint32_t i;
    uint8_t  *d = (uint8_t *)dst;

    /* 有多少填多少，不足部分补静音。
     * （原来"不足就整半静音"会在缓冲临界点造成整段 23ms 静音跳变 → 间断；
     *   现在欠载只丢缺失的那点，听感是极短空白，不会整块静音。） */
    /* 软件音量：逐 16bit 样本做 (v*g)>>8。g=256 时就是直通，
     * 乘法只在有真实数据时跑（2048 样本/23ms ≈ 0.8% CPU），不影响时序。 */
    {
        uint16_t g = s_sw_gain;

        if (g == 256u) {
            for (i = 0; i < n; i++) {
                d[i] = s_ring[s_ring_r];
                s_ring_r = (s_ring_r + 1u) & AUDIO_RING_MASK;
            }
        } else {
            uint32_t k = 0;
            for (i = 0; i < n; i++) {
                d[i] = s_ring[s_ring_r];
                s_ring_r = (s_ring_r + 1u) & AUDIO_RING_MASK;
                k++;
                if (k == 2u) {                       /* 凑够一个 16bit 样本 */
                    int32_t v = (int16_t)((uint16_t)d[i - 1u] | ((uint16_t)d[i] << 8));
                    v = (v * (int32_t)g) >> 8;
                    if (v > 32767) v = 32767;
                    if (v < -32768) v = -32768;
                    d[i - 1u] = (uint8_t)((uint16_t)v & 0xFFu);
                    d[i]      = (uint8_t)(((uint16_t)v >> 8) & 0xFFu);
                    k = 0;
                }
            }
        }
    }
    for (; i < need; i++) d[i] = 0;

    /* 歌词时间轴：只累计【真实 PCM】的字节数（n），静音填充（need-n）不计时。
     * 好处：
     *   - 软件启动后多久才点播放都无所谓，第一块真实数据才是 0 点；
     *   - 中途卡顿/欠载时歌词自动"停住"，恢复后继续对齐，不会越走越偏；
     *   - 断流超过约 1.5 秒再恢复，视为重新开始播放，时间轴清零。 */
    if (n > 0u) {
        if (s_idle_cnt >= AUDIO_IDLE_RESYNC) s_pos_bytes = 0;
        s_pos_bytes += n;
        s_idle_cnt = 0;
    } else if (s_idle_cnt < 255u) {
        s_idle_cnt++;
    }

    /* LCD 歌词时间轴：本次 refill 意味着 DMA 已播完 need 字节。
     * 中断里只做一次 32bit 加法（原子、极快），不做任何 UI/文件操作。 */
    s_consumed_bytes += need;
}

/* 已播放时长(ms)：只按真实 PCM 计时，静音/欠载不计。
 * 与歌声用的是同一份数据，因此天然同步。 */
void audio_stream_set_volume(uint8_t vol)
{
    if (vol > 100u) vol = 100u;
    s_sw_vol  = vol;
    /* 0~100 线性映射到 Q8 增益 0..256：0=静音，100=0dB 直通。
     * 之前是 0~63、每次 ±4（只有 16 档），现在 101 档、每次 ±1。 */
    s_sw_gain = (uint16_t)(((uint32_t)vol * 256u) / 100u);
}

uint8_t audio_stream_volume(void) { return s_sw_vol; }

uint32_t audio_stream_position_ms(void)
{
    return (uint32_t)(((uint64_t)s_pos_bytes * 1000u) / (uint32_t)(AUDIO_SAMPLE_RATE * 4u));
}

/* 换曲/重放时把歌词时间轴归零。
 * ⚠️ 时序坑：上位机 select_slot() 只是置了 UI 的 pending 标志，真正的清零发生在
 *    下一次 lcd_ui_tick()；而 T_POS（seek 后的时间轴基准）在这之前就被 cdc_ctrl
 *    消费了。如果这里无条件清 0，基准会被冲掉，seek 后歌词又提前。
 *    解法：set_position() 记下一次性基准 s_start_ms，这里的「清零」回到该基准。 */
static volatile uint32_t s_start_ms = 0;

void audio_stream_reset_position(void)
{
    if (s_start_ms != 0u) {
        s_pos_bytes = (uint32_t)(((uint64_t)s_start_ms
                                 * (uint32_t)(AUDIO_SAMPLE_RATE * 4u)) / 1000u);
        s_start_ms  = 0;                 /* 一次性，用完即弃 */
    } else {
        s_pos_bytes = 0;
    }
    s_idle_cnt  = 0;
}

void audio_stream_set_position(uint32_t ms)
{
    /* ms -> 字节：176400 B/s（44.1k * 2ch * 2B），64 位避免溢出。
     * 上位机 seek / 换倍速 / 切歌后调用；传进来的是「已按倍速缩放」的时间，
     * 与下发到设备的那份 LRC 时间戳同尺度。 */
    s_start_ms  = ms;                 /* 供紧接着的 reset_position() 保住基准 */
    s_pos_bytes = (uint32_t)(((uint64_t)ms * (uint32_t)(AUDIO_SAMPLE_RATE * 4u)) / 1000u);
    s_idle_cnt  = 0;
}

uint32_t audio_stream_consumed_bytes(void)
{
    return s_consumed_bytes;
}

void audio_stream_reset_consumed(void)
{
    s_consumed_bytes = 0;
}

/* DMA 半传输完成：第一半刚播完 → 填第一半 */
void HAL_I2S_TxHalfCpltCallback(I2S_HandleTypeDef *hi2s)
{
    if (hi2s->Instance == SPI2 && s_stream_on)
        stream_fill_half((uint16_t *)&s_stream_buf[0], AUDIO_STREAM_HALF_LEN);
}

/* DMA 全传输完成：第二半刚播完 → 填第二半 */
void HAL_I2S_TxCpltCallback(I2S_HandleTypeDef *hi2s)
{
    if (hi2s->Instance == SPI2 && s_stream_on)
        stream_fill_half((uint16_t *)&s_stream_buf[AUDIO_STREAM_HALF_LEN], AUDIO_STREAM_HALF_LEN);
}

/* 主机 PCM 字节灌入环形缓冲（USB 中断里调用） */
int audio_stream_push(const uint8_t *data, uint32_t len)
{
    uint32_t i = 0;
    uint32_t avail;

    /* 以 4 字节（一个立体声帧）为单位写入，溢出时也整帧丢弃：
     * 这样 16bit 采样与 L/R 对齐永远不乱，绝不会因"丢单字节"出现位错/爆音。
     * （原来按单字节丢最旧，一旦溢出就会把后续所有样本错位半字节 → 刺耳。） */
    while (i + 4u <= len) {
        avail = (s_ring_w - s_ring_r) & AUDIO_RING_MASK;
        if (avail >= AUDIO_RING_SIZE - 4u) {
            /* 只剩不足一帧空闲 → 丢最旧一帧，腾出 4 字节 */
            s_ring_r = (s_ring_r + 4u) & AUDIO_RING_MASK;
        }
        s_ring[s_ring_w]                          = data[i];
        s_ring[(s_ring_w + 1u) & AUDIO_RING_MASK] = data[i + 1u];
        s_ring[(s_ring_w + 2u) & AUDIO_RING_MASK] = data[i + 2u];
        s_ring[(s_ring_w + 3u) & AUDIO_RING_MASK] = data[i + 3u];
        s_ring_w = (s_ring_w + 4u) & AUDIO_RING_MASK;
        i += 4u;
    }
    /* 尾部不足一帧的残余字节丢弃，保证 4 字节对齐 */
    return (int)i;
}

uint32_t audio_stream_available(void)
{
    return (s_ring_w - s_ring_r) & AUDIO_RING_MASK;
}

void audio_stream_start(void)
{
    uint32_t i;

    /* 双缓冲先清零（静音），环形清空 */
    for (i = 0; i < (AUDIO_STREAM_HALF_LEN * 2u); i++) s_stream_buf[i] = 0;
    s_ring_r = s_ring_w = 0;
    s_consumed_bytes = 0;      /* 每次重新启流，歌词时间轴归零 */
    s_pos_bytes = 0;
    s_idle_cnt  = 0;
    s_stream_on = 1;

    /* 以整块双缓冲为单位做循环传输；HAL 在 HT/TC 回调里 refill */
    HAL_I2S_Transmit_DMA(&g_i2s2_handle, (uint16_t *)s_stream_buf,
                         (uint16_t)(AUDIO_STREAM_HALF_LEN * 2u));
}

void audio_stream_stop(void)
{
    if (s_stream_on) {
        HAL_I2S_DMAStop(&g_i2s2_handle);
        s_stream_on = 0;
    }
}
