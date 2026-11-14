/* ============================================================
 * i2s_audio.h —— I2S2 音频输出（Phase 3：先让喇叭独立出声）
 *
 * 硬件：STM32F407ZGT6 I2S2（SPI2 复用）→ WM8978
 *   引脚（探索者 V2.7 官方 I2S 例程/开发指南；与板上 I2S 复用一致）：
 *     PB12 = I2S2_WS  (LRCK)
 *     PB13 = I2S2_CK  (BCLK)
 *     PC3  = I2S2_SD  (DACDAT)
 *     PC6  = I2S2_MCK (MCLK, 256×fs)
 *   DMA：DMA1_Stream4 / Channel0（SPI2_TX），循环模式
 *   格式：I2S 飞利浦标准 / 16bit / 44.1kHz / 主模式发送 / MCLK 使能
 *
 * 时钟：PLLI2S  VCO = HSE/PLLM × PLLI2SN = 8M/8 × 271 = 271MHz
 *                I2SCLK = VCO / PLLI2SR = 271/2 = 135.5MHz
 *       HAL 自动算 I2SDIV=6 → MCLK = 135.5M/(2×6) = 11.2917MHz
 *       （目标 256×44100 = 11.2896MHz，误差 +0.019%，听不出来）
 * ============================================================ */
#ifndef __I2S_AUDIO_H
#define __I2S_AUDIO_H

#include "stm32f4xx_hal.h"

#define AUDIO_SAMPLE_RATE   44100u
#define AUDIO_TONE_FRAMES   2205u          /* 50ms 立体声帧数（每声道 2205 样本） */
#define AUDIO_TONE_BUF_LEN  (AUDIO_TONE_FRAMES * 2u)   /* halfword 个数 */

/* 初始化 I2S2（含 PLLI2S、GPIO、DMA）。返回 0 = 成功，非 0 = 失败 */
uint8_t audio_i2s_init(void);

/* 用 DMA 循环播放指定频率的正弦测试音（幅度约 -8.7dBFS）
 * freq_hz 建议 100~4000；0 表示静音（填零缓冲） */
void audio_tone_start(uint32_t freq_hz);

/* 停止播放并静音 */
void audio_tone_stop(void);

/* ============================================================
 * Phase 4：USB CDC → 环形缓冲 → 双缓冲 PCM 流播放
 *   环形缓冲：字节流（小端 16bit 交错立体声，与 I2S DMA 布局一致）
 *   双缓冲：DMA 循环播放整块，半传输(HT)/全传输(TC)中断里 refill 刚播完的半区
 * ============================================================ */
#define AUDIO_STREAM_HALF_FRAMES  1024u          /* 每个半区的立体声帧数 */
#define AUDIO_STREAM_HALF_LEN     (AUDIO_STREAM_HALF_FRAMES * 2u)  /* halfword 个数 */
#define AUDIO_RING_SIZE           32768u         /* 字节环形缓冲（必须是 2^n）；32KB≈186ms，抗 USB 抖动 */
#define AUDIO_RING_MASK           (AUDIO_RING_SIZE - 1u)

/* 启动 PCM 流播放（DMA 双缓冲循环；无数据时播放静音） */
void audio_stream_start(void);
/* 停止 PCM 流 */
void audio_stream_stop(void);
/* 把主机发来的 PCM 字节灌入环形缓冲（在 USB 中断里调用）；
 * 环形满时丢弃最旧数据以限制延迟；返回实际写入字节数 */
int audio_stream_push(const uint8_t *data, uint32_t len);
/* 当前环形缓冲已缓存字节数（调试用） */
uint32_t audio_stream_available(void);

/* LCD 歌词时间轴：DMA 实际消费的 PCM 字节总数（单调递增、只读）。
 * 由 stream_fill_half() 每次 refill 累加，代表真播出去的字节数。
 * 比 HAL_GetTick() 准：欠载/暂停/切源都不会让歌词进度漂移。
 * 音频输出链行为完全不变，仅新增一个计数器。 */
uint32_t audio_stream_consumed_bytes(void);
void     audio_stream_reset_consumed(void);

/* 歌词同步用：已播放时长(ms)，以"第一次出现真实 PCM 数据"为 0 点。
 * 断流超过约 0.8s 后再来数据会自动重新取 0 点（暂停/重放/换曲都能对齐）。
 * 与墙钟无关，也不受"开机后多久才点播放"影响。 */
uint32_t audio_stream_position_ms(void);

/* 软件音量（0~63，DMA refill 里定点乘法，不依赖 CODEC 的 I2C）。
 * 与 WM8978 的 SPK 音量是两级串联：这里管数字，那里管模拟。 */
void audio_stream_set_volume(uint8_t vol);
uint8_t audio_stream_volume(void);
void     audio_stream_reset_position(void);
/* 由上位机在 seek/倍速/切歌后下发的「歌词时间轴基准」（ms）。
 * 注意：这里传的是**已按倍速缩放过**的时间，和设备上那份 LRC 的时间戳同尺度。 */
void     audio_stream_set_position(uint32_t ms);

/* 供外部读取的两个句柄（调试用） */
extern I2S_HandleTypeDef g_i2s2_handle;
extern DMA_HandleTypeDef g_i2s2_tx_dma;

#endif /* __I2S_AUDIO_H */
