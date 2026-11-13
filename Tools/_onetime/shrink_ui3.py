#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第三轮精简：演示歌词 8 -> 6 行，给 Keil startup.s 留足余量。

处理后 Local ROM 应约为 31.6KB，加 startup 约 32.2KB，稳定低于 32768。
"""
import re

BS = chr(92)
NL = BS + "n"

LYRICS = [
    ("00:00.00", "演示歌词 非真实歌曲"),
    ("00:08.00", "请把 LRC 文件给我"),
    ("00:16.00", "探索者 F407 播放中"),
    ("00:24.00", "USB CDC 接收音频"),
    ("00:32.00", "I2S 送往 WM8978"),
    ("00:40.00", "歌词逐行高亮滚动"),
]


def esc(t):
    return "".join(BS + "x%02X" % b for b in t.encode("gbk"))


def main():
    lines = ['    "[%s]%s%s"' % (t, esc(s), NL) for t, s in LYRICS]
    body = "\n".join(lines) + ";"

    p = r"C:/stm32TEST/User/Hardware/LCD/lcd_ui.c"
    src = open(p, "r", encoding="utf-8", errors="ignore").read()
    m = re.search(r"static const char s_demo_lrc\[\] =\n(?:.*?\n)*?.*?;\n", src, re.S)
    if not m:
        raise SystemExit("s_demo_lrc not found")
    src = src[:m.start()] + "static const char s_demo_lrc[] =\n" + body + "\n" + src[m.end():]
    open(p, "w", encoding="utf-8", newline="").write(src)
    print("lcd_ui.c lyrics =", len(LYRICS))

    p2 = r"C:/stm32TEST/Tools/gen_cn_font.py"
    s2 = open(p2, encoding="utf-8").read()
    block = "DEMO_LYRICS = [\n" + "".join('    "%s",\n' % s for _, s in LYRICS) + "]\n"
    s2 = re.sub(r"DEMO_LYRICS = \[\n(?:.*?\n)*?\]\n", block, s2, count=1)
    open(p2, "w", encoding="utf-8", newline="").write(s2)
    print("gen_cn_font.py synced")


if __name__ == "__main__":
    main()
