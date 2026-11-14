/* ============================================================
 * lcd_ui.c —— LCD 播放界面：上半屏 = 封面 / 歌曲信息，下半屏 = 滚动歌词
 *
 * 版式（4.3" 800x480 横屏）：
 *   y   0..239  上半屏
 *     x 0..239    封面 240x240（cover_img.h，RGB565，1:1 画）
 *     右侧         模糊底图上叠 歌名(32px) / 歌手(16px) / 进度条 / 时间
 *     （该曲没有封面数据时，上半屏画竖渐变 + 居中歌名，不留黑块）
 *   y 240        分隔线
 *   y 248..472   下半屏歌词：当前块高亮（左侧黄色指示条）
 *
 * 关键约束（项目贯穿原则）：
 *   - 只读音频状态，不反向控制音频；UI 全在主循环，绝不进中断。
 *   - 歌词时间轴 = 真实 PCM 已播时长（audio_stream_position_ms()），
 *     与歌声同一基准；等静音不算时间。
 *   - 只在「当前行变化 / 秒数变化 / 进度像素变化」时重画，避免刷屏抢总线。
 *   - 中文走内置 GBK 16x16 点阵（cn_font.h），ASCII 走驱动自带 asc2_1608，
 *     两者都按整数倍放大绘制，不额外占 Flash。
 *   - 歌词数据在 lrc_data.h（Tools/lrc_playlist.py 生成），
 *     一条记录里 '\x01' 分隔「原文」与「译文」，渲染成两行。
 *   - 曲目切换由上位机 CDC 控制线告知（波特率编码），不靠猜。
 * ============================================================ */
#include "lcd_ui.h"
#include "lcd.h"
#include "cn_font.h"
#include "cn_font40.h"        /* 40px 原生大字模（歌词用，Tools/gen_big_font.py 生成） */
#include "lrc_data.h"         /* s_lrcN / s_titleN / s_artistN / s_durN（自动生成） */
#include "cover_img.h"        /* s_coverN / s_bgN（Tools/gen_cover.py 生成） */
#include "i2s_audio.h"        /* audio_stream_reset_position() */
#include <string.h>
#include <stdlib.h>

/* lcdfont.h 里的是「定义」不是声明，本文件只做 extern 声明（避免重复定义）。
 * 需要 lcd.h 的 LCD_KEEP_ASCII_FONT=1，否则 lcd.c 不编进 asc2_1608。 */
extern const unsigned char asc2_1608[95][16];

/* ---------------- 版式常量 ---------------- */
#define UI_W                 800u
#define UI_H                 480u
#define TOP_H                240u      /* 上半屏高度 */

#define COVER_X              8u
#define COVER_Y              16u
#define IMG_W                256u     /* 左栏宽度 = 屏宽 1/3：图片 + 歌曲信息 */
#define PANEL_X              8u       /* 左栏文字左边界 */
#define PANEL_R              248u     /* 左栏文字右边界（含） */
#define TITLE_Y              262u
#define TITLE_H              32u
#define ARTIST_Y             310u
#define BAR_X                8u
#define BAR_Y                336u
#define BAR_W                236u     /* 8..243，与左栏同宽 */
#define BAR_H                6u
#define TIME_Y               350u
#define VOL_Y                374u     /* "VOL nn" / "PAUSE" */

/* ---- 触屏控制按钮（左栏下方空出来的 90px）---- */
#define BTN_Y                396u
#define BTN_H                76u
#define BTN_W                76u
#define BTN_X0               4u       /* 上一首 4..79 */
#define BTN_X1               88u      /* 播放/暂停 88..163 */
#define BTN_X2               172u     /* 下一首 172..247 */
#define BTN_COL              0x2104u  /* 按钮底：深灰 */
#define BTN_COL_ON           0x39E7u  /* 按下态 */

#define LYR_X                276u     /* 歌词区左边界（右侧 2/3） */
#define LYR_MARK_X           262u     /* 高亮指示条 */
#define LYR_Y0               6u       /* 歌词区上边界 */
#define LYR_Y1               474u     /* 歌词区下边界（含） */
#define LYR_LIMIT            796u

#define TICK_MS              100u      /* 10fps 上限，实际只在变化时重画 */
#define ANIM_MS              110u      /* 当前句变色刷新间隔（≈9fps） */

/* 每块歌词：原文(scale2=32px) + 译文(scale1=16px) */
#define BLK_STEP_BI          72u       /* 双语块步距：3 块 = 216 ≤ 224 */
#define BLK_STEP_MONO        44u       /* 单语块步距：5 块 = 220 ≤ 224 */

#define LRC_MAX_LINES        96u
#define TEXT_MAX             96u       /* 与 Tools/lrc_playlist.py 的 MAX_TEXT+1 一致 */
#define SONG_COUNT           6u        /* 与 Tools/lrc_playlist.py 的 MAX_SONGS 一致 */

/* 上电默认显示哪一首（0 起）。5 = 第 6 首「忘不掉的你」——
 * 开机先看到最新这首的歌词；上位机发来 plNN.wav 仍会按
 * SET_LINE_CODING 自动切到对应曲目。 */
#define UI_DEFAULT_SONG      5u

#define LRC_SEP              '\x01'    /* 原文 / 译文 分隔符 */
#define LRC_BR               '\x02'    /* 长句折行符：太长的行在第 2 行接着画 */

/* ---------------- 配色 ---------------- */
#define UI_COL_BG            0x0000u
#define UI_COL_SPLIT         0x2104u   /* 上下分区分隔线 */
#define UI_COL_EDGE          0x2104u   /* 封面右侧竖线 */
#define UI_COL_TITLE         0xFFFFu   /* 歌名：白 */
#define UI_COL_ARTIST        0xBDF7u   /* 歌手：浅灰 */
#define UI_COL_TRACK         0x39E7u   /* 进度条底槽（稍亮，能看出槽） */
#define UI_COL_FILL          0xFFFFu   /* 进度条已播 */
#define UI_COL_TIME          0xE71Cu   /* 当前时间 */
#define UI_COL_TIME_TOTAL    0x8C71u   /* 总时长 */
#define UI_COL_ACTIVE        0xFFE0u   /* 当前歌词（原文）：黄 */
#define UI_COL_ACT_TRANS     0xFDA0u   /* 当前歌词（译文）：暖橙 */
#define UI_COL_NORMAL        0xDEDBu   /* 其他歌词：更亮的灰，避免发灰看不清 */
#define UI_COL_DIM           0x7BEFu   /* 其他歌词（译文）：中灰 */

typedef struct {
    uint32_t t_ms;
    uint8_t  bi;            /* 1 = 本条含译文 */
    char     text[TEXT_MAX];/* GBK 字节串，原文 + '\x01' + 译文 */
} ui_line_t;

/* 只保留「当前曲目」一份解析结果：换曲时重解析，省 RAM（5 首全解要 48KB）。 */
static ui_line_t  s_lines[LRC_MAX_LINES];
static int        s_cur_n;

/* 播放列表：歌词 / 歌名 / 歌手 / 时长 / 封面 / 底图（来自自动生成的头文件） */
static const char *const s_lrcs[SONG_COUNT]    = { s_lrc1, s_lrc2, s_lrc3, s_lrc4, s_lrc5, s_lrc6 };
static const char *const s_titles[SONG_COUNT]  = { s_title1, s_title2, s_title3, s_title4, s_title5, s_title6 };
static const char *const s_artists[SONG_COUNT] = { s_artist1, s_artist2, s_artist3, s_artist4, s_artist5, s_artist6 };
static const uint32_t    s_durs[SONG_COUNT]    = { s_dur1, s_dur2, s_dur3, s_dur4, s_dur5, s_dur6 };
/* 没有单独封面的曲目统一用 s_coverD / s_bgD（Tools/add_default_cover.py 生成），
 * 只有第 5 首有自己那张照片。 */
static const uint16_t *const s_covers[SONG_COUNT] = { s_coverD, s_coverD, s_coverD, s_coverD, s_cover5, s_coverD };
static const uint16_t *const s_bgs[SONG_COUNT]    = { s_bgD, s_bgD, s_bgD, s_bgD, s_bg5, s_bgD };

static int        s_song = 0;
static int        s_active = -1;
static int        s_last_active = -2;
static uint32_t   s_last_tick = 0;
static uint32_t   s_last_sec = 0xFFFFFFFFu;
static uint16_t   s_bar_fill = 0;
static char       s_track[48] = "";      /* 覆盖歌名（上位机下发），空=用列表歌名 */
static char       s_artist_ovr[48] = "";  /* 覆盖歌手，空=用列表歌手 */
static uint8_t    s_ready = 0;

/* ---- 当前句的矩形 + 动态颜色（只重画这一块） ---- */
static uint16_t   s_act_y = 0;
static uint16_t   s_act_h = 0;
static uint16_t   s_col_orig = UI_COL_ACTIVE;
static uint16_t   s_col_trans = UI_COL_ACT_TRANS;
static uint32_t   s_anim_tick = 0;
static uint32_t   s_last_pos = 0xFFFFFFFFu;
static uint32_t   s_dur_override = 0;    /* 外部音源给的时长（0 = 用内置表） */
static uint8_t    s_volume = 38u;   /* 与 i2s_audio.c 默认一致，量程 0~100 */
static uint8_t    s_paused = 0;           /* 已通知电脑暂停 */

/* 选曲信号：USB 中断里置位，主循环消费（中断里绝不画屏/换算） */
static volatile uint8_t s_req_song = 0;
static volatile uint8_t s_song_pending = 0;

/* 背景板 1 行（2x 放大后 800 像素），避免每次开大数组 */
static uint16_t s_rowbuf[UI_W];

/* ------------------------------------------------------------
 * 小工具：颜色
 * ------------------------------------------------------------ */
/* h 0..255 绕一圈的彩虹（满亮度），转 RGB565 */
static uint16_t hsv565(uint8_t h)
{
    uint8_t region = (uint8_t)(h / 43u);
    uint8_t rem    = (uint8_t)((h - region * 43u) * 6u);
    uint8_t q      = (uint8_t)(255u - rem);
    uint8_t r, g, b;

    switch (region) {
        case 0:  r = 255u; g = rem;  b = 0;    break;
        case 1:  r = q;    g = 255u; b = 0;    break;
        case 2:  r = 0;    g = 255u; b = rem;  break;
        case 3:  r = 0;    g = q;    b = 255u; break;
        case 4:  r = rem;  g = 0;    b = 255u; break;
        default: r = 255u; g = 0;    b = q;    break;
    }
    return (uint16_t)(((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3));
}

/* 同色相压暗（译文用），k = 0..255 */
static uint16_t dim565(uint16_t c, uint8_t k)
{
    uint16_t r = (uint16_t)(((c >> 11) & 0x1Fu) * k / 255u);
    uint16_t g = (uint16_t)(((c >> 5) & 0x3Fu) * k / 255u);
    uint16_t b = (uint16_t)((c & 0x1Fu) * k / 255u);
    return (uint16_t)((r << 11) | (g << 5) | b);
}

/* ------------------------------------------------------------
 * 底层：字形
 * ------------------------------------------------------------ */
/* 查 GBK 字形：整张表按 GBK 码升序排列（生成脚本保证），用二分。
 * 全 GB2312 是 7478 字，线性扫一遍每次换行要几十万次比较，二分只要 13 次。 */
static const uint8_t *cn_bits(uint16_t gbk)
{
    uint16_t lo = 0, hi = CN_FONT_COUNT;

    while (lo < hi) {
        uint16_t mid = (uint16_t)((lo + hi) / 2u);
        if (g_cn_font[mid].gbk == gbk) return g_cn_font[mid].bits;
        if (g_cn_font[mid].gbk < gbk) lo = (uint16_t)(mid + 1u);
        else                          hi = mid;
    }
    return 0;
}

/* 16x16 汉字点阵，按 scale 放大：行优先（每行 2 字节，MSB=最左），
 * 同一行连续亮点合并成一次 lcd_fill。 */
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

/* 8x16 ASCII 点阵，按 scale 放大。asc2_1608 是「逐列式」：每列 2 字节
 * （第 1 字节 = 该列上 8 行，第 2 字节 = 下 8 行，MSB 在上）。 */
static void draw_ascii_ch(uint16_t x, uint16_t y, char ch, uint16_t color, uint8_t scale)
{
    const uint8_t *p;
    uint16_t bits;
    uint8_t col, row, r0;

    if ((uint8_t)ch < 0x20u || (uint8_t)ch > 0x7Eu) ch = ' ';
    p = (const uint8_t *)asc2_1608[(uint8_t)ch - 0x20u];

    for (col = 0; col < 8u; col++) {
        bits = ((uint16_t)p[col * 2u] << 8) | p[col * 2u + 1u];
        if (bits == 0u) continue;
        row = 0;
        while (row < 16u) {
            if (bits & (0x8000u >> row)) {
                r0 = row;
                while (row < 16u && (bits & (0x8000u >> row))) row++;
                lcd_fill((uint16_t)(x + col * scale),
                         (uint16_t)(y + r0 * scale),
                         (uint16_t)(x + col * scale + scale - 1u),
                         (uint16_t)(y + row * scale - 1u),
                         color);
            } else {
                row++;
            }
        }
    }
}

/* 画 GBK/ASCII 混排字符串（遇到 '\x01' 停）。x_limit 为右边界（含）。 */
static uint16_t draw_text(uint16_t x, uint16_t y, const char *s,
                          uint16_t color, uint8_t scale, uint16_t x_limit)
{
    uint16_t px = x;
    const uint8_t *p = (const uint8_t *)s;
    const uint8_t *bits;

    if (!s) return 0;
    while (*p) {
        if (*p == (uint8_t)LRC_SEP) break;
        if (*p < 0x80u) {
            if ((uint16_t)(px + 8u * scale) > x_limit) break;
            draw_ascii_ch(px, y, (char)*p, color, scale);
            px = (uint16_t)(px + 8u * scale);
            p++;
        } else {
            if (*(p + 1) == 0) break;
            if ((uint16_t)(px + 16u * scale) > x_limit) break;
            bits = cn_bits((uint16_t)(((uint16_t)(*p) << 8) | *(p + 1)));
            if (bits) draw_glyph(px, y, bits, color, scale);
            px = (uint16_t)(px + 16u * scale);
            p += 2;
        }
    }
    return (uint16_t)(px - x);
}

/* 字符串在给定放大倍数下的像素宽度（不计裁剪），用于选倍数/居中 */
static uint16_t text_width(const char *s, uint8_t scale)
{
    uint16_t w = 0;
    const uint8_t *p = (const uint8_t *)s;

    if (!s) return 0;
    while (*p) {
        if (*p == (uint8_t)LRC_SEP) break;
        if (*p < 0x80u) { w = (uint16_t)(w + 8u * scale); p++; }
        else            { w = (uint16_t)(w + 16u * scale); p += (*p && *(p + 1)) ? 2 : 1; }
    }
    return w;
}

/* ------------------------------------------------------------
 * 40px 原生点阵（cn_font40.h）：歌词主字号，1:1 画，不做块状放大
 * ------------------------------------------------------------ */
static const uint8_t *cn40_bits(uint16_t gbk)
{
    uint16_t lo = 0, hi = CN40_COUNT;

    while (lo < hi) {
        uint16_t mid = (uint16_t)((lo + hi) / 2u);
        if (g_cn40[mid].gbk == gbk) return g_cn40[mid].bits;
        if (g_cn40[mid].gbk < gbk) lo = (uint16_t)(mid + 1u);
        else                       hi = mid;
    }
    return 0;
}

/* 40x40，每行 5 字节，MSB 在最左；横向连续亮点合并成一次 lcd_fill */
static void draw_glyph40(uint16_t x, uint16_t y, const uint8_t *bits, uint16_t color)
{
    uint16_t row, col, run;
    uint64_t line;

    for (row = 0; row < CN40_H; row++) {
        const uint8_t *p = bits + (uint16_t)row * 5u;
        line = ((uint64_t)p[0] << 32) | ((uint64_t)p[1] << 24) |
               ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 8) | p[4];
        if (line == 0u) continue;
        col = 0;
        while (col < 40u) {
            if (line & (0x8000000000ULL >> col)) {
                run = col;
                while (col < 40u && (line & (0x8000000000ULL >> col))) col++;
                lcd_fill((uint16_t)(x + run), (uint16_t)(y + row),
                         (uint16_t)(x + col - 1u), (uint16_t)(y + row), color);
            } else {
                col++;
            }
        }
    }
}

/* ASCII 20x40，每行 ASC40_STRIDE(3) 字节；MSB 在最左 */
static void draw_ascii40(uint16_t x, uint16_t y, char ch, uint16_t color)
{
    const uint8_t *p;
    uint16_t row, col, run;
    uint32_t bits;

    if ((uint8_t)ch < 0x20u || (uint8_t)ch > 0x7Eu) ch = ' ';
    p = g_asc40[(uint8_t)ch - 0x20u];

    for (row = 0; row < ASC40_H; row++) {
        const uint8_t *q = p + (uint16_t)row * ASC40_STRIDE;
        bits = ((uint32_t)q[0] << 16) | ((uint32_t)q[1] << 8) | q[2];
        if (bits == 0u) continue;
        col = 0;
        while (col < ASC40_W) {
            if (bits & (0x800000uL >> col)) {
                run = col;
                while (col < ASC40_W && (bits & (0x800000uL >> col))) col++;
                lcd_fill((uint16_t)(x + run), (uint16_t)(y + row),
                         (uint16_t)(x + col - 1u), (uint16_t)(y + row), color);
            } else {
                col++;
            }
        }
    }
}

/* 整行是否都能用 40px 字模画出来（缺字就整行降字号，避免一行两种高度） */
static uint8_t text40_ok(const char *s)
{
    const uint8_t *p = (const uint8_t *)s;

    if (!s) return 0;
    while (*p) {
        if (*p == (uint8_t)LRC_SEP) break;
        if (*p < 0x80u) { p++; continue; }
        if (*(p + 1) == 0) return 0;
        if (!cn40_bits((uint16_t)(((uint16_t)(*p) << 8) | *(p + 1)))) return 0;
        p += 2;
    }
    return 1;
}

static uint16_t text40_width(const char *s)
{
    uint16_t w = 0;
    const uint8_t *p = (const uint8_t *)s;

    if (!s) return 0;
    while (*p) {
        if (*p == (uint8_t)LRC_SEP || *p == (uint8_t)LRC_BR) break;
        if (*p < 0x80u) { w = (uint16_t)(w + ASC40_W); p++; }
        else            { w = (uint16_t)(w + CN40_W); p += 2; }
    }
    return w;
}

/* 太长的单语行就地插入折行符，改成两行 40px 显示。
 * 为什么要折：40px 汉字 40 宽、ASCII 16 宽，歌词区可用 530px，
 * 英文长句（35~52 字符）放不下就只能退回 16px 放大 → 用户说的「马赛克」。
 * 折成两行后仍是原生 40px，清晰且不丢字。 */
/* 某段 GBK 串按 40px 字号算宽度 */
static uint16_t seg_width40(const char *s, int len)
{
    uint16_t w = 0;
    int i = 0;

    while (i < len && s[i]) {
        if ((uint8_t)s[i] < 0x80u) { w = (uint16_t)(w + ASC40_W); i++; }
        else                       { w = (uint16_t)(w + CN40_W);  i += 2; }
    }
    return w;
}

static void wrap_40(char *t)
{
    const uint16_t avail = (uint16_t)(LYR_LIMIT - LYR_X);
    uint16_t w = 0;
    int i = 0, sp = -1, best = -1, k, len;
    size_t nb_len;

    if (!t || !t[0]) return;
    if (strchr(t, LRC_BR) || strchr(t, LRC_SEP)) return;   /* 已折过 / 双语块不动 */

    while (t[i]) {
        uint8_t c = (uint8_t)t[i];
        uint16_t cw;
        int step;

        if (c < 0x80u) { cw = ASC40_W; step = 1; }
        else           { if (!t[i + 1]) break; cw = CN40_W; step = 2; }

        if ((uint32_t)w + cw > avail) break;
        if (c == ' ') sp = i;
        w = (uint16_t)(w + cw);
        i += step;
    }
    if (!t[i]) return;                       /* 一行放得下，不用折 */

    /* 在「前半段放得下 且 后半段也放得下」的空格里挑最后一个，
     * 这样折完两行都不会被 x_limit 截掉字（只按第一个空格折会切尾）。 */
    len = (int)strlen(t);
    for (k = 1; k < len; k++) {
        if (t[k] != ' ') continue;
        if (seg_width40(t, k) > avail) break;
        if (seg_width40(t + k + 1, len - k - 1) > avail) continue;
        best = k;
    }

    if (best > 0) {
        t[best] = LRC_BR;
    } else if (sp > 0) {
        t[sp] = LRC_BR;                      /* 没有两全的断点，退回最后一个空格 */
    } else {
        nb_len = strlen(t);
        if (nb_len + 2u >= TEXT_MAX) nb_len = TEXT_MAX - 3u;
        memmove(t + i + 1, t + i, nb_len - (size_t)i + 1u);
        t[i] = LRC_BR;                       /* 没空格（长中文句）就硬切 */
    }
}

static void draw_text40(uint16_t x, uint16_t y, const char *s, uint16_t color, uint16_t x_limit)
{
    uint16_t px = x;
    const uint8_t *p = (const uint8_t *)s;
    const uint8_t *bits;

    if (!s) return;
    while (*p) {
        if (*p == (uint8_t)LRC_SEP || *p == (uint8_t)LRC_BR) break;
        if (*p < 0x80u) {
            if ((uint16_t)(px + ASC40_W) > x_limit) break;
            draw_ascii40(px, y, (char)*p, color);
            px = (uint16_t)(px + ASC40_W);
            p++;
        } else {
            if (*(p + 1) == 0) break;
            if ((uint16_t)(px + CN40_W) > x_limit) break;
            bits = cn40_bits((uint16_t)(((uint16_t)(*p) << 8) | *(p + 1)));
            if (bits) draw_glyph40(px, y, bits, color);
            px = (uint16_t)(px + CN40_W);
            p += 2;
        }
    }
}

/* ------------------------------------------------------------
 * 底层：图像搬运
 * ------------------------------------------------------------ */
static void blit_row(uint16_t x, uint16_t y, const uint16_t *src, uint16_t w)
{
    uint16_t i;
    lcd_set_cursor(x, y);
    lcd_write_ram_prepare();
    for (i = 0; i < w; i++) LCD->LCD_RAM = src[i];
}

/* 无封面时的兜底底色：竖向深蓝灰渐变（按行算色，t=0 顶 / 1 底） */
static uint16_t grad_color(uint16_t y)
{
    uint32_t t = (y >= TOP_H) ? (TOP_H - 1u) : y;
    uint16_t r = (uint16_t)(3u - (2u * t) / (TOP_H - 1u));
    uint16_t g = (uint16_t)(9u - (7u * t) / (TOP_H - 1u));
    uint16_t b = (uint16_t)(6u - (5u * t) / (TOP_H - 1u));
    return (uint16_t)((r << 11) | (g << 5) | b);
}

/* RGB565 逐通道取平均 */
static uint16_t mix565(uint16_t a, uint16_t b)
{
    uint16_t r = (uint16_t)(((a >> 11) + (b >> 11)) >> 1);
    uint16_t g = (uint16_t)((((a >> 5) & 0x3Fu) + ((b >> 5) & 0x3Fu)) >> 1);
    uint16_t bl = (uint16_t)(((a & 0x1Fu) + (b & 0x1Fu)) >> 1);
    return (uint16_t)((r << 11) | (g << 5) | bl);
}

/* 屏幕坐标 (x,y) 处的背景色：底图 400x120 -> 800x240 的双线性放大。
 * 全屏铺底与局部还原都走这一个函数，保证「擦掉再画」像素完全对齐。 */
static uint16_t bg_px(uint16_t x, uint16_t y)
{
    const uint16_t *bg = s_bgs[s_song];
    uint16_t sx, sy, x1, y1, v;

    if (y >= TOP_H) y = (uint16_t)(y - TOP_H);   /* 左栏比背景板高，竖向平铺 */
    if (!bg) return grad_color(y);
    sx = (uint16_t)(x >> 1);
    sy = (uint16_t)(y >> 1);
    x1 = (sx + 1u < COVER_BG_W) ? (uint16_t)(sx + 1u) : sx;
    y1 = (sy + 1u < COVER_BG_H) ? (uint16_t)(sy + 1u) : sy;

    v = bg[(uint32_t)sy * COVER_BG_W + sx];
    if (x & 1u) v = mix565(v, bg[(uint32_t)sy * COVER_BG_W + x1]);
    if (y & 1u) v = mix565(v, bg[(uint32_t)y1 * COVER_BG_W + sx]);

    /* 不再压暗/盖黑底：封面完整亮出来。信息文字靠 1px 深色描边（draw_text_halo）
     * 保证在白底/亮底封面上也能看清。 */
    return v;
}

/* 把左栏某一块恢复成「背景」 */
static void restore_rect(uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
    uint16_t i, j;

    /* 裁剪必须用整屏高度 UI_H，不是背景板高度 TOP_H！
     * 曾经写 TOP_H(240) 而文字区在 y=350 → 240-350 无符号下溢成 65xxx，
     * 刷 6 万多行 → 开机卡死、USB 不枚举。 */
    if (y >= UI_H) return;
    if ((uint32_t)y + h > UI_H) h = (uint16_t)(UI_H - y);
    if (x >= UI_W) return;
    if ((uint32_t)x + w > UI_W) w = (uint16_t)(UI_W - x);

    for (j = 0; j < h; j++) {
        for (i = 0; i < w; i++) {
            s_rowbuf[i] = bg_px((uint16_t)(x + i), (uint16_t)(y + j));
        }
        blit_row(x, (uint16_t)(y + j), s_rowbuf, w);
    }
}

/* 铺满上半屏背景（封面之后画的部分都压在它上面） */
static void draw_top_bg(void)
{
    uint16_t x, y;

    for (y = 0; y < UI_H; y++) {
        for (x = 0; x < IMG_W; x++) s_rowbuf[x] = bg_px(x, y);
        blit_row(0, y, s_rowbuf, IMG_W);
    }
}

/* 画封面（1:1），右侧加一条竖线跟文字区隔开 */
static void draw_cover(void)
{
    const uint16_t *cov = s_covers[s_song];
    uint16_t y;

    if (!cov) {
        /* 无封面：240x240 里画居中的大号曲目序号（占位封面），
         * 不重复画歌名——歌名在上方文字区已经有了。 */
        char num[3];
        uint16_t w, sc;
        if (s_song < 9) {
            num[0] = (char)('1' + s_song);
            num[1] = '\0';
            sc = 5u;
        } else {
            num[0] = (char)('0' + (s_song + 1) / 10);
            num[1] = (char)('0' + (s_song + 1) % 10);
            num[2] = '\0';
            sc = 3u;
        }
        w = text_width(num, (uint8_t)sc);
        draw_text((uint16_t)(COVER_X + (COVER_W - w) / 2u),
                  (uint16_t)(COVER_Y + (COVER_H - 16u * sc) / 2u),
                  num, UI_COL_DIM, (uint8_t)sc, (uint16_t)(COVER_X + COVER_W));
        return;
    }
    for (y = 0; y < COVER_H; y++) {
        blit_row(COVER_X, (uint16_t)(COVER_Y + y),
                 cov + (uint32_t)y * COVER_W, COVER_W);
    }
}

/* ------------------------------------------------------------
 * 上半屏：歌名 / 歌手 / 进度条 / 时间
 * ------------------------------------------------------------ */
static void fmt_time(char *b, uint32_t ms)
{
    uint32_t ss = ms / 1000u;
    uint32_t m = ss / 60u;
    uint32_t s = ss % 60u;

    b[0] = (char)('0' + (m / 10u) % 10u);
    b[1] = (char)('0' + m % 10u);
    b[2] = ':';
    b[3] = (char)('0' + s / 10u);
    b[4] = (char)('0' + s % 10u);
    b[5] = '\0';
}

static const char *cur_title(void)
{
    return s_track[0] ? s_track : s_titles[s_song];
}

static const char *cur_artist(void)
{
    return s_artist_ovr[0] ? s_artist_ovr : s_artists[s_song];
}

/* 局部磨砂底：只把「文字那一小块」的背景压暗，保留封面纹理，
 * 不铺整块黑底、也不把封面盖掉。比纯黑条柔和，白字也压得住。
 * 亮度系数 110/255 ≈ 43%，白底漫画 / 深色照片两种封面都适用。 */
static void shade_rect(uint16_t x, uint16_t y, uint16_t w, uint16_t h)
{
    uint16_t i, j;

    if (x >= UI_W || y >= UI_H) return;
    if ((uint32_t)x + w > UI_W) w = (uint16_t)(UI_W - x);
    if ((uint32_t)y + h > UI_H) h = (uint16_t)(UI_H - y);
    for (j = 0; j < h; j++) {
        for (i = 0; i < w; i++) {
            s_rowbuf[i] = dim565(bg_px((uint16_t)(x + i), (uint16_t)(y + j)), 110u);
        }
        blit_row(x, (uint16_t)(y + j), s_rowbuf, w);
    }
}

/* 1px 深色描边 + 局部磨砂底：不铺大块黑底，浅色字压在亮色封面上也能看清。
 * 只在换曲/改音量时画，不在 10fps 循环里跑，5 倍绘制量可以接受。 */
static void draw_text_halo(uint16_t x, uint16_t y, const char *s,
                           uint16_t col, uint8_t sc, uint16_t limit)
{
    static const int8_t off[4][2] = { {-1, 0}, {1, 0}, {0, -1}, {0, 1} };
    uint8_t k;
    uint16_t tw = text_width(s, sc);

    shade_rect(x, y, (uint16_t)(tw + 6u), (uint16_t)(16u * sc + 3u));
    for (k = 0; k < 4u; k++) {
        int16_t xx = (int16_t)x + off[k][0];
        int16_t yy = (int16_t)y + off[k][1];
        if (xx < 0 || yy < 0) continue;
        draw_text((uint16_t)xx, (uint16_t)yy, s, UI_COL_BG, sc, limit);
    }
    draw_text(x, y, s, col, sc, limit);
}

static void draw_text40_halo(uint16_t x, uint16_t y, const char *s,
                             uint16_t col, uint16_t limit)
{
    static const int8_t off[4][2] = { {-1, 0}, {1, 0}, {0, -1}, {0, 1} };
    uint8_t k;

    shade_rect(x, y, (uint16_t)(text40_width(s) + 6u), 44u);
    for (k = 0; k < 4u; k++) {
        int16_t xx = (int16_t)x + off[k][0];
        int16_t yy = (int16_t)y + off[k][1];
        if (xx < 0 || yy < 0) continue;
        draw_text40((uint16_t)xx, (uint16_t)yy, s, UI_COL_BG, limit);
    }
    draw_text40(x, y, s, col, limit);
}

/* 音量小字："VOL nnn"（0~100 三位数） */
static void draw_volume(void)
{
    char b[10];
    uint8_t v = s_volume;

    b[0] = 'V'; b[1] = 'O'; b[2] = 'L'; b[3] = ' ';
    if (v >= 100u) {
        b[4] = '1'; b[5] = '0'; b[6] = '0'; b[7] = '\0';
    } else {
        b[4] = (char)('0' + v / 10u);
        b[5] = (char)('0' + v % 10u);
        b[6] = '\0';
    }

    restore_rect(PANEL_X, VOL_Y, 96u, 16u);
    draw_text_halo(PANEL_X, VOL_Y, b, UI_COL_TIME_TOTAL, 1u, PANEL_R);
}

/* 实心三角形：dir=1 右指，0 左指；w 底边宽，h 高 */
static void draw_tri(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint8_t dir, uint16_t col)
{
    uint16_t i, half = (uint16_t)(h / 2u), seg;

    for (i = 0; i < h; i++) {
        uint16_t k = (i < half) ? (uint16_t)(i + 1u) : (uint16_t)(h - i);
        seg = (uint16_t)((uint32_t)w * k / (half ? half : 1u));
        if (seg == 0u) continue;
        if (dir) {
            lcd_fill(x, (uint16_t)(y + i), (uint16_t)(x + seg - 1u), (uint16_t)(y + i), col);
        } else {
            lcd_fill((uint16_t)(x + w - seg), (uint16_t)(y + i),
                     (uint16_t)(x + w - 1u), (uint16_t)(y + i), col);
        }
    }
}

static void draw_btn_bg(uint16_t x, uint16_t col)
{
    lcd_fill(x, BTN_Y, (uint16_t)(x + BTN_W - 1u), (uint16_t)(BTN_Y + BTN_H - 1u), col);
}

/* 只画中间那个按钮（播放/暂停），状态变化时用，避免整屏重画 */
static void draw_btn_play(void)
{
    uint16_t x = BTN_X1;

    draw_btn_bg(x, BTN_COL);
    if (s_paused) {                       /* 暂停中 → 显示 ▶（点了就播） */
        draw_tri((uint16_t)(x + 26u), (uint16_t)(BTN_Y + 20u), 26u, 36u, 1u, UI_COL_TITLE);
    } else {                              /* 播放中 → 显示 ⏸ */
        lcd_fill((uint16_t)(x + 24u), (uint16_t)(BTN_Y + 20u),
                 (uint16_t)(x + 32u), (uint16_t)(BTN_Y + 55u), UI_COL_TITLE);
        lcd_fill((uint16_t)(x + 42u), (uint16_t)(BTN_Y + 20u),
                 (uint16_t)(x + 50u), (uint16_t)(BTN_Y + 55u), UI_COL_TITLE);
    }
}

/* 三个触屏按钮：上一首 / 播放暂停 / 下一首 */
static void draw_controls(void)
{
    uint16_t x = BTN_X0;

    draw_btn_bg(BTN_X0, BTN_COL);
    draw_btn_bg(BTN_X1, BTN_COL);
    draw_btn_bg(BTN_X2, BTN_COL);

    /* ⏮ 上一首 */
    lcd_fill((uint16_t)(x + 18u), (uint16_t)(BTN_Y + 20u),
             (uint16_t)(x + 21u), (uint16_t)(BTN_Y + 55u), UI_COL_TITLE);
    draw_tri((uint16_t)(x + 24u), (uint16_t)(BTN_Y + 20u), 26u, 36u, 0u, UI_COL_TITLE);

    draw_btn_play();

    /* ⏭ 下一首 */
    x = BTN_X2;
    draw_tri((uint16_t)(x + 22u), (uint16_t)(BTN_Y + 20u), 26u, 36u, 1u, UI_COL_TITLE);
    lcd_fill((uint16_t)(x + 50u), (uint16_t)(BTN_Y + 20u),
             (uint16_t)(x + 53u), (uint16_t)(BTN_Y + 55u), UI_COL_TITLE);
}

/* 触摸命中判定：0=没点到按钮，1=上一首，2=播放/暂停，3=下一首 */
uint8_t lcd_ui_hit(uint16_t x, uint16_t y)
{
    /* 热区放宽到「左栏下半段」：电阻屏校准难免有偏差，卡死在 76×76 的
     * 按钮小方框里很容易点不中。左栏按 x 三等分对应 上一首/播放暂停/下一首，
     * y 从 380 开始（按钮顶 396，再往上留 16px 容差）。右栏是歌词，不响应。 */
    if (y < 380u || y >= UI_H) return 0;
    if (x >= IMG_W) return 0;
    if (x < 85u)  return 1;
    if (x < 171u) return 2;
    return 3;
}

/* 按压反馈：点到的按钮亮一下 */
void lcd_ui_btn_flash(uint8_t hit)
{
    uint16_t x;

    if (!s_ready) return;
    if (hit == 1) x = BTN_X0;
    else if (hit == 2) x = BTN_X1;
    else if (hit == 3) x = BTN_X2;
    else return;

    draw_btn_bg(x, BTN_COL_ON);
    HAL_Delay(60);
    if (hit == 2) {
        draw_btn_play();
    } else {
        draw_btn_bg(x, BTN_COL);
        if (hit == 1) {
            lcd_fill((uint16_t)(BTN_X0 + 18u), (uint16_t)(BTN_Y + 20u),
                     (uint16_t)(BTN_X0 + 21u), (uint16_t)(BTN_Y + 55u), UI_COL_TITLE);
            draw_tri((uint16_t)(BTN_X0 + 24u), (uint16_t)(BTN_Y + 20u), 26u, 36u, 0u, UI_COL_TITLE);
        } else {
            draw_tri((uint16_t)(BTN_X2 + 22u), (uint16_t)(BTN_Y + 20u), 26u, 36u, 1u, UI_COL_TITLE);
            lcd_fill((uint16_t)(BTN_X2 + 50u), (uint16_t)(BTN_Y + 20u),
                     (uint16_t)(BTN_X2 + 53u), (uint16_t)(BTN_Y + 55u), UI_COL_TITLE);
        }
    }
}

static void draw_panel(void)
{
    const char *title = cur_title();
    const char *artist = cur_artist();
    uint16_t w;
    uint8_t sc = 2u;

    /* 歌名优先用 40px 原生字模：中文歌名（≤6 字）都放得下，比放大清晰得多；
     * 放不下才退 32px（2x）→ 16px。 */
    if (text40_ok(title) && text40_width(title) <= PANEL_R - PANEL_X) {
        draw_text40_halo(PANEL_X, TITLE_Y, title, UI_COL_TITLE, PANEL_R);
    } else {
        w = text_width(title, sc);
        if (w > PANEL_R - PANEL_X) {
            sc = 1u;
            w = text_width(title, sc);
        }
        draw_text_halo(PANEL_X, TITLE_Y, title, UI_COL_TITLE, sc, PANEL_R);
    }
    (void)w;

    if (artist && artist[0]) {
        draw_text_halo(PANEL_X, ARTIST_Y, artist, UI_COL_ARTIST, 1u, PANEL_R);
    }

    /* 进度条底槽（已播部分由 draw_progress 覆盖） */
    lcd_fill(BAR_X, BAR_Y, (uint16_t)(BAR_X + BAR_W - 1u), (uint16_t)(BAR_Y + BAR_H - 1u),
             UI_COL_TRACK);
    s_bar_fill = 0;
    s_last_sec = 0xFFFFFFFFu;      /* 强制下一拍重画时间 */
    draw_volume();
}

/* 进度条 + 时间：只在像素/秒变化时真的写屏 */
static void draw_progress(uint32_t pos_ms)
{
    uint32_t dur = s_dur_override ? s_dur_override : s_durs[s_song];
    uint16_t want;
    char buf[8];

    if (dur == 0u) return;
    if (pos_ms > dur) pos_ms = dur;
    want = (uint16_t)(((uint64_t)BAR_W * pos_ms) / dur);

    if (want > s_bar_fill) {
        lcd_fill((uint16_t)(BAR_X + s_bar_fill), BAR_Y,
                 (uint16_t)(BAR_X + want - 1u), (uint16_t)(BAR_Y + BAR_H - 1u),
                 UI_COL_FILL);
        s_bar_fill = want;
    } else if (want < s_bar_fill) {
        lcd_fill((uint16_t)(BAR_X + want), BAR_Y,
                 (uint16_t)(BAR_X + s_bar_fill - 1u), (uint16_t)(BAR_Y + BAR_H - 1u),
                 UI_COL_TRACK);
        s_bar_fill = want;
    }

    if (pos_ms / 1000u != s_last_sec) {
        s_last_sec = pos_ms / 1000u;
        fmt_time(buf, pos_ms);
        restore_rect(PANEL_X, TIME_Y, 40u, 16u);
        draw_text_halo(PANEL_X, TIME_Y, buf, UI_COL_TIME, 1u, PANEL_R);

        fmt_time(buf, dur);
        restore_rect((uint16_t)(PANEL_R - 39u), TIME_Y, 40u, 16u);
        draw_text_halo((uint16_t)(PANEL_R - 39u), TIME_Y, buf, UI_COL_TIME_TOTAL, 1u,
                       (uint16_t)(PANEL_R + 1u));
    }
}

static void draw_top(void)
{
    lcd_fill(IMG_W, 0, UI_W - 1u, UI_H - 1u, UI_COL_BG);   /* 右侧歌词区底 */
    draw_top_bg();                                          /* 左栏：图片/模糊底 */
    draw_cover();
    /* 左栏与歌词区之间的 2px 竖线 */
    lcd_fill(IMG_W, 0, (uint16_t)(IMG_W + 1u), UI_H - 1u, UI_COL_EDGE);
    draw_panel();
    draw_controls();                                        /* 触屏：上一首/播放暂停/下一首 */
}

/* ------------------------------------------------------------
 * LRC 解析：[mm:ss.xx]文本，按时间升序；正文内 '\x01' 分隔原文/译文
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
        dst[n].bi = (strchr(dst[n].text, LRC_SEP) != 0) ? 1u : 0u;
        if (!dst[n].bi) wrap_40(dst[n].text);   /* 单语长句：折成两行，保持 40px */
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
        if (s_lines[i].t_ms <= ms) a = i; else break;
    }
    return a;
}

/* ------------------------------------------------------------
 * 下半屏歌词
 * ------------------------------------------------------------ */
/* 这一块该用多大字号：40（原生，最清晰）→ 32（16x16 放大）→ 16 */
static uint8_t blk_font(int idx)
{
    const char *txt = s_lines[idx].text;

    if (strchr(txt, LRC_BR)) return 40u;      /* 已折成两行：两行都用原生 40px */
    if (text40_ok(txt) && text40_width(txt) <= UI_W - LYR_X - 12u) return 40u;
    if (text_width(txt, 2u) <= UI_W - LYR_X - 12u) return 32u;
    return 16u;
}

/* 块步距（含块间空隙）：随字号变化，保证整屏排得下 */
static uint16_t blk_step(int idx)
{
    uint8_t f = blk_font(idx);
    uint8_t bi = s_lines[idx].bi ? 1u : 0u;
    uint8_t br = (strchr(s_lines[idx].text, LRC_BR) != 0) ? 1u : 0u;

    if (f == 40u) {
        if (br) return bi ? 108u : 92u;     /* 两行 40px(84) + 译文/空隙 */
        return bi ? 68u : 52u;              /* 40 + 4 + 16 + 空隙 */
    }
    if (f == 32u) return bi ? 72u : 44u;
    return bi ? 56u : 28u;
}

/* 画一条歌词块：原文 32px，译文 16px（有译文时）
 * 当前句颜色由 s_col_orig/s_col_trans 决定（动效会一直改它们），
 * 同时把当前句的矩形记下来，供动效只重画这一块。 */
static void draw_block(uint16_t y, int idx, uint8_t hl)
{
    const char *txt = s_lines[idx].text;
    const char *trans = strchr(txt, LRC_SEP);
    const char *br = strchr(txt, LRC_BR);
    uint8_t has_trans = (trans && trans[1]) ? 1u : 0u;
    uint8_t f = blk_font(idx);
    uint16_t col_orig = hl ? s_col_orig : UI_COL_NORMAL;
    uint16_t col_trans = hl ? s_col_trans : UI_COL_DIM;
    uint16_t h_total, ty;

    if (f == 40u) {
        draw_text40(LYR_X, y, txt, col_orig, LYR_LIMIT);   /* 原生 40px，无块状放大 */
        if (br) {
            /* 折行：第二行紧接在第一行下面（仍是 40px 原生） */
            draw_text40(LYR_X, (uint16_t)(y + 44u), br + 1, col_orig, LYR_LIMIT);
            h_total = 84u;
            ty = (uint16_t)(y + 88u);
        } else {
            h_total = 40u;
            ty = (uint16_t)(y + 44u);
        }
    } else if (f == 32u) {
        draw_text(LYR_X, y, txt, col_orig, 2u, UI_W - 1u);
        h_total = 32u;
        ty = (uint16_t)(y + 36u);
    } else {
        draw_text(LYR_X, y, txt, col_orig, 1u, UI_W - 1u);
        h_total = 16u;
        ty = (uint16_t)(y + 20u);
    }

    if (has_trans) {
        draw_text(LYR_X, ty, trans + 1, col_trans, 1u, LYR_LIMIT);
        h_total = (uint16_t)(h_total + 20u);
    }
    if (hl) {
        lcd_fill(LYR_MARK_X, y, (uint16_t)(LYR_MARK_X + 3u),
                 (uint16_t)(y + h_total - 4u), col_orig);
        s_act_y = y;
        s_act_h = h_total;
    }
}

/* 歌词区整体重画：当前块固定落在「从上数第 3 格」，前面几块不够时就从顶部排。
 * 这样开机（还没播）也是满屏歌词，且第一句开始唱时不会整块跳动。 */
static void draw_lyrics(int active)
{
    int anchor, i;
    int32_t ytop, y;
    const int32_t area_h = (int32_t)(LYR_Y1 + 1u - LYR_Y0);

    lcd_fill((uint16_t)(LYR_MARK_X - 4u), LYR_Y0, UI_W - 1u, UI_H - 1u, UI_COL_BG);

    if (s_cur_n == 0) {
        draw_text(300u, 340u, (const char *)"\xCE\xDE\xB8\xE8\xB4\xCA",
                  UI_COL_DIM, 2u, UI_W - 1u);
        return;
    }

    anchor = (active < 0) ? 0 : active;
    s_act_h = 0;                 /* 本帧没有高亮块时，动效不要乱画 */

    /* 当前句固定在歌词区垂直正中：上方回填唱过的，下方依次排没唱的。
     * （原来是「固定第 3 格」，唱的那句总靠上，看起来像歌词在顶部堆着。） */
    ytop = (int32_t)LYR_Y0 + (area_h - (int32_t)blk_step(anchor)) / 2;
    if (ytop < (int32_t)LYR_Y0) ytop = (int32_t)LYR_Y0;

    /* 上方：从当前句往上回填历史歌词，超出上边界就停 */
    y = ytop;
    for (i = anchor - 1; i >= 0; i--) {
        int32_t h = (int32_t)blk_step(i);
        if (y - h < (int32_t)LYR_Y0) break;
        y -= h;
        draw_block((uint16_t)y, i, 0u);
    }

    /* 当前句（高亮 + 变色） */
    draw_block((uint16_t)ytop, anchor, (uint8_t)(active >= 0));

    /* 下方：后面的歌词依次往下排，超出下边界就停 */
    y = ytop + (int32_t)blk_step(anchor);
    for (i = anchor + 1; i < s_cur_n; i++) {
        uint16_t h = blk_step(i);
        if (y + (int32_t)h > LYR_Y1 + 1) break;
        draw_block((uint16_t)y, i, 0u);
        y += (int32_t)h;
    }
}

/* ------------------------------------------------------------
 * 公开接口
 * ------------------------------------------------------------ */
/* 上位机通过 CDC 控制线选曲（0..SONG_COUNT-1）。
 * 在 USB 中断上下文调用：只记标志，不碰 LCD。 */
void lcd_ui_select_song(uint8_t idx)
{
    if (idx >= SONG_COUNT) return;
    s_req_song = idx;
    s_song_pending = 1;
}

uint8_t lcd_ui_init(void)
{
    lcd_init();
    LCD_BL(1);
    lcd_display_dir(1);         /* 横屏 800x480 */

    lcd_clear(UI_COL_BG);

    s_song  = (int)UI_DEFAULT_SONG;
    s_cur_n = parse_lrc(s_lrcs[s_song], s_lines);

    draw_top();

    s_active = -1;
    s_last_active = -2;
    s_last_sec = 0xFFFFFFFFu;
    s_ready = 1;
    draw_lyrics(-1);
    draw_progress(0);
    return 0;
}

void lcd_ui_tick(uint32_t played_ms)
{
    uint32_t now;
    int active;

    if (!s_ready) return;
    now = HAL_GetTick();
    if ((uint32_t)(now - s_last_tick) < TICK_MS) return;
    s_last_tick = now;

    /* 1) 处理上位机选曲信号：换歌词 + 换封面 + 时间轴归零 */
    if (s_song_pending) {
        s_song_pending = 0;
        if ((int)s_req_song != s_song) {
            s_song  = (int)s_req_song;
            s_cur_n = parse_lrc(s_lrcs[s_song], s_lines);
            s_active = -1;
            s_last_active = -2;
            audio_stream_reset_position();   /* 新曲：歌词时钟清零 */
            draw_top();
            draw_lyrics(-1);
            draw_progress(0);
            return;
        }
        audio_stream_reset_position();
        s_last_active = -2;
    }

    /* 2) 歌词时间 = 已播放的真实 PCM 时长 */
    active = find_active(played_ms);
    if (active != s_last_active) {
        draw_lyrics(active);
        s_last_active = active;
        s_active = active;
    }

    /* 3) 进度条 / 时间 */
    draw_progress(played_ms);

    /* 4) 卡拉OK 式变色：当前句的颜色一直流动。
     *    只在「真的在播」（时间轴在前进）时才跑，暂停/没数据就停住，别空转刷屏；
     *    而且只重画当前那一块（~52 行 × 800），不动其他歌词。 */
    if (played_ms != s_last_pos) {
        s_last_pos = played_ms;
        if (s_active >= 0 && s_act_h != 0u &&
            (uint32_t)(now - s_anim_tick) >= ANIM_MS) {
            uint8_t hue = (uint8_t)((now / 22u) & 0xFFu);   /* 255*22ms ≈ 5.6s 一圈 */

            s_anim_tick = now;
            s_col_orig  = hsv565(hue);
            s_col_trans = dim565(s_col_orig, 150u);
            /* 🔴 只清右栏歌词区！这里原来从 x=0 整屏清，改版成「左1/3图+右2/3歌词」后
             * 没跟着改，导致每 110ms 用黑横条把左栏封面/歌名擦掉一次 —— 就是照片里
             * 「黑色挡住封面」的真正原因。 */
            lcd_fill((uint16_t)(LYR_MARK_X - 4u), s_act_y, UI_W - 1u,
                     (uint16_t)(s_act_y + s_act_h - 1u), UI_COL_BG);
            draw_block(s_act_y, s_active, 1u);
        }
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
        restore_rect(PANEL_X, TITLE_Y, (uint16_t)(PANEL_R - PANEL_X), 32u);
        draw_panel();
    }
}

void lcd_ui_set_meta(const char *title, const char *artist)
{
    size_t l;

    s_track[0] = '\0';
    s_artist_ovr[0] = '\0';
    if (title) {
        l = strlen(title);
        if (l > sizeof(s_track) - 1u) l = sizeof(s_track) - 1u;
        memcpy(s_track, title, l);
        s_track[l] = '\0';
    }
    if (artist) {
        l = strlen(artist);
        if (l > sizeof(s_artist_ovr) - 1u) l = sizeof(s_artist_ovr) - 1u;
        memcpy(s_artist_ovr, artist, l);
        s_artist_ovr[l] = '\0';
    }
    if (s_ready) {
        restore_rect(PANEL_X, TITLE_Y, (uint16_t)(PANEL_R - PANEL_X), 60u);
        draw_panel();
    }
}

int lcd_ui_load_lrc(const char *gbk_lrc)
{
    s_cur_n = parse_lrc(gbk_lrc ? gbk_lrc : s_lrcs[s_song], s_lines);
    s_last_active = -2;
    return s_cur_n;
}

int lcd_ui_line_count(void)  { return s_cur_n; }
int lcd_ui_active_line(void) { return s_active; }
int lcd_ui_current_song(void) { return s_song; }
uint8_t lcd_ui_song_count(void) { return (uint8_t)SONG_COUNT; }

void lcd_ui_set_duration(uint32_t ms)
{
    s_dur_override = ms;
    s_bar_fill = 0;
    s_last_sec = 0xFFFFFFFFu;      /* 下一拍重画进度条与时间 */
}

void lcd_ui_set_paused(int paused)
{
    s_paused = paused ? 1u : 0u;
    if (!s_ready) return;
    restore_rect((uint16_t)(PANEL_X + 84u), VOL_Y, 88u, 16u);
    if (s_paused) {
        draw_text_halo((uint16_t)(PANEL_X + 84u), VOL_Y, (const char *)"PAUSE",
                       UI_COL_ACTIVE, 1u, PANEL_R);
    }
    draw_btn_play();       /* 按钮图标跟着变：播放中=⏸，暂停=▶ */
}

void lcd_ui_set_volume(uint8_t vol)
{
    if (vol > 100u) vol = 100u;
    if (vol == s_volume) return;
    s_volume = vol;
    if (s_ready) draw_volume();
}
