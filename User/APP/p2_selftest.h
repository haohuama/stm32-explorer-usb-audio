/* ============================================================
 * p2_selftest.h —— P2.1 零风险自检入口
 *
 * 做什么：f_mount → f_opendir 列目录 → 找第一个 .wav → 读 512B 头
 *         → 解析并打印 采样率/位深/声道/时长 → 校验是否适配 44.1k/16bit/立体声
 * 不做什么（关键）：
 *   - 不碰 I2S、不碰 DMA、不碰 WM8978、不碰 USB，不播放任何声音
 *   - 不写 TF 卡（FF_FS_READONLY=1）
 *   - 全部输出只走 CH340 → USART1
 *
 * 调用位置：main.c 里放在 MX_USART1_UART_Init() 之后、
 *           audio_i2s_init() / audio_stream_start() / MX_USB_DEVICE_Init() 之前。
 *           因此 SDIO 轮询读扇区时，USB 中断与 I2S DMA 都还没启动，零干扰。
 * ============================================================ */
#ifndef __P2_SELFTEST_H
#define __P2_SELFTEST_H

/* 打印回调（复用 main.c 的 uart_puts / uart_put_u32，避免引入 printf） */
typedef void (*p2_puts_fn)(const char *s);
typedef void (*p2_put_u32_fn)(uint32_t v);

/* 返回 0 = 挂载+目录+WAV 头全部通过；非 0 = 见串口打印的错误码 */
int p2_selftest_run(p2_puts_fn puts, p2_put_u32_fn put_u32);

#endif
