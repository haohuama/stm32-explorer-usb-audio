/* ============================================================
 * cdc_ctrl.h —— 复用 USB CDC 下行通道，给设备送「歌曲元数据 / 歌词 / 封面」
 *
 * 为什么走 CDC：音频本来就要电脑经 CDC 送 PCM，歌词/封面跟着同一条线下来，
 * 就不用 TF 卡、也不用每次改歌词都重烧固件。
 *
 * 时序（上位机负责）：
 *   ser.baudrate = 200000   → 进入控制模式（CDC_SET_LINE_CODING）
 *   发帧（SONG / LRC × N / LRC_END / COVER_ROW × 240）
 *   ser.baudrate = 115200   → 退出控制模式，下面才是 PCM
 * 播放期间不解析任何帧，**完全不碰现有音频链路**。
 *
 * 帧格式（小端）：
 *   'A' 'T' 'K' | type | len_lo len_hi | payload[len]
 *   type 0x01 SONG     : idx, tlen, title[GBK], alen, artist[GBK]
 *   type 0x02 LRC      : 歌词文本块（GBK，可多次，累加）
 *   type 0x03 LRC_END  : 空载荷 → 解析并生效
 *   type 0x04 COVER_ROW: row_lo, row_hi, 240×RGB565(小端)
 *   type 0x05 POS       : 4 字节 LE 毫秒，设置歌词时间轴基准（seek/倍速/切歌后用）
 *
 * 流控：收到一帧且主循环还没取走时，不再 arm OUT 端点 → 主机的 write 阻塞，
 *       天然不丢帧；主循环一次最多消化 8 帧，避免占着主循环不放。
 * ============================================================ */
#ifndef __CDC_CTRL_H
#define __CDC_CTRL_H

#include <stdint.h>

#define CDC_CTRL_BAUD   200000u     /* 上位机把这个波特率设上来 = 进入控制模式 */

void cdc_ctrl_set_enabled(int on);
int  cdc_ctrl_enabled(void);

/* USB 中断里调用：只做组帧/拷贝，绝不碰 LCD */
void cdc_ctrl_feed(const uint8_t *d, uint32_t n);

/* 中断里判断：还有未消费的整帧时返回 1（此时不要重新 arm OUT 端点） */
int  cdc_ctrl_frame_pending(void);

/* 主循环里调用：消化已就绪的帧（画封面行 / 解析歌词 / 换曲） */
void cdc_ctrl_poll(void);

#endif /* __CDC_CTRL_H */
