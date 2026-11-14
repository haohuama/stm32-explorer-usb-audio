#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""让 preview_ui.py 也用 40px 原生点阵渲染歌词（与固件 blk_font 规则一致）。"""
import os
import sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Tools/preview_ui.py")


def main():
    s = open(P, encoding="utf-8").read()
    if "load_font40" in s:
        print("已打过补丁，跳过")
        return 0

    # 1) 载入 40px 字库
    s = s.replace("def load_ascii_font():",
'''def load_font40():
    """读 cn_font40.h：-> (cn40: gbk->200bytes, asc40: [95][80])"""
    path = os.path.join(LCD, "cn_font40.h")
    if not os.path.exists(path):
        return {}, []
    txt = read(path)
    cn40 = {}
    for gbk, body in re.findall(r"\\{0x([0-9A-Fa-f]{4}),\\{([^}]*)\\}\\}", txt):
        cn40[int(gbk, 16)] = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", body)]
    m = re.search(r"g_asc40\\[95\\]\\[80\\] = \\{(.*?)\\n\\};", txt, re.S)
    asc40 = []
    if m:
        for row in re.findall(r"\\{([^}]*)\\}", m.group(1)):
            v = [int(x, 16) for x in re.findall(r"0x([0-9A-Fa-f]{2})", row)]
            asc40.append(v + [0] * (80 - len(v)))
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


def draw_ascii40(cv, x, y, ch, col, asc40):
    if not (0x20 <= ord(ch) <= 0x7E) or not asc40:
        ch = " "
    p = asc40[ord(ch) - 0x20]
    for row in range(40):
        bits = (p[row * 2] << 8) | p[row * 2 + 1]
        if not bits:
            continue
        c = 0
        while c < 16:
            if bits & (0x8000 >> c):
                run = c
                while c < 16 and (bits & (0x8000 >> c)):
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
    return sum((16 if ord(c) < 0x80 else 40) for c in txt.split(SEP)[0])


def draw_text40(cv, x, y, txt, col, x_limit, cn40, asc40):
    px = x
    for ch in txt.split(SEP)[0]:
        adv = 16 if ord(ch) < 0x80 else 40
        if px + adv > x_limit:
            break
        if ord(ch) < 0x80:
            draw_ascii40(cv, px, y, ch, col, asc40)
        else:
            bits = cn40.get(int.from_bytes(ch.encode("gbk", "replace"), "big"))
            if bits:
                draw_cn40(cv, px, y, bits, col)
        px += adv


def load_ascii_font():''')

    # 2) main 里载入
    s = s.replace("    cn = load_cn_font()\n    asc = load_ascii_font()",
                  "    cn = load_cn_font()\n    asc = load_ascii_font()\n    cn40, asc40 = load_font40()")

    # 3) 歌词块绘制：按 40/32/16 选字号（与 lcd_ui.c 的 blk_font 一致）
    s = s.replace(
'''        step = lambda i: BLK_STEP_BI if SEP in lines[i][1] else BLK_STEP_MONO''',
'''        def blk_font(txt):
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
            return 56 if bi else 28''')

    s = s.replace(
'''            s2 = 2 if text_width(orig, 2) <= UI_W - LYR_X - 12 else 1
            hue = (pos // 22) & 0xFF
            c_act, c_act_tr = hsv565(hue), dim565(hsv565(hue))
            draw_text(cv, LYR_X, y, orig, c_act if hl else COL["normal"], s2,
                      UI_W - 1, cn, asc)
            if trans:
                draw_text(cv, LYR_X, y + 16 * s2 + 4, trans,
                          c_act_tr if hl else COL["dim"], 1, UI_W - 1, cn, asc)
            if hl:
                cv.fill(LYR_MARK_X, y, LYR_MARK_X + 3,
                        y + 16 * s2 + (20 if trans else 0) - 4, c_act)''',
'''            f = blk_font(txt)
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
                cv.fill(LYR_MARK_X, y, LYR_MARK_X + 3, y + hh - 4, c_act)''')

    open(P, "w", encoding="utf-8", newline="\n").write(s)
    print("preview_ui.py 已更新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
