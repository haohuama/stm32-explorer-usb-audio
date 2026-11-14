/* ============================================================
 * cdc_ctrl.c —— 控制帧接收（USB 中断组帧 + 主循环执行）
 *
 * 分工：
 *   cdc_ctrl_feed()  ← USB 中断：逐字节组帧，凑满一帧就搬到 s_ready，
 *                      然后"停止 arm OUT 端点"由 usbd_cdc_if.c 处理（流控）
 *   cdc_ctrl_poll()  ← 主循环：画封面行、解析歌词、换曲，并在取走一帧后
 *                      调用 CDC_CTRL_Rearm() 继续收
 *
 * 两个缓冲区（s_work 收 / s_ready 待处理），SPSC 交接，不需要临界区：
 * 只有 flag 清零后中断才会写 s_ready。
 * ============================================================ */
#include "cdc_ctrl.h"
#include "lcd_ui.h"
#include "lcd.h"
#include "i2s_audio.h"        /* audio_stream_set_position()：歌词时间轴基准 */
#include <string.h>

/* usbd_cdc_if.c 提供：重新武装 CDC OUT 端点 */
extern void CDC_CTRL_Rearm(void);

#define FR_MAGIC0   0x41u   /* 'A' */
#define FR_MAGIC1   0x54u   /* 'T' */
#define FR_MAGIC2   0x4Bu   /* 'K' */
#define FR_HDR      6u
#define FR_MAX      512u    /* 单帧最大载荷（封面行 482B 够用） */

#define T_SONG      0x01u
#define T_LRC       0x02u
#define T_LRC_END   0x03u
#define T_COVER_ROW 0x04u
#define T_POS       0x05u     /* 4 字节 LE 毫秒：歌词时间轴基准 */

#define LRC_ACC_MAX 8192u
#define POLL_FRAMES 8       /* 一次主循环最多消化多少帧 */

static volatile uint8_t s_enabled;

/* ---- 中断侧组帧 ---- */
static uint8_t  s_hdr[FR_HDR];
static uint8_t  s_hdr_n;
static uint16_t s_need;
static uint16_t s_got;
static uint8_t  s_work[FR_MAX];

/* ---- 中断 -> 主循环 交接 ---- */
static uint8_t           s_ready[FR_HDR + FR_MAX];
static volatile uint16_t s_ready_len;
static volatile uint8_t  s_ready_flag;

/* ---- 主循环侧状态 ---- */
static char     s_lrc_acc[LRC_ACC_MAX];
static uint32_t s_lrc_n = 0xFFFFFFFFu;   /* 0xFFFFFFFF = 还没收到 LRC 帧 */
static uint16_t s_cover_row[240];
static uint8_t  s_pay[FR_MAX];           /* 主循环侧载荷副本（不能和 s_work 共用） */

/* ------------------------------------------------------------ */
void cdc_ctrl_set_enabled(int on)
{
    s_enabled = on ? 1u : 0u;
    s_hdr_n = 0;
    s_ready_flag = 0;
    s_lrc_n = 0xFFFFFFFFu;
}

int cdc_ctrl_enabled(void) { return s_enabled; }

int cdc_ctrl_frame_pending(void) { return s_ready_flag ? 1 : 0; }

/* 一帧收齐：搬进 s_ready（此时主循环保证没有未处理帧） */
static void publish(void)
{
    memcpy(s_ready, s_hdr, FR_HDR);
    if (s_need) memcpy(s_ready + FR_HDR, s_work, s_need);
    s_ready_len  = (uint16_t)(FR_HDR + s_need);
    s_ready_flag = 1;
    s_hdr_n = 0;
    s_got = 0;
}

/* 头部前 3 字节不是 'A''T''K'：左移一字节重新找同步 */
static void resync(void)
{
    uint8_t i;
    for (i = 1; i < FR_HDR; i++) s_hdr[i - 1u] = s_hdr[i];
    s_hdr_n = (uint8_t)(FR_HDR - 1u);
}

void cdc_ctrl_feed(const uint8_t *d, uint32_t n)
{
    uint32_t i;

    for (i = 0; i < n; i++) {
        uint8_t b = d[i];

        if (s_hdr_n < FR_HDR) {
            s_hdr[s_hdr_n++] = b;
            if (s_hdr_n < FR_HDR) continue;

            if (s_hdr[0] != FR_MAGIC0 || s_hdr[1] != FR_MAGIC1 || s_hdr[2] != FR_MAGIC2) {
                resync();
                continue;
            }
            s_need = (uint16_t)s_hdr[4] | ((uint16_t)s_hdr[5] << 8);
            s_got = 0;
            if (s_need > FR_MAX) {       /* 长度非法，丢帧重新同步 */
                s_hdr_n = 0;
                continue;
            }
            if (s_need == 0u) publish();
            continue;
        }

        s_work[s_got++] = b;
        if (s_got >= s_need) publish();
    }
}

/* ------------------------------------------------------------
 * 主循环侧：执行一帧
 * ------------------------------------------------------------ */
static void draw_cover_row(uint16_t row, const uint16_t *px)
{
    uint16_t i;

    if (row >= 240u) return;
    lcd_set_cursor(0, row);
    lcd_write_ram_prepare();
    for (i = 0; i < 240u; i++) LCD->LCD_RAM = px[i];
}

static void handle_frame(uint8_t type, const uint8_t *p, uint16_t len)
{
    switch (type) {
        case T_SONG: {
            /* idx, tlen, title[GBK], alen, artist[GBK] */
            uint8_t idx, tlen, alen;
            char title[48], artist[48];
            uint16_t off = 0;

            if (len < 2u) break;
            idx = p[off++];
            tlen = p[off++];
            if ((uint16_t)(off + tlen) > len || tlen > 40u) break;
            memcpy(title, p + off, tlen);
            title[tlen] = '\0';
            off = (uint16_t)(off + tlen);
            if ((uint16_t)(off + 1u) > len) break;
            alen = p[off++];
            if ((uint16_t)(off + alen) > len || alen > 40u) alen = 0;
            memcpy(artist, p + off, alen);
            artist[alen] = '\0';

            s_lrc_n = 0;                       /* 准备接这首的歌词 */
            lcd_ui_select_song(idx);
            lcd_ui_set_meta(title, artist);
            break;
        }
        case T_LRC:
            if (s_lrc_n == 0xFFFFFFFFu) s_lrc_n = 0;
            if (s_lrc_n + len < LRC_ACC_MAX - 1u) {
                memcpy(s_lrc_acc + s_lrc_n, p, len);
                s_lrc_n += len;
            }
            break;

        case T_LRC_END:
            if (s_lrc_n != 0xFFFFFFFFu && s_lrc_n > 0u) {
                s_lrc_acc[s_lrc_n] = '\0';
                lcd_ui_load_lrc(s_lrc_acc);    /* 解析 + 下一拍重画 */
            }
            break;

        case T_POS: {
            /* 上位机 seek / 换倍速 / 切歌后同步歌词时间轴，
             * 传进来的是「已按倍速缩放」的时间，与下发 LRC 的时间戳同尺度。 */
            if (len >= 4u) {
                uint32_t ms = (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
                              ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
                audio_stream_set_position(ms);
            }
            break;
        }
        case T_COVER_ROW: {
            uint16_t row, i;
            if (len < 2u + 480u) break;
            row = (uint16_t)p[0] | ((uint16_t)p[1] << 8);
            for (i = 0; i < 240u; i++) {
                s_cover_row[i] = (uint16_t)p[2u + i * 2u] |
                                 ((uint16_t)p[3u + i * 2u] << 8);
            }
            draw_cover_row(row, s_cover_row);
            break;
        }
        default:
            break;
    }
}

void cdc_ctrl_poll(void)
{
    int guard = POLL_FRAMES;

    if (!s_enabled) return;

    while (guard-- > 0 && s_ready_flag) {
        uint8_t  type = s_ready[3];
        uint16_t len  = (uint16_t)(s_ready_len - FR_HDR);

        /* 先拷出来再放行，中断可以继续往 s_ready 写下一帧。
         * 用静态缓冲而不是局部数组：这个工程 Stack 只有 1KB。 */
        if (len) memcpy(s_pay, s_ready + FR_HDR, len);
        s_ready_flag = 0;
        CDC_CTRL_Rearm();

        handle_frame(type, s_pay, len);
    }
}
