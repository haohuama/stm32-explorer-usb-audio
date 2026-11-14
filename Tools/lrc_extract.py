#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 User/Hardware/LCD/lrc_data.h 反向还原成 .lrc 源文件（Tools/lyrics/plNN.lrc）。

用途：歌词源文件丢失时，从固件里已生成的歌词表恢复到可编辑的 .lrc，
之后仍用 Tools/lrc_playlist.py 重生成。生成的 .lrc 为 UTF-8 + LF，
并带 [ti:歌名] / [ar:歌手] 标签（lrc_playlist.py 会优先读标签）。

用法: python Tools/lrc_extract.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "User/Hardware/LCD/lrc_data.h")
DST = os.path.join(ROOT, "Tools/lyrics")


def unescape(s):
    """把 C 字符串里的 \\xNN / \\n / \\\\ 还原成文本（字节按 GBK 解释）。"""
    out = bytearray()
    i = 0
    while i < len(s):
        ch = s[i]
        if ch == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "x":
                out.append(int(s[i + 2:i + 4], 16))
                i += 4
                continue
            if nxt == "n":
                out.append(0x0A)
                i += 2
                continue
            if nxt == "r":
                out.append(0x0D)
                i += 2
                continue
            out.extend(nxt.encode("gbk", "replace"))
            i += 2
            continue
        out.extend(ch.encode("gbk", "replace"))
        i += 1
    return bytes(out).decode("gbk", "replace")


def main():
    src = open(SRC, encoding="utf-8", errors="ignore").read()
    os.makedirs(DST, exist_ok=True)
    n = 1
    while True:
        m = re.search(r'static const char s_lrc%d\[\] =\n(.*?)";' % n, src, re.S)
        if not m:
            break
        mt = re.search(r'static const char s_title%d\[\] = "(.*?)";' % n, src)
        ma = re.search(r'static const char s_artist%d\[\] = "(.*?)";' % n, src)
        title = unescape(mt.group(1)) if mt else ""
        artist = unescape(ma.group(1)) if ma else ""
        rows = [unescape(r) for r in re.findall(r'"(.*)"', m.group(1))]
        path = os.path.join(DST, "pl%02d.lrc" % n)
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            if title:
                f.write("[ti:%s]\n" % title)
            if artist:
                f.write("[ar:%s]\n" % artist)
            f.write("\n".join(rows) + "\n")
        print(path, title or "-", len(rows), "行")
        n += 1
    if n == 1:
        print("未在 lrc_data.h 里找到 s_lrc1")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
