/* ============================================================
 * lcd_ui.h —— LCD 歌词与播放状态界面（模块1 USB CDC 模式）
 *
 * 设计要点：
 *   1) 只读音频状态：时间轴由 DMA 实际消费的 PCM 字节数推算，
 *      不占用 CDC 通道（CDC 只承载 PCM，禁止打印/控制字）。
 *   2) UI 全部在主循环执行，绝不在 DMA/USB 中断里刷屏；
 *      限帧 + 歌词带局部刷新，避免抢 FSMC/CPU 影响音频。
 *   3) 中文用内置精简 GBK 16x16 点阵（cn_font.h），
 *      ASCII 用 lcd.c 自带 asc2_1608；源码字符串为 GBK 字节。
 *   4) 内置【演示歌词】，明确标注非真实歌曲文本；
 *      提供 lcd_ui_load_lrc() 供后续替换为真 .lrc。
 *
 * 硬件：4.3" 800x480 8080 MCU 屏，FSMC NE4 / A6。
 *   与 SDIO(PC8-PC12,PD2)、I2S2(PB12/13,PC3/PC6)、USB(PA11/12) 无引脚冲突。
 * ============================================================ */
#ifndef __LCD_UI_H
#define __LCD_UI_H

#include <stdint.h>

/* 初始化屏：背光拉高、FSMC、控制器 ID 自动识别、画静态框架。
   返回 0=成功。必须在主循环开始前调用一次（音频启动之后更稳）。 */
uint8_t lcd_ui_init(void);

/* 主循环节拍：传入「已播放时长 ms」（来自 audio_stream_position_ms()）。
 * 该时间以"第一次出现真实 PCM"为 0 点，因此与歌声严格对齐。 */
void lcd_ui_tick(uint32_t played_ms);

/* 上位机通过 USB 串口控制线（DTR=bit0, RTS=bit1）选曲：
 *   0 = 第 1 首，1 = 第 2 首。可在 USB 中断里安全调用（只记标志）。
 * 有了它就不必靠"时长取模"猜曲目，单曲循环/任意顺序都正确。 */
void lcd_ui_select_song(uint8_t idx);

/* 设置当前曲目显示文本（GBK 编码，'\0' 结尾；可传 ASCII）。
   电脑推裸 PCM，MCU 不知道歌名，由 host 或固件填入。 */
void lcd_ui_set_track(const char *gbk_name);

/* 替换内置演示歌词。buf 为 GBK 编码 LRC 文本（[mm:ss.xx]歌词）。
   返回解析到的行数；0=失败。传入 NULL 恢复演示歌词。 */
int  lcd_ui_load_lrc(const char *gbk_lrc);

/* 当前解析出的歌词行数 / 当前高亮行（调试用，-1 表示无） */
int  lcd_ui_line_count(void);
int  lcd_ui_active_line(void);

#endif
