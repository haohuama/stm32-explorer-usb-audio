/* ============================================================
 * lcd_ui.c —— LCD 全屏歌词界面（模块1 USB CDC 模式）
 *
 * 关键约束（项目贯穿原则）：
 *   - 只读音频状态，不反向控制音频；UI 全在主循环，绝不进中断。
 *   - 歌词时间轴 = 真实 PCM 已播时长（audio_stream_position_ms()），
 *     与歌声同一基准；等静音不算时间。
 *   - 歌词只在"当前行变化"时重画，避免每帧刷屏抢总线。
 *   - 中文走内置 GBK 16x16 点阵（cn_font.h），按 2x2 像素块放大到 32px，
 *     不额外占 Flash。
 *   - 歌词数据在 lrc_data.h（由 Tools/lrc_playlist.py 生成）。
 *   - 曲目切换由上位机通过 USB 串口控制线（DTR/RTS）告知，不靠猜。
 * ============================================================ */
#include "lcd_ui.h"
#include "lcd.h"
#include "cn_font.h"
#include "lrc_data.h"         /* s_lrc1..4 / s_title1..4（自动生成） */
#include "i2s_audio.h"        /* audio_stream_reset_position() */
#include <string.h>
#include <stdlib.h>

/* ---- 4.3" 800x480 横屏，全屏歌词布局 ---- */
#define UI_W                 800u
#define UI_H                 480u
#define UI_TITLE_Y           2u        /* 顶部一行小字：歌名（16px） */
#define UI_Y0                24u       /* 第一行歌词的 y */
#define UI_LINE_H            56u       /* 行距（32px 字 + 24px 间隔） */
#define UI_LINES             8u        /* 屏上同时显示 8 行 */
#define UI_TEXT_X            26u       /* 正文左边距（左侧留给高亮指示条） */
#define UI_SCALE             2u        /* 点阵放大倍数：16 -> 32 px */
#define UI_TICK_MS           100u      /* 10fps 上限，实际只在换行时重画 */

#define UI_COL_BG            BLACK
#define UI_COL_TITLE         GRAY
#define UI_COL_HINT          GRAY
#define UI_COL_ACTIVE        YELLOW
#define UI_COL_NORMAL        GRAYBLUE

#define LRC_MAX_LINES        96u
#define SONG_COUNT           4u        /* 与 Tools/lrc_playlist.py 的 MAX_SONGS 一致 */

typedef struct {
    uint32_t t_ms;
    char     text[64];      /* GBK 字节串，'\0' 结尾 */
} ui_line_t;

/* 每首一份解析结果 */
static ui_line_t  s_lines[SONG_COUNT][LRC_MAX_LINES];
static int        s_n[SONG_COUNT];

/* 歌词/标题表（来自 lrc_data.h） */
static const char *const s_lrcs[SONG_COUNT]   = { s_lrc1, s_lrc2, s_lrc3, s_lrc4 };
static const char *const s_titles[SONG_COUNT] = { s_title1, s_title2, s_title3, s_title4 };

static ui_line_t *s_cur = s_lines[0];   /* 当前生效的那一份 */
static int        s_cur_n = 0;
static int        s_song = 0;
static int        s_active = -1;
static int        s_last_active = -2;
static uint32_t   s_last_tick = 0;
static char       s_track[64] = "";
static uint8_t    s_ready = 0;
/* 选曲信号：USB 中断里置位，主循环消费（中断里绝不画屏/换算） */
static volatile uint8_t s_req_song = 0;
static volatile uint8_t s_song_pending = 0;

/* ------------------------------------------------------------
 * 查 GBK 字形（线性表，仅在换行时用到）
 * ------------------------------------------------------------ */
static const uint8_t *cn_bits(uint16_t gbk)
{
    uint16_t i;
    for (i = 0; i < CN_FONT_COUNT; i++) {
        if (g_cn_font[i].gbk == gbk) return g_cn_font[i].bits;
    }
    return 0;
}

/* 画一个 16x16 点阵，按 scale 放大；同一行连续亮点合并成一次 lcd_fill */
static void draw_glyph(uint16_t x, uint16_t y, const uint8_t *bits,
                       uint16_t color, uint8_t scale)
{
    uint16_t row, col, line, run;

    for (row = 0; row < 16u; row++) {
        line = ((uint16_t)bits[row * 2u] << 8) | bits[row * 2u + 1u];
        if (line == 0u) continue;
        col = 0;
        while (col < 16u) {
            if (line & (0x8000u >> col)) {
                run = col;
                while (col < 16u && (line & (0x8000u >> col))) col++;
                lcd_fill((uint16_t)(x + run * scale),
                         (uint16_t)(y + row * scale),
                         (uint16_t)(x + col * scale - 1u),
                         (uint16_t)(y + row * scale + scale - 1u),
                         color);
            } else {
                col++;
            }
        }
    }
}

/* 逐字节绘制 GBK 字符串（scale 倍放大）；返回宽度（像素） */
static uint16_t draw_gbk_string(uint16_t x, uint16_t y, const char *s,
                               uint16_t color, uint8_t scale)
{
    uint16_t px = x;
    const uint8_t *p = (const uint8_t *)s;
    const uint8_t *bits;
    uint16_t gbk;
    uint16_t cw = (uint16_t)(16u * scale);

    if (!s) return 0;
    while (*p) {
        if (*p < 0x80u) {                     /* 未启用 ASCII 字模，跳过 */
            px += (uint16_t)(8u * scale);
            p++;
            continue;
        }
        if (*(p + 1) == 0) break;
        gbk = ((uint16_t)(*p) << 8) | *(p + 1);
        bits = cn_bits(gbk);
        if (bits) draw_glyph(px, y, bits, color, scale);
        px += cw;
        p += 2;
        if (px + cw > UI_W) break;
    }
    return (uint16_t)(px - x);
}

/* ------------------------------------------------------------
 * LRC 解析：[mm:ss.xx]文本，按时间升序
 * ------------------------------------------------------------ */
static int parse_lrc(const char *src, ui_line_t *dst)
{
    const char *p = src;
    int n = 0;

    memset(dst, 0, sizeof(ui_line_t) * LRC_MAX_LINES);
    if (!src) return 0;

    while (*p && n < (int)LRC_MAX_LINES) {
        uint32_t mm, ss, cc;
        const char *e;
        size_t len;

        if (*p != '[') { p++; continue; }
        mm = (uint32_t)strtoul(p + 1, (char **)&e, 10);
        if (*e != ':') { p++; continue; }
        ss = (uint32_t)strtoul(e + 1, (char **)&e, 10);
        if (*e == '.') {
            cc = (uint32_t)strtoul(e + 1, (char **)&e, 10);
            if (cc > 99u) cc = 99u;
        } else {
            cc = 0;
        }
        if (*e != ']') { p++; continue; }
        e++;
        {
            const char *nl = strchr(e, '\n');
            const char *cr = strchr(e, '\r');
            const char *stop = nl ? nl : (cr ? cr : 0);
            if (cr && nl && cr < nl) stop = cr;
            len = stop ? (size_t)(stop - e) : strlen(e);
        }
        if (len > sizeof(dst[n].text) - 1u) len = sizeof(dst[n].text) - 1u;
        memcpy(dst[n].text, e, len);
        dst[n].text[len] = '\0';
        dst[n].t_ms = (mm * 60u + ss) * 1000u + cc * 10u;
        n++;
        {
            const char *nl = strchr(e, '\n');
            p = nl ? nl + 1 : (e + strlen(e));
        }
    }
    return n;
}

static int find_active(uint32_t ms)
{
    int i, a = -1;
    for (i = 0; i < s_cur_n; i++) {
        if (s_cur[i].t_ms <= ms) a = i; else break;
    }
    return a;
}

/* 顶部小字：当前曲名 */
static void draw_title(void)
{
    lcd_fill(0, 0, UI_W - 1u, UI_Y0 - 4u, UI_COL_BG);
    draw_gbk_string(8u, UI_TITLE_Y, s_titles[s_song], UI_COL_TITLE, 1u);
}

/* 全屏歌词：当前行居中，其余灰蓝；只在换行时调用 */
static void draw_lyrics(int active)
{
    int i, first;
    uint16_t y;

    lcd_fill(0, UI_Y0 - 2u, UI_W - 1u, UI_H - 1u, UI_COL_BG);

    if (s_cur_n == 0) {
        draw_gbk_string(300u, 200u, (const char *)"\xCE\xDE\xB8\xE8\xB4\xCA",
                        UI_COL_HINT, 2u);
        return;
    }

    first = active - (int)(UI_LINES / 2u);
    if (first < 0) first = 0;
    if (first > s_cur_n - (int)UI_LINES) {
        first = (s_cur_n > (int)UI_LINES) ? (s_cur_n - (int)UI_LINES) : 0;
    }

    for (i = 0; i < (int)UI_LINES; i++) {
        int idx = first + i;
        if (idx >= s_cur_n) break;
        y = (uint16_t)(UI_Y0 + i * UI_LINE_H);
        if (idx == active) {
            lcd_fill(6u, (uint16_t)(y + 4u), 16u, (uint16_t)(y + 28u), UI_COL_ACTIVE);
            draw_gbk_string(UI_TEXT_X, y, s_cur[idx].text, UI_COL_ACTIVE, UI_SCALE);
        } else {
            draw_gbk_string(UI_TEXT_X, y, s_cur[idx].text, UI_COL_NORMAL, UI_SCALE);
        }
    }
}

/* ------------------------------------------------------------
 * 公开接口
 * ------------------------------------------------------------ */
/* 上位机通过 USB 控制线选曲（0..SONG_COUNT-1）。
 * 在 USB 中断上下文调用：只记标志，不碰 LCD。 */
void lcd_ui_select_song(uint8_t idx)
{
    if (idx >= SONG_COUNT) return;
    s_req_song = idx;
    s_song_pending = 1;
}

uint8_t lcd_ui_init(void)
{
    uint8_t k;

    lcd_init();
    LCD_BL(1);
    lcd_display_dir(1);         /* 横屏 800x480 */

    for (k = 0; k < SONG_COUNT; k++) {
        s_n[k] = parse_lrc(s_lrcs[k], s_lines[k]);
    }
    s_song  = 0;
    s_cur   = s_lines[0];
    s_cur_n = s_n[0];

    lcd_clear(UI_COL_BG);
    draw_title();
    s_active = -1;
    s_last_active = -2;
    s_ready = 1;
    draw_lyrics(-1);
    return 0;
}

void lcd_ui_tick(uint32_t played_ms)
{
    uint32_t now;
    int active;

    if (!s_ready) return;
    now = HAL_GetTick();
    if ((uint32_t)(now - s_last_tick) < UI_TICK_MS) return;
    s_last_tick = now;

    /* 1) 处理上位机选曲信号 */
    if (s_song_pending) {
        s_song_pending = 0;
        if ((int)s_req_song != s_song) {
            s_song  = (int)s_req_song;
            s_cur   = s_lines[s_song];
            s_cur_n = s_n[s_song];
            draw_title();
        }
        audio_stream_reset_position();     /* 新曲：歌词时钟清零 */
        s_last_active = -2;
    }

    /* 2) 歌词时间 = 已播放的真实 PCM 时长 */
    active = find_active(played_ms);
    if (active != s_last_active) {
        draw_lyrics(active);
        s_last_active = active;
        s_active = active;
    }
}

void lcd_ui_set_track(const char *gbk_name)
{
    size_t l;
    if (!gbk_name) return;
    l = strlen(gbk_name);
    if (l > sizeof(s_track) - 1u) l = sizeof(s_track) - 1u;
    memcpy(s_track, gbk_name, l);
    s_track[l] = '\0';
    if (s_ready) {
        lcd_fill(0, 0, UI_W - 1u, UI_Y0 - 4u, UI_COL_BG);
        draw_gbk_string(8u, UI_TITLE_Y, s_track, UI_COL_TITLE, 1u);
    }
}

int lcd_ui_load_lrc(const char *gbk_lrc)
{
    s_n[0] = parse_lrc(gbk_lrc ? gbk_lrc : s_lrc1, s_lines[0]);
    if (s_song == 0) { s_cur = s_lines[0]; s_cur_n = s_n[0]; }
    s_last_active = -2;
    return s_n[0];
}

int lcd_ui_line_count(void)  { return s_cur_n; }
int lcd_ui_active_line(void) { return s_active; }
