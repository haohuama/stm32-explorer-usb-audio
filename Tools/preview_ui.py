#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""在电脑上按固件同一套版式渲染 LCD 画面预览（800x480 PNG）。

数据来源全是固件里真正会烧进去的头文件：
    User/Hardware/LCD/cover_img.h   封面 240x240 + 背景板 400x120（RGB565）
    User/Hardware/LCD/lrc_data.h    歌名/歌手/时长/歌词
    User/Hardware/LCD/cn_font.h     16x16 汉字点阵
    User/Hardware/LCD/lcdfont.h     8x16 ASCII 点阵 asc2_1608
版式常量与 lcd_ui.c 一一对应 —— 用于烧录前确认「上半图片 / 下半歌词」没错位。

用法:
    python Tools/preview_ui.py --song 5 --time 01:10
    python Tools/preview_ui.py --song 5 --time 00:05 --out preview_05.png
    python Tools/preview_ui.py --song 1 --time 00:40        # 无封面曲目
"""
import argparse
import os
import re

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LCD = os.path.join(ROOT, "User/Hardware/LCD")

# ---- 与 lcd_ui.c 完全一致的版式常量 ----
UI_W, UI_H = 800, 480
TOP_H = 240
COVER_X, COVER_Y = 0, 0
PANEL_X, PANEL_R = 272, 788
TITLE_Y, ARTIST_Y = 52, 92
BAR_X, BAR_Y, BAR_W, BAR_H = 272, 150, 517, 6
TIME_Y = 164
VOL_Y = 196
LYR_SPLIT_Y = 240
LYR_Y0, LYR_Y1 = 248, 472
LYR_X, LYR_MARK_X = 26, 10
BLK_STEP_BI, BLK_STEP_MONO = 72, 44

COL = {
    "bg": 0x0000, "split": 0x2104, "edge": 0x2104,
    "title": 0xFFFF, "artist": 0xBDF7, "track": 0x3186, "fill": 0xFFFF,
    "time": 0xE71C, "time_total": 0x8C71,
    "active": 0xFFE0, "act_trans": 0xFDA0, "normal": 0xCE79, "dim": 0x632C,
}
SEP = "\x01"
ASC_W40, ASC_STRIDE40 = 20, 3   # 与 cn_font40.h 的 ASC40_W / ASC40_STRIDE 一致（load_font40 会覆盖）


def hsv565(h):
    """与 lcd_ui.c 的 hsv565() 同算法：h 0..255 一圈彩虹。"""
    region = h // 43
    rem = (h - region * 43) * 6
    q = 255 - rem
    r, g, b = [(255, rem, 0), (q, 255, 0), (0, 255, rem),
               (0, q, 255), (rem, 0, 255), (255, 0, q)][region]
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def dim565(c, k=150):
    r = ((c >> 11) & 0x1F) * k // 255
    g = ((c >> 5) & 0x3F) * k // 255
    b = (c & 0x1F) * k // 255
    return (r << 11) | (g << 5) | b


def rgb565(v):
    r = (v >> 11) & 0x1F
    g = (v >> 5) & 0x3F
    b = v & 0x1F
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def read(path):
    return open(path, encoding="utf-8", errors="ignore").read()


def load_cover(song):
    """-> (cover list|None, bg list|None)"""
    path = os.path.join(LCD, "cover_img.h")
    if not os.path.exists(path):
        return None, None
    s = read(path)

    def array(name, n):
        m = re.search(r"static const uint16_t %s\[\] = \{(.*?)\n\};" % name, s, re.S)
        if not m:
            return None
        vals = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{4})", m.group(1))]
        return vals if len(vals) == n else None

    # 没有单独封面的曲目，固件里指向 s_coverD / s_bgD（默认封面），预览同规则
    return (array("s_cover%d" % song, 240 * 240) or array("s_coverD", 240 * 240),
            array("s_bg%d" % song, 400 * 120) or array("s_bgD", 400 * 120))


def unescape(s):
    out, i = bytearray(), 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            n = s[i + 1]
            if n == "x":
                out.append(int(s[i + 2:i + 4], 16)); i += 4; continue
            if n == "n":
                out.append(10); i += 2; continue
            if n == "r":
                out.append(13); i += 2; continue
            out.extend(n.encode("gbk", "replace")); i += 2; continue
        out.extend(ch.encode("gbk", "replace")); i += 1
    return bytes(out).decode("gbk", "replace")


def load_song(song):
    s = read(os.path.join(LCD, "lrc_data.h"))
    title = unescape(re.search(r'static const char s_title%d\[\] = "(.*?)";' % song, s).group(1))
    ma = re.search(r'static const char s_artist%d\[\] = "(.*?)";' % song, s)
    artist = unescape(ma.group(1)) if ma else ""
    dur = int(re.search(r"static const uint32_t s_dur%d = (\d+)u;" % song, s).group(1))
    body = re.search(r'static const char s_lrc%d\[\] =\n(.*?)";' % song, s, re.S).group(1)
    lines = []
    for row in re.findall(r'"(.*)"', body):
        txt = unescape(row)
        m = re.match(r"\[(\d+):(\d+)\.(\d+)\](.*)", txt, re.S)
        if not m:
            continue
        ms = (int(m.group(1)) * 60 + int(m.group(2))) * 1000 + int(m.group(3)) * 10
        lines.append((ms, m.group(4).strip("\r\n")))
    return title, artist, dur, lines


def load_cn_font():
    s = read(os.path.join(LCD, "cn_font.h"))
    out = {}
    for gbk, bits in re.findall(r"\{0x([0-9A-Fa-f]{4}), \{([^}]*)\}\}", s):
        out[int(gbk, 16)] = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", bits)]
    return out


def load_font40():
    """读 cn_font40.h：-> (cn40: gbk->200bytes, asc40: [95][80])"""
    path = os.path.join(LCD, "cn_font40.h")
    if not os.path.exists(path):
        return {}, []
    txt = read(path)
    cn40 = {}
    for gbk, body in re.findall(r"\{0x([0-9A-Fa-f]{4}),\{([^}]*)\}\}", txt):
        cn40[int(gbk, 16)] = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", body)]
    mw = re.search(r"#define ASC40_W (\d+)u", txt)
    ms = re.search(r"#define ASC40_STRIDE (\d+)u", txt)
    global ASC_W40, ASC_STRIDE40
    if mw:
        ASC_W40 = int(mw.group(1))
    if ms:
        ASC_STRIDE40 = int(ms.group(1))
    m = re.search(r"g_asc40\[95\]\[(\d+)\] = \{(.*?)\n\};", txt, re.S)
    asc40 = []
    if m:
        per = int(m.group(1))
        for row in re.findall(r"\{([^}]*)\}", m.group(2)):
            v = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", row)]
            asc40.append(v + [0] * (per - len(v)))
    return cn40, asc40


def draw_cn40(cv, x, y, bits, col):
    for row in range(40):
        p = bits[row * 5:row * 5 + 5]
        if not any(p):
            continue
        line = (p[0] << 32) | (p[1] << 24) | (p[2] << 16) | (p[3] << 8) | p[4]
        c = 0
        while c < 40:
            if line & (0x8000000000 >> c):
                run = c
                while c < 40 and (line & (0x8000000000 >> c)):
                    c += 1
                cv.fill(x + run, y + row, x + c - 1, y + row, col)
            else:
                c += 1


def draw_ascii40(cv, x, y, ch, col, asc40, width=None, stride=None):
    """按 cn_font40.h 的 ASC40_W/ASC40_STRIDE 绘制（当前 20 宽 = 每行 3 字节）。"""
    if width is None:
        width = ASC_W40
    if stride is None:
        stride = ASC_STRIDE40
    if not (0x20 <= ord(ch) <= 0x7E) or not asc40:
        ch = " "
    p = asc40[ord(ch) - 0x20]
    top = 1 << (width - 1)
    for row in range(40):
        bits = 0
        for k in range(stride):
            bits = (bits << 8) | p[row * stride + k]
        if not bits:
            continue
        c = 0
        while c < width:
            if bits & (top >> c):
                run = c
                while c < width and (bits & (top >> c)):
                    c += 1
                cv.fill(x + run, y + row, x + c - 1, y + row, col)
            else:
                c += 1


def text40_ok(txt, cn40):
    for ch in txt.split(SEP)[0]:
        if ord(ch) < 0x80:
            continue
        if int.from_bytes(ch.encode("gbk", "replace"), "big") not in cn40:
            return False
    return True


def text40_width(txt):
    return sum((ASC_W40 if ord(c) < 0x80 else 40) for c in txt.split(SEP)[0])


def draw_text40(cv, x, y, txt, col, x_limit, cn40, asc40):
    px = x
    for ch in txt.split(SEP)[0]:
        adv = ASC_W40 if ord(ch) < 0x80 else 40
        if px + adv > x_limit:
            break
        if ord(ch) < 0x80:
            draw_ascii40(cv, px, y, ch, col, asc40)
        else:
            bits = cn40.get(int.from_bytes(ch.encode("gbk", "replace"), "big"))
            if bits:
                draw_cn40(cv, px, y, bits, col)
        px += adv


def load_ascii_font():
    s = read(os.path.join(LCD, "lcdfont.h"))
    m = re.search(r"asc2_1608\[95\]\[16\]=\{(.*?)\n\};", s, re.S)
    rows = re.findall(r"\{([^}]*)\}", m.group(1))
    out = []
    for r in rows:
        v = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", r)]
        out.append(v + [0] * (16 - len(v)))
    return out


class Canvas:
    def __init__(self):
        self.img = Image.new("RGB", (UI_W, UI_H), rgb565(COL["bg"]))
        self.d = ImageDraw.Draw(self.img)

    def fill(self, x1, y1, x2, y2, col):
        if x2 < x1 or y2 < y1:
            return
        self.d.rectangle([x1, y1, x2, y2], fill=rgb565(col))

    def px(self, x, y, col):
        if 0 <= x < UI_W and 0 <= y < UI_H:
            self.img.putpixel((x, y), rgb565(col))


def draw_cn(cv, x, y, bits, col, scale):
    for row in range(16):
        line = (bits[row * 2] << 8) | bits[row * 2 + 1]
        if not line:
            continue
        col_i = 0
        while col_i < 16:
            if line & (0x8000 >> col_i):
                run = col_i
                while col_i < 16 and (line & (0x8000 >> col_i)):
                    col_i += 1
                cv.fill(x + run * scale, y + row * scale,
                        x + col_i * scale - 1, y + row * scale + scale - 1, col)
            else:
                col_i += 1


def draw_ascii(cv, x, y, ch, col, scale, ascii_font):
    if not (0x20 <= ord(ch) <= 0x7E):
        ch = " "
    p = ascii_font[ord(ch) - 0x20]
    for c in range(8):
        bits = (p[c * 2] << 8) | p[c * 2 + 1]
        if not bits:
            continue
        row = 0
        while row < 16:
            if bits & (0x8000 >> row):
                r0 = row
                while row < 16 and (bits & (0x8000 >> row)):
                    row += 1
                cv.fill(x + c * scale, y + r0 * scale,
                        x + c * scale + scale - 1, y + row * scale - 1, col)
            else:
                row += 1


def text_width(s, scale):
    w = 0
    for ch in s.split(SEP)[0]:
        w += (8 if ord(ch) < 0x80 else 16) * scale
    return w


def draw_text(cv, x, y, s, col, scale, x_limit, cn, asc):
    px = x
    for ch in s.split(SEP)[0]:
        adv = (8 if ord(ch) < 0x80 else 16) * scale
        if px + adv > x_limit:
            break
        if ord(ch) < 0x80:
            draw_ascii(cv, px, y, ch, col, scale, asc)
        else:
            bits = cn.get(int.from_bytes(ch.encode("gbk", "replace"), "big"))
            if bits:
                draw_cn(cv, px, y, bits, col, scale)
        px += adv
    return px - x


def fmt_time(ms):
    ss = ms // 1000
    return "%02d:%02d" % (ss // 60, ss % 60)


def mix565(a, b):
    r = ((a >> 11) + (b >> 11)) >> 1
    g = (((a >> 5) & 0x3F) + ((b >> 5) & 0x3F)) >> 1
    bl = ((a & 0x1F) + (b & 0x1F)) >> 1
    return (r << 11) | (g << 5) | bl


def bg_px(bg, x, y):
    """与 lcd_ui.c 的 bg_px() 同算法：400x120 -> 800x240 双线性放大。"""
    sx, sy = x >> 1, y >> 1
    x1 = sx + 1 if sx + 1 < 400 else sx
    y1 = sy + 1 if sy + 1 < 120 else sy
    v = bg[sy * 400 + sx]
    if x & 1:
        v = mix565(v, bg[sy * 400 + x1])
    if y & 1:
        v = mix565(v, bg[y1 * 400 + sx])
    return v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", type=int, default=5)
    ap.add_argument("--time", default="00:60", help="mm:ss")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    title, artist, dur, lines = load_song(args.song)
    cover, bg = load_cover(args.song)
    cn = load_cn_font()
    asc = load_ascii_font()
    cn40, asc40 = load_font40()

    mm, ss = args.time.split(":")
    pos = (int(mm) * 60 + int(ss)) * 1000

    cv = Canvas()

    # ---- 上半屏 ----
    if bg:
        for y in range(TOP_H):
            for x in range(UI_W):
                cv.img.putpixel((x, y), rgb565(bg_px(bg, x, y)))
    else:
        for y in range(TOP_H):
            t = y
            r = 3 - (2 * t) // (TOP_H - 1)
            g = 9 - (7 * t) // (TOP_H - 1)
            b = 6 - (5 * t) // (TOP_H - 1)
            cv.fill(0, y, UI_W - 1, y, (r << 11) | (g << 5) | b)

    if cover:
        for y in range(240):
            for x in range(240):
                cv.d.rectangle([x, y, x, y], fill=rgb565(cover[y * 240 + x]))
    else:
        # 无封面：居中画曲目序号（与 lcd_ui.c 的 draw_cover() 占位一致）
        if args.song < 10:
            num, sc = str(args.song), 5
        else:
            num, sc = "%02d" % args.song, 3
        w = text_width(num, sc)
        draw_text(cv, (240 - w) // 2, (TOP_H - 16 * sc) // 2, num,
                  COL["dim"], sc, 240, cn, asc)

    cv.fill(240, 0, 241, 239, COL["edge"])

    sc = 2 if text_width(title, 2) <= PANEL_R - PANEL_X else 1
    draw_text(cv, PANEL_X, TITLE_Y, title, COL["title"], sc, PANEL_R, cn, asc)
    if artist:
        draw_text(cv, PANEL_X, ARTIST_Y, artist, COL["artist"], 1, PANEL_R, cn, asc)

    cv.fill(BAR_X, BAR_Y, BAR_X + BAR_W - 1, BAR_Y + BAR_H - 1, COL["track"])
    if dur:
        fill_w = min(BAR_W, BAR_W * min(pos, dur) // dur)
        if fill_w:
            cv.fill(BAR_X, BAR_Y, BAR_X + fill_w - 1, BAR_Y + BAR_H - 1, COL["fill"])
    draw_text(cv, PANEL_X, TIME_Y, fmt_time(min(pos, dur) if dur else pos),
              COL["time"], 1, PANEL_R + 1, cn, asc)
    if dur:
        draw_text(cv, PANEL_R - 39, TIME_Y, fmt_time(dur), COL["time_total"], 1, PANEL_R + 1, cn, asc)

    draw_text(cv, PANEL_X, VOL_Y, "VOL 48", COL["time_total"], 1, PANEL_R, cn, asc)

    cv.fill(0, LYR_SPLIT_Y, UI_W - 1, LYR_SPLIT_Y + 1, COL["split"])

    # ---- 下半屏歌词（与 draw_lyrics 同算法）----
    cv.fill(0, LYR_Y0, UI_W - 1, UI_H - 1, COL["bg"])
    if not lines:
        draw_text(cv, 300, 340, "无歌词", COL["dim"], 2, UI_W - 1, cn, asc)
    else:
        active = -1
        for i, (ms, _) in enumerate(lines):
            if ms <= pos:
                active = i
            else:
                break
        def blk_font(txt):
            if text40_ok(txt, cn40) and text40_width(txt) <= UI_W - LYR_X - 12:
                return 40
            if text_width(txt.split(SEP)[0], 2) <= UI_W - LYR_X - 12:
                return 32
            return 16

        def step(i):
            f = blk_font(lines[i][1])
            bi = SEP in lines[i][1]
            if f == 40:
                return 68 if bi else 52
            if f == 32:
                return 72 if bi else 44
            return 56 if bi else 28
        anchor = max(0, active)
        first = max(0, anchor - 2)
        y = LYR_Y0
        for i in range(first, len(lines)):
            h = step(i)
            if y + h > LYR_Y1 + 1:
                break
            txt = lines[i][1]
            parts = txt.split(SEP)
            orig = parts[0]
            trans = parts[1] if len(parts) > 1 else ""
            hl = (i == active)
            f = blk_font(txt)
            hue = (pos // 22) & 0xFF
            c_act, c_act_tr = hsv565(hue), dim565(hsv565(hue))
            c_o, c_t = (c_act, c_act_tr) if hl else (COL["normal"], COL["dim"])
            if f == 40:
                draw_text40(cv, LYR_X, y, orig, c_o, UI_W - 1, cn40, asc40)
                ty, hh = y + 44, 40
            elif f == 32:
                draw_text(cv, LYR_X, y, orig, c_o, 2, UI_W - 1, cn, asc)
                ty, hh = y + 36, 32
            else:
                draw_text(cv, LYR_X, y, orig, c_o, 1, UI_W - 1, cn, asc)
                ty, hh = y + 20, 16
            if trans:
                draw_text(cv, LYR_X, ty, trans, c_t, 1, UI_W - 1, cn, asc)
                hh += 20
            if hl:
                cv.fill(LYR_MARK_X, y, LYR_MARK_X + 3, y + hh - 4, c_act)
            y += h

    out = args.out or os.path.join(ROOT, "preview_song%d_%s.png" % (args.song, args.time.replace(":", "")))
    cv.img.save(out)
    print("已渲染", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
