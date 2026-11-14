# -*- coding: utf-8 -*-
"""patch_preview_center.py —— 让预览与固件一致：当前句居中、轻遮罩、VOL 038/100"""
import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "Tools", "preview_new.py")
s = io.open(P, encoding="utf-8").read()

# 1) 遮罩调轻
a = """    if y >= 248:
        k = 78 if y >= 320 else 170 - (y - 248) * 92 // 72"""
b = """    if y >= 248:
        k = 210 if y >= 320 else 245 - (y - 248) * 35 // 72   # 最多压暗 18%，不挡封面"""
assert a in s
s = s.replace(a, b, 1)

# 2) VOL 显示
s = s.replace('"VOL 24"', '"VOL 38"')

# 3) 歌词布局：固定第 3 格 -> 当前句垂直居中
a = """        anchor = max(0, active)
        first = max(0, anchor - 2)
        y = LYR_Y0
        hue = (pos_ms // 22) & 0xFF
        c_act, c_tr = P.hsv565(hue), P.dim565(P.hsv565(hue))
        for i in range(first, len(lines)):
            h = step(i, lines, cn40)
            if y + h > LYR_Y1 + 1:
                break
            txt = lines[i][1]"""
b = """        anchor = max(0, active)
        area_h = LYR_Y1 + 1 - LYR_Y0
        ytop = LYR_Y0 + (area_h - step(anchor, lines, cn40)) // 2
        if ytop < LYR_Y0:
            ytop = LYR_Y0
        hue = (pos_ms // 22) & 0xFF
        c_act, c_tr = P.hsv565(hue), P.dim565(P.hsv565(hue))

        def one(i, y, hl):
            h = step(i, lines, cn40)
            txt = lines[i][1]"""
assert a in s
s = s.replace(a, b, 1)

# 上面把 for 头换成函数定义，需要把循环体内剩余部分缩进并改成绘制 + 三段调用
a = """            parts = txt.split(SEP)
            orig = parts[0]
            trans = parts[1] if len(parts) > 1 else ""
            hl = (i == active)
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
            y += h
"""
b = """            parts = txt.split(SEP)
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

        # 上方回填唱过的句子
        y = ytop
        for i in range(anchor - 1, -1, -1):
            h = step(i, lines, cn40)
            if y - h < LYR_Y0:
                break
            y -= h
            one(i, y, False)
        # 当前句（高亮，固定在正中）
        one(anchor, ytop, True)
        # 下方排没唱的
        y = ytop + step(anchor, lines, cn40)
        for i in range(anchor + 1, len(lines)):
            h = step(i, lines, cn40)
            if y + h > LYR_Y1 + 1:
                break
            one(i, y, False)
            y += h
"""
assert a in s, "找不到歌词绘制循环体"
s = s.replace(a, b, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("预览已改为居中滚动")
