# -*- coding: utf-8 -*-
"""preview_new.py —— 按 lcd_ui.c **当前**版式渲染 800x480 预览。

左 1/3：封面 + 歌名/歌手/进度条/时间/音量 + 三个触屏按钮
右 2/3：40px 原生歌词（长句自动折两行）

复用 preview_ui.py 里的取字模/绘制函数，只重写版式，避免两份字体解析代码。
用法：
    py Tools/preview_new.py --song 6 --time 00:40 --out out.png
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import preview_ui as P   # noqa: E402

# ---- 与 lcd_ui.c 一致的版式常量 ----
UI_W, UI_H = 800, 480
IMG_W = 256
COVER_X, COVER_Y, COVER_W, COVER_H = 8, 16, 240, 240
TOP_H = 240
PANEL_X, PANEL_R = 8, 248
TITLE_Y, ARTIST_Y = 262, 310
BAR_X, BAR_Y, BAR_W, BAR_H = 8, 336, 236, 6
TIME_Y, VOL_Y = 350, 374
BTN_Y, BTN_H, BTN_W = 396, 76, 76
BTN_X0, BTN_X1, BTN_X2 = 4, 88, 172
BTN_COL, BTN_COL_ON = 0x2104, 0x39E7
LYR_X, LYR_MARK_X = 276, 262
LYR_Y0, LYR_Y1, LYR_LIMIT = 6, 474, 796
SEP, BR = "\x01", "\x02"
COL = P.COL


def bg_tile(bg, x, y):
    """lcd_ui.c 的 bg_px()：竖向平铺 + 信息区（y>=248）压暗，保证浅色字看得清。"""
    # 不压暗、不盖黑底：封面完整亮出来，文字靠固件里的 1px 描边保证可读
    return P.bg_px(bg, x, y % TOP_H)


def wrap40(txt, cn40):
    """与 lcd_ui.c 的 wrap_40() 同规则：单语长句在最后能放下的空格处折行。"""
    if SEP in txt or BR in txt:
        return txt
    avail = LYR_LIMIT - LYR_X
    w, i, sp = 0, 0, -1
    while i < len(txt):
        ch = txt[i]
        cw = P.ASC_W40 if ord(ch) < 0x80 else 40   # 必须跟着字库宽度走，否则折行位置和绘制不一致
        if w + cw > avail:
            break
        if ch == " ":
            sp = i
        w += cw
        i += 1
    if i >= len(txt):
        return txt

    def w40(seg):
        return sum((P.ASC_W40 if ord(c) < 0x80 else 40) for c in seg)

    best = -1
    for k in range(1, len(txt)):
        if txt[k] != " ":
            continue
        if w40(txt[:k]) > avail:
            break
        if w40(txt[k + 1:]) > avail:
            continue
        best = k
    if best > 0:
        return txt[:best] + BR + txt[best + 1:]   # 与固件 wrap_40 同规则
    if sp > 0:
        return txt[:sp] + BR + txt[sp + 1:]
    return txt[:i] + BR + txt[i:]


def blk_font(txt, cn40):
    if BR in txt:
        return 40
    if P.text40_ok(txt, cn40) and P.text40_width(txt) <= LYR_LIMIT - LYR_X:
        return 40
    if P.text_width(txt.split(SEP)[0], 2) <= LYR_LIMIT - LYR_X:
        return 32
    return 16


def step(i, lines, cn40):
    f = blk_font(lines[i][1], cn40)
    bi = SEP in lines[i][1]
    br = BR in lines[i][1]
    if f == 40:
        if br:
            return 108 if bi else 92
        return 68 if bi else 52
    if f == 32:
        return 72 if bi else 44
    return 56 if bi else 28


def shade(cv, x, y, w, h):
    """示意固件 shade_rect()：只压暗文字那一小块，保留封面主体"""
    cv.fill(x, y, min(IMG_W - 1, x + w), y + h, COL["edge"])


def draw_tri(cv, x, y, w, h, right, col):
    half = h // 2
    for i in range(h):
        k = i + 1 if i < half else h - i
        seg = max(1, w * k // max(1, half))
        if right:
            cv.fill(x, y + i, x + seg - 1, y + i, col)
        else:
            cv.fill(x + w - seg, y + i, x + w - 1, y + i, col)


def draw_controls(cv, paused):
    for x in (BTN_X0, BTN_X1, BTN_X2):
        cv.fill(x, BTN_Y, x + BTN_W - 1, BTN_Y + BTN_H - 1, BTN_COL)
    # 上一首
    cv.fill(BTN_X0 + 18, BTN_Y + 20, BTN_X0 + 21, BTN_Y + 55, COL["title"])
    draw_tri(cv, BTN_X0 + 24, BTN_Y + 20, 26, 36, False, COL["title"])
    # 播放/暂停
    if paused:
        draw_tri(cv, BTN_X1 + 26, BTN_Y + 20, 26, 36, True, COL["title"])
    else:
        cv.fill(BTN_X1 + 24, BTN_Y + 20, BTN_X1 + 32, BTN_Y + 55, COL["title"])
        cv.fill(BTN_X1 + 42, BTN_Y + 20, BTN_X1 + 50, BTN_Y + 55, COL["title"])
    # 下一首
    draw_tri(cv, BTN_X2 + 22, BTN_Y + 20, 26, 36, True, COL["title"])
    cv.fill(BTN_X2 + 50, BTN_Y + 20, BTN_X2 + 53, BTN_Y + 55, COL["title"])


def render(song, pos_ms, out, paused=False):
    title, artist, dur, lines = P.load_song(song)
    cover, bg = P.load_cover(song)
    cn, asc = P.load_cn_font(), P.load_ascii_font()
    cn40, asc40 = P.load_font40()

    # 固件是在 parse_lrc 里就把长句折好（写进 s_lines），步距也按折行后的算；
    # 预览必须同样先折再排版，否则折行块会和下一块重叠。
    lines = [(ms, wrap40(txt, cn40)) for ms, txt in lines]

    cv = P.Canvas()
    cv.fill(IMG_W, 0, UI_W - 1, UI_H - 1, COL["bg"])

    # 左栏背景
    if bg:
        for y in range(UI_H):
            for x in range(IMG_W):
                cv.img.putpixel((x, y), P.rgb565(bg_tile(bg, x, y)))
    else:
        for y in range(UI_H):
            r = 3 - (2 * y) // (UI_H - 1)
            g = 9 - (7 * y) // (UI_H - 1)
            b = 6 - (5 * y) // (UI_H - 1)
            cv.fill(0, y, IMG_W - 1, y, (r << 11) | (g << 5) | b)

    # 封面 / 占位序号
    if cover:
        for y in range(COVER_H):
            for x in range(COVER_W):
                cv.img.putpixel((COVER_X + x, COVER_Y + y),
                                P.rgb565(cover[y * COVER_W + x]))
    else:
        num = str(song)
        sc = 5 if song < 10 else 3
        w = P.text_width(num, sc)
        P.draw_text(cv, COVER_X + (COVER_W - w) // 2,
                    COVER_Y + (COVER_H - 16 * sc) // 2, num, COL["dim"], sc,
                    COVER_X + COVER_W, cn, asc)

    cv.fill(IMG_W, 0, IMG_W + 1, UI_H - 1, COL["edge"])

    # 歌名/歌手/进度/时间/音量
    # 歌名优先 40px 原生（与固件 draw_panel 一致）
    if P.text40_ok(title, cn40) and P.text40_width(title) <= PANEL_R - PANEL_X:
        shade(cv, PANEL_X, TITLE_Y, P.text40_width(title) + 6, 44)
        P.draw_text40(cv, PANEL_X, TITLE_Y, title, COL["title"], PANEL_R, cn40, asc40)
    else:
        sc = 2 if P.text_width(title, 2) <= PANEL_R - PANEL_X else 1
        shade(cv, PANEL_X, TITLE_Y, P.text_width(title, sc) + 6, 16 * sc + 3)
        P.draw_text(cv, PANEL_X, TITLE_Y, title, COL["title"], sc, PANEL_R, cn, asc)
    if artist:
        shade(cv, PANEL_X, ARTIST_Y, P.text_width(artist, 1) + 6, 19)
        P.draw_text(cv, PANEL_X, ARTIST_Y, artist, COL["artist"], 1, PANEL_R, cn, asc)

    cv.fill(BAR_X, BAR_Y, BAR_X + BAR_W - 1, BAR_Y + BAR_H - 1, COL["track"])
    if dur:
        fw = min(BAR_W, BAR_W * min(pos_ms, dur) // dur)
        if fw:
            cv.fill(BAR_X, BAR_Y, BAR_X + fw - 1, BAR_Y + BAR_H - 1, COL["fill"])
    shade(cv, PANEL_X, TIME_Y, 46, 19)
    P.draw_text(cv, PANEL_X, TIME_Y, P.fmt_time(min(pos_ms, dur) if dur else pos_ms),
                COL["time"], 1, PANEL_R + 1, cn, asc)
    if dur:
        t = P.fmt_time(dur)
        shade(cv, PANEL_R - (len(t) * 8) + 1, TIME_Y, len(t) * 8 + 6, 19)
        P.draw_text(cv, PANEL_R - (len(t) * 8) + 1, TIME_Y, t, COL["time_total"], 1,
                    PANEL_R + 1, cn, asc)

    shade(cv, PANEL_X, VOL_Y, 7 * 8 + 6, 19)
    P.draw_text(cv, PANEL_X, VOL_Y, "VOL 38", COL["time_total"], 1, PANEL_R, cn, asc)
    draw_controls(cv, paused)

    # 歌词
    cv.fill(LYR_MARK_X - 4, LYR_Y0, UI_W - 1, UI_H - 1, COL["bg"])
    if not lines:
        P.draw_text(cv, 300, 200, "无歌词", COL["dim"], 2, UI_W - 1, cn, asc)
    else:
        active = -1
        for i, (ms, _) in enumerate(lines):
            if ms <= pos_ms:
                active = i
            else:
                break
        anchor = max(0, active)
        area_h = LYR_Y1 + 1 - LYR_Y0
        ytop = LYR_Y0 + (area_h - step(anchor, lines, cn40)) // 2
        if ytop < LYR_Y0:
            ytop = LYR_Y0
        hue = (pos_ms // 22) & 0xFF
        c_act, c_tr = P.hsv565(hue), P.dim565(P.hsv565(hue))

        def one(i, y, hl):
            txt = wrap40(lines[i][1], cn40)
            parts = txt.split(SEP)
            orig = parts[0]
            trans = parts[1] if len(parts) > 1 else ""
            f = blk_font(txt, cn40)
            c_o = c_act if hl else COL["normal"]
            c_t = c_tr if hl else COL["dim"]
            if f == 40:
                segs = orig.split(BR)
                P.draw_text40(cv, LYR_X, y, segs[0], c_o, LYR_LIMIT, cn40, asc40)
                hh = 40
                ty = y + 44
                if len(segs) > 1:
                    P.draw_text40(cv, LYR_X, y + 44, segs[1], c_o, LYR_LIMIT, cn40, asc40)
                    hh, ty = 84, y + 88
            elif f == 32:
                P.draw_text(cv, LYR_X, y, orig, c_o, 2, LYR_LIMIT, cn, asc)
                hh, ty = 32, y + 36
            else:
                P.draw_text(cv, LYR_X, y, orig, c_o, 1, LYR_LIMIT, cn, asc)
                hh, ty = 16, y + 20
            if trans:
                P.draw_text(cv, LYR_X, ty, trans, c_t, 1, LYR_LIMIT, cn, asc)
                hh += 20
            if hl:
                cv.fill(LYR_MARK_X, y, LYR_MARK_X + 3, y + hh - 4, c_act)

        # 当前句固定在歌词区正中间；上方回填唱过的，下方排没唱的
        y = ytop
        for i in range(anchor - 1, -1, -1):
            h = step(i, lines, cn40)
            if y - h < LYR_Y0:
                break
            y -= h
            one(i, y, False)
        one(anchor, ytop, True)
        y = ytop + step(anchor, lines, cn40)
        for i in range(anchor + 1, len(lines)):
            h = step(i, lines, cn40)
            if y + h > LYR_Y1 + 1:
                break
            one(i, y, False)
            y += h

    cv.img.save(out)
    print("saved", out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--song", type=int, default=6)
    ap.add_argument("--time", default="00:40")
    ap.add_argument("--paused", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    mm, ss = a.time.split(":")
    out = a.out or os.path.join(P.ROOT, "preview_s%d_%s.png" % (a.song, a.time.replace(":", "")))
    render(a.song, (int(mm) * 60 + int(ss)) * 1000, out, a.paused)


if __name__ == "__main__":
    main()
