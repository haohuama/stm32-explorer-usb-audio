#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 lcd_ui.c 的演示歌词缩到 8 行、去掉进度条，并同步 gen_cn_font.py。

用于在 Keil MDK-Lite 32KB 限制下腾空间。反斜杠全部用 chr(92) 构造，
避免经 shell heredoc 传递时被吞。
"""
import re

BS = chr(92)
NL_ESC = BS + "n"

LYRICS = [
    ("00:00.00", "演示歌词 非真实歌曲"),
    ("00:08.00", "请把 LRC 文件给我替换"),
    ("00:16.00", "探索者 F407 正在播放"),
    ("00:24.00", "USB CDC 接收电脑音频"),
    ("00:32.00", "I2S 送往 WM8978 解码"),
    ("00:40.00", "FSMC 并口点亮这块屏"),
    ("00:48.00", "歌词随进度逐行高亮"),
    ("00:56.00", "局部刷新 不抢总线"),
]


def gbk_esc(text):
    return "".join(BS + "x%02X" % b for b in text.encode("gbk"))


def main():
    lines = ['    "[%s]%s%s"' % (t, gbk_esc(s), NL_ESC) for t, s in LYRICS]
    new_lrc = "\n".join(lines) + ";"

    p = r"C:/stm32TEST/User/Hardware/LCD/lcd_ui.c"
    src = open(p, "r", encoding="utf-8", errors="ignore").read()

    m = re.search(r"static const char s_demo_lrc\[\] =\n(?:.*?\n)*?.*?;\n", src, re.S)
    if not m:
        raise SystemExit("s_demo_lrc pattern not found")
    src = src[:m.start()] + "static const char s_demo_lrc[] =\n" + new_lrc + "\n" + src[m.end():]

    # 去掉进度条绘制（保留时间文本与变量声明兼容）
    pat = re.compile(
        r"\n\s*/\* 进度条：用演示歌词总长做分母.*?\n\s*if \(bar_w > 0u\) \{\n(?:.*?\n)*?\s*\}\n",
        re.S)
    if pat.search(src):
        src = pat.sub("\n    /* 进度条在 MDK-Lite 32KB 限制下省略，保留时间显示 */\n", src, count=1)
        print("progress bar removed")
    else:
        print("progress bar pattern NOT found, check manually")

    # bar_w 变量若已不用，去掉以免 warning
    src = src.replace("    uint32_t bar_w = 0;\n", "")

    open(p, "w", encoding="utf-8", newline="").write(src)
    print("lcd_ui.c updated, lyrics =", len(LYRICS))

    # 同步 gen_cn_font.py
    p2 = r"C:/stm32TEST/Tools/gen_cn_font.py"
    s2 = open(p2, encoding="utf-8").read()
    block = "DEMO_LYRICS = [\n" + "".join('    "%s",\n' % s for _, s in LYRICS) + "]\n"
    if re.search(r"DEMO_LYRICS = \[\n(?:.*?\n)*?\]\n", s2):
        s2 = re.sub(r"DEMO_LYRICS = \[\n(?:.*?\n)*?\]\n", block, s2, count=1)
        open(p2, "w", encoding="utf-8", newline="").write(s2)
        print("gen_cn_font.py synced")
    else:
        print("DEMO_LYRICS block not found in gen_cn_font.py")


if __name__ == "__main__":
    main()
