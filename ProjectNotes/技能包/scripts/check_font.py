#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验 lrc_data.h 里的歌词用字是否都被 cn_font.h 覆盖（防屏上出现空白方块）。

用法: python Tools/check_font.py
"""
import re
import sys

FONT = r"C:/stm32TEST/User/Hardware/LCD/cn_font.h"
DATA = r"C:/stm32TEST/User/Hardware/LCD/lrc_data.h"


def c_string_bytes(block):
    out = bytearray()
    i = 0
    while i < len(block):
        ch = block[i]
        if ch == "\\":
            nxt = block[i + 1]
            if nxt == "x":
                out.append(int(block[i + 2:i + 4], 16)); i += 4; continue
            if nxt == "n":
                out.append(0x0A); i += 2; continue
            if nxt == "r":
                out.append(0x0D); i += 2; continue
            if nxt == "\\":
                out.append(0x5C); i += 2; continue
            i += 2
            continue
        out.extend(ch.encode("gbk", "replace"))
        i += 1
    return bytes(out)


def font_chars():
    s = open(FONT, encoding="utf-8", errors="ignore").read()
    codes = set(int(m, 16) for m in re.findall(r"\{\s*0x([0-9A-Fa-f]{4})\s*,", s))
    got = set()
    for c in codes:
        try:
            got.add(bytes([c >> 8, c & 0xFF]).decode("gbk"))
        except Exception:
            pass
    return got


def main():
    have = font_chars()
    data = open(DATA, encoding="utf-8", errors="ignore").read()

    need = set()
    total_bytes = 0
    blocks = re.findall(r'static const char (s_\w+)\[\] =((?:\s*"[^"]*"\s*)+);', data)
    if not blocks:
        print("lrc_data.h 里没找到字符串数组"); return 2
    for name, body in blocks:
        body = body.replace("\n", "").replace("\r", "")
        raw = c_string_bytes(body.strip()[1:-1] if body.strip().startswith('"') else body)
        total_bytes += len(raw)
        txt = raw.decode("gbk", "replace")
        need |= set(ch for ch in txt if ord(ch) > 0x7F)
        if name.startswith("s_title"):
            print("%-9s: %s" % (name, txt))
        else:
            print("%-9s: %d 行, %d 字节" % (name, txt.count("\n"), len(raw)))

    miss = need - have
    print("\n字库汉字 %d 个；歌词/标题需要 %d 个；缺字: %s"
          % (len(have), len(need), ("".join(sorted(miss)) if miss else "无")))
    return 0 if not miss else 1


if __name__ == "__main__":
    sys.exit(main())
