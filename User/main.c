     /* ============================================================
 * main.c —— Phase 4：USB CDC → I2S2 → WM8978（电脑经虚拟串口发 PCM）
 *
 * 目标：不碰 USB、不碰 LCD，先验证最核心的音频链路：
 *      MCU(I2S2 主模式, 44.1kHz/16bit/飞利浦) --MCLK/BCLK/LRCK/SD-->
 *      WM8978 --内部DAC+功放--> SPK 绿色端子 --> 喇叭
 *
 * 判据：喇叭发出连续稳定的 1kHz 单音（不是断续、不是爆音）。
 *
 * 本工程适配要点（沿用上一轮修好的做法）：
 *   1) 时钟用本文件自包含的 SystemClock_Config()（HSE8M→168M），
 *      不依赖 sys.c / sys.h 的包含路径。
 *   2) 串口保留本地 huart1 + MX_USART1_UART_Init()，【不定义】
 *      HAL_UART_MspInit —— 工程 usart.c 已提供强符号版本。
 *   3) 不调用工程的 usart_init()（会开 RX 中断而 it.c 没有 USART1_IRQHandler）。
 *   4) HAL_I2S_MspInit 由 i2s_audio.c 提供（配 PB12/13、PC3、PC6 + DMA1_Stream4）。
 *   5) WM8978 的 I2C 走 PB8(SCL)/PB9(SDA) —— 本板已实测确认 CODEC 挂在这组。
 *
 * 已有实测依据（2026-11-13 11:00）：I2C 只读探测结果
 *   [PB8/PB9] W0x34=ACK R0x35=NACK W0x20=NACK R0x21=NACK => WM8978
 * ============================================================ */
#include "stm32f4xx_hal.h"
#include "i2c_soft.h"
#include "wm8978.h"
#include "i2s_audio.h"
#include "usb_device.h"
#include "audio_source.h"      /* P2.0 统一切源接口契约 */
#include "lcd_ui.h"            /* LCD 歌词界面（模块1 只读播放状态） */
#include "lcd.h"               /* lcddev.id：启动时打印面板型号 */
#include "key.h"               /* 板载 4 键：上下音量 / 左右切歌 */
#include "cdc_ctrl.h"          /* USB 下行控制帧：歌词/封面 */
#include "tp.h"                /* 触屏 XPT2046：屏幕上的上一首/播放暂停/下一首 */

/* usbd_cdc_if.c：给上位机发 1 字节命令（P 暂停 / R 继续 / N 下一首 / B 重播） */
extern int CDC_Cmd_Send(uint8_t c);
extern int CDC_Cmd_Send2(uint8_t c, uint8_t d);   /* 'S'+idx：屏上切歌通知电脑换 WAV */

/* ---- P2.1 TF 卡自检开关 ----------------------------------------
 * Keil 已于 2026-11-13 授权（MDK-Community，32KB 限制解除），但 TF 卡这条
 * 支线仍默认不编入：ff.c/ffunicode.c/diskio.c/sdio_sd.c/p2_selftest.c
 * 还没加回 uvprojx。当前主线是「USB CDC 收 PCM + LCD 封面/歌词」。
 *
 * 要恢复 P2.1：
 *   1) 把上述 5 个 .c 加回 uvprojx（Middlewares/FATFS + User/APP 组）
 *   2) ffconf.h 里 FF_USE_LFN 改回 1（需要 ffunicode.c）
 *   3) 本宏改为 1
 * ---------------------------------------------------------------- */
#define P2_SELFTEST_ENABLE   0

#if P2_SELFTEST_ENABLE
#include "p2_selftest.h"
#endif

UART_HandleTypeDef huart1;

/* WM8978 的控制总线：PB8=SCL / PB9=SDA（实测确认） */
static const soft_i2c_t codec_bus = { GPIOB, GPIO_PIN_8, GPIO_PIN_9 };

/* ---------- 串口小工具（不依赖 printf，免 C 库/半主机麻烦）---------- */
static void uart_putc(char c)
{
    HAL_UART_Transmit(&huart1, (uint8_t *)&c, 1, HAL_MAX_DELAY);
}
static void uart_puts(const char *s)
{
    while (*s) uart_putc(*s++);
}
static void uart_put_u8(uint8_t v)
{
    char b[4];
    int i = 0;
    if (v == 0) b[i++] = '0';
    while (v) { b[i++] = (char)('0' + (v % 10)); v /= 10; }
    while (i) uart_putc(b[--i]);
}
static void uart_put_u32(uint32_t v)
{
    char b[11];
    int i = 0;
    if (v == 0) b[i++] = '0';
    while (v) { b[i++] = (char)('0' + (v % 10)); v /= 10; }
    while (i) uart_putc(b[--i]);
}

/* 打印面板 ID（4 位十六进制）——用于判断 LCD 控制器是否被识别 */
static void uart_put_panel_id(void)
{
    static const char hex[] = "0123456789ABCDEF";
    uint16_t id = (uint16_t)lcddev.id;
    uart_put_u8((uint8_t)hex[(id >> 12) & 0x0F]);
    uart_put_u8((uint8_t)hex[(id >> 8) & 0x0F]);
    uart_put_u8((uint8_t)hex[(id >> 4) & 0x0F]);
    uart_put_u8((uint8_t)hex[id & 0x0F]);
}

/* ---------- USART1：PA9(TX)/PA10(RX)，115200 ----------
 * 引脚由工程 usart.c 的 HAL_UART_MspInit 配置（不在此重复定义） */
static void MX_USART1_UART_Init(void)
{
    huart1.Instance          = USART1;
    huart1.Init.BaudRate     = 115200;
    huart1.Init.WordLength   = UART_WORDLENGTH_8B;
    huart1.Init.StopBits     = UART_STOPBITS_1;
    huart1.Init.Parity       = UART_PARITY_NONE;
    huart1.Init.Mode         = UART_MODE_TX_RX;
    huart1.Init.HwFlowCtl    = UART_HWCONTROL_NONE;
    huart1.Init.OverSampling = UART_OVERSAMPLING_16;
    HAL_UART_Init(&huart1);
}

/* ---------- 时钟：HSE 8MHz -> PLL 168MHz ---------- */
static void SystemClock_Config(void)
{
    RCC_OscInitTypeDef osc = {0};
    RCC_ClkInitTypeDef clk = {0};

    __HAL_RCC_PWR_CLK_ENABLE();
    __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);

    osc.OscillatorType = RCC_OSCILLATORTYPE_HSE;
    osc.HSEState       = RCC_HSE_ON;
    osc.PLL.PLLState   = RCC_PLL_ON;
    osc.PLL.PLLSource  = RCC_PLLSOURCE_HSE;
    osc.PLL.PLLM = 8;
    osc.PLL.PLLN = 336;
    osc.PLL.PLLP = RCC_PLLP_DIV2;
    osc.PLL.PLLQ = 7;
    if (HAL_RCC_OscConfig(&osc) != HAL_OK) { while (1); }

    clk.ClockType      = RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_SYSCLK |
                         RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2;
    clk.SYSCLKSource   = RCC_SYSCLKSOURCE_PLLCLK;
    clk.AHBCLKDivider  = RCC_SYSCLK_DIV1;    /* HCLK 168MHz */
    clk.APB1CLKDivider = RCC_HCLK_DIV4;      /* PCLK1 42MHz  */
    clk.APB2CLKDivider = RCC_HCLK_DIV2;      /* PCLK2 84MHz  */
    if (HAL_RCC_ClockConfig(&clk, FLASH_LATENCY_5) != HAL_OK) { while (1); }
}

/* ============================================================
 * 主流程
 * ============================================================ */
int main(void)
{
    uint8_t err;

    HAL_Init();
    SystemClock_Config();
    MX_USART1_UART_Init();

    uart_puts("\r\n==== 电脑音频播放器  USB CDC -> I2S2 -> WM8978 + LCD ====\r\n");
    uart_puts("44.1k/16bit/立体声 / 电脑经虚拟串口发 PCM / 屏上显示封面+歌词\r\n");

    /* ---- P2.0 / P2.1：TF 卡零风险自检 -------------------------------
     * 位置要求：必须在 audio_i2s_init() / audio_stream_start() /
     *           MX_USB_DEVICE_Init() 之前。
     * 原因：SDIO 用轮询读扇区，此时 I2S DMA 与 USB 中断均未启动，
     *       自检不会与任何实时链路争总线；自检本身也完全不碰这些外设。
     * 失败不影响主线：没插卡/挂载失败只打印错误，下面照常启动 USB CDC。
     * 输出只走 CH340(USART1)，CDC 口不打印（遵守项目约定）。
     * ---------------------------------------------------------------- */
    src_init();                                   /* P2.0 状态机：纯内存操作 */
#if P2_SELFTEST_ENABLE
    (void)p2_selftest_run(uart_puts, uart_put_u32);
#else
    uart_puts("[P2.1] TF card self-test: DISABLED (not linked in this build)\r\n");
#endif

    /* ---- 1. 先起 I2S（MCLK/BCLK/LRCK 立即输出）---- */
    err = audio_i2s_init();
    uart_puts("[1] I2S2 init : ");
    if (err == 0) { uart_puts("OK\r\n"); }
    else          { uart_puts("FAIL code="); uart_put_u8(err); uart_puts("\r\n"); }

    /* ---- 2. 配置 WM8978（I2C，只写器件）---- */
    WM8978_BindBus(&codec_bus);
    err = WM8978_Init();
    uart_puts("[2] WM8978_Init: ");
    if (err == 0) { uart_puts("OK (I2C 全部 ACK)\r\n"); }
    else          { uart_puts("FAIL (有寄存器写不进 → 查 PB8/PB9 上拉/供电)\r\n"); }

    WM8978_PlayMode();
    /* 音量 0x30/63：从满档 0x3F 回退，给板载功放留余量。
     * 实测两首歌贴顶样本仅 0.002%，"炸"不是数字削波，而是模拟端满档过载；
     * 数字端保持 gain 由上位机控制，这里只把模拟增益落到干净档。 */
    WM8978_SPKvol_Set(0x30);   /* 模拟音量固定 -9dB 干净档，之后不再改 */
    audio_stream_set_volume(38);  /* 数字音量默认 38/100≈0.38x，音量键只改这个 */
    uart_puts("[3] PlayMode  : DAC开 / 输入关 / 输出开 / 模拟固定0x30 + 数字38/100\r\n");
    /* ---- 4. 启动 PCM 流播放（无数据时静音）---- */
    audio_stream_start();
    uart_puts("[4] audio stream: 双缓冲循环启动（静音待数据）\r\n");

    /* ---- 5. 启动 USB 设备（CDC 虚拟串口，等主机枚举）---- */
    MX_USB_DEVICE_Init();
    uart_puts("[5] USB CDC    : 已启动，等主机枚举 + 发 PCM\r\n");

    /* ---- 6. 点亮 LCD（放在 USB 之后，避免 FSMC 初始化影响枚举时序）----
     * 只初始化一次；之后全在主循环 tick，绝不进任何中断。
     * 屏上版式：上半屏 = 封面 + 歌名/歌手/进度条/时间，下半屏 = 滚动歌词。
     * 歌名/歌手/封面/歌词全部来自自动生成的头文件（lrc_data.h / cover_img.h）。 */
    (void)lcd_ui_init();
    uart_puts("[6] LCD       : id=0x");
    uart_put_panel_id();
    uart_puts(" (NT35510=0x5510 / ILI9341=0x9341)\r\n");

    /* 触屏（XPT2046，位操作 SPI）：只做「有没有按下 + 坐标」，
     * 面板左下角三个按钮靠它；没接触摸时 T_PEN 上拉为高，不会误触。 */
    tp_init();
    uart_puts("[7] TOUCH     : XPT2046  T_PEN=PB1 T_CS=PC13 T_MISO=PB2 T_MOSI=PF11 T_SCK=PB0\r\n");
    uart_puts("[7] TP PEN    : 空闲电平=");
    uart_put_u8(tp_pen_level());
    uart_puts(" (1=高/未按, 0=低)  按屏幕会打印 [TP] x= y=\r\n");

    uart_puts("---- 预期现象 ----\r\n");
    uart_puts("屏: 上半屏封面照片 + 歌名/歌手/进度条, 下半屏歌词(当前句高亮)\r\n");
    uart_puts("电脑识别\"WM8978 CDC PCM\"虚拟串口 -> 跑 host_cdc_sender.py 发 WAV -> 喇叭出声\r\n");
    uart_puts("  py Tools\\host_cdc_sender.py --auto --wait --playlist --gain 1.0\r\n");
    uart_puts("  (单首: -f Tools\\pl05.wav; 切歌靠文件名 plNN -> idx=NN-1)\r\n");
    uart_puts("若只静音: 查串口是否打开/脚本端口号/WAV(44.1k,16bit,立体声)\r\n");
    uart_puts("若歌名是方块: lcd.h 的 LCD_KEEP_ASCII_FONT 必须为 1\r\n");

    /* ---- 7. 按键（PE4/PE3/PE2 + PA0）：上下调音量、左右切曲 ----
     * 按键只在主循环 10ms 轮询，不进中断；消抖与长按重复在 key.c 里做。 */
    key_init();
    uart_puts("[7] KEY       : KEY0=下一首 / KEY2=上一首 / KEY1=音量- / WK_UP=音量+\r\n");
    uart_puts("              : 音量键按住可连加/连减；播放暂停只在屏幕按钮上\r\n");
    uart_puts("[7] KEY raw   : 0x");
    uart_put_u8(key_raw_bits());
    uart_puts("  <- 手不按键时应为 0x00；不是 0 说明该键被压住或悬空\r\n");

    /* 主循环：非阻塞。UI 内部限帧 10fps，只在主循环刷新，
     * 绝不进 DMA/USB 中断；时间轴取 DMA 实际消费字节数。 */
    {
        uint32_t last_log = 0;
        uint8_t  vol = 38u;      /* 0~100 共 101 档，默认 38；WK_UP 加、KEY1 减 */
        uint8_t  paused = 0;

        while (1) {
            key_evt_t ev = key_scan();

            if (ev == KEY_VOL_UP || ev == KEY_VOL_DN) {
                if (ev == KEY_VOL_UP) {
                    vol = (uint8_t)((vol >= 100u) ? 100u : vol + 1u);
                } else {
                    vol = (uint8_t)((vol == 0u) ? 0u : vol - 1u);
                }
                audio_stream_set_volume(vol);  /* 音量只走数字端：不碰 I2C，不会被卡住 */
                lcd_ui_set_volume(vol);
                uart_puts("[KEY] VOL=");
                uart_put_u8(vol);
                uart_puts("/100\r\n");
            } else if (ev == KEY_NEXT || ev == KEY_PREV) {
                int cur = lcd_ui_current_song();
                int n   = (int)lcd_ui_song_count();
                int nxt = (ev == KEY_NEXT) ? ((cur + 1) % n) : ((cur + n - 1) % n);

                /* 注意：音频仍由电脑送，这里换的是屏上的曲目（封面/歌词/时间轴）。
                 * 要让声音也跟着换，在电脑端换文件（见 docs 的说明）。 */
                (void)CDC_Cmd_Send2((uint8_t)'S', (uint8_t)nxt);
                lcd_ui_set_meta("", "");        /* 按键切曲：回到内置歌名/歌手 */
                lcd_ui_select_song((uint8_t)nxt);
                uart_puts("[KEY] song -> ");
                uart_put_u8((uint8_t)(nxt + 1));
                uart_puts(" (屏幕切曲；声音仍来自电脑端当前文件)\r\n");
            }

            /* 触屏按钮：上一首 / 播放暂停 / 下一首
             * 每次读到有效坐标都打印诊断；350ms 内不重复触发。 */
            {
                static uint32_t last_tp = 0, last_pr = 0;
                uint16_t tx = 0, ty = 0;

                if (tp_scan(&tx, &ty)) {
                    /* 诊断：按一下屏幕若串口有 [TP]，说明驱动层是通的 */
                    if ((uint32_t)(HAL_GetTick() - last_pr) >= 250u) {
                        uint16_t rx = 0, ry = 0;
                        last_pr = HAL_GetTick();
                        tp_last_raw(&rx, &ry);
                        uart_puts("[TP] x="); uart_put_u32(tx);
                        uart_puts(" y=");    uart_put_u32(ty);
                        uart_puts(" raw=");  uart_put_u32(rx);
                        uart_puts(",");      uart_put_u32(ry);
                        uart_puts("\r\n");
                    }

                    if ((uint32_t)(HAL_GetTick() - last_tp) >= 350u) {
                        uint8_t hit = lcd_ui_hit(tx, ty);

                        if (hit) {
                            last_tp = HAL_GetTick();
                            lcd_ui_btn_flash(hit);
                            if (hit == 2u) {
                                paused = (uint8_t)!paused;
                                (void)CDC_Cmd_Send(paused ? (uint8_t)'P' : (uint8_t)'R');
                                lcd_ui_set_paused(paused);
                                uart_puts(paused ? "[TP] PAUSE\r\n" : "[TP] PLAY\r\n");
                            } else {
                                int cur = lcd_ui_current_song();
                                int n   = (int)lcd_ui_song_count();
                                int nxt = (hit == 1u) ? ((cur + n - 1) % n) : ((cur + 1) % n);

                                (void)CDC_Cmd_Send2((uint8_t)'S', (uint8_t)nxt);
                                lcd_ui_set_meta("", "");
                                lcd_ui_select_song((uint8_t)nxt);
                                uart_puts("[TP] song -> ");
                                uart_put_u8((uint8_t)(nxt + 1));
                                uart_puts("\r\n");
                            }
                        }
                    }
                }
            }

            cdc_ctrl_poll();                        /* 消化 USB 下发的歌词/封面帧 */
            lcd_ui_tick(audio_stream_position_ms());
            HAL_Delay(10);

            if (HAL_GetTick() - last_log >= 3000u) {
                last_log = HAL_GetTick();
                uart_puts("... USB CDC running, ring=");
                uart_put_u32(audio_stream_available());
                uart_puts(" bytes\r\n");
                {
                    uint32_t pen = 0, ok = 0, bad = 0;
                    tp_stats(&pen, &ok, &bad);
                    uart_puts("      TP: pen="); uart_put_u32(pen);
                    uart_puts(" ok=");  uart_put_u32(ok);
                    uart_puts(" bad="); uart_put_u32(bad);
                    uart_puts("\r\n");
                }
            }
        }
    }
}
