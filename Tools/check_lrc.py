#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用与 lcd_ui.c 的 parse_lrc() 完全相同的规则，验证 lrc_data.h 能被正确解析。

防止"烧完发现屏上一片空"。用法: python Tools/check_lrc.py
"""
import re
import sys

DATA = r"C:/stm32TEST/User/Hardware/LCD/lrc_data.h"
MAX_LINES = 96


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


def parse_like_c(data):
    lines, p, n = [], 0, len(data)

    def strtoul(pos):
        start = pos
        while pos < n and 0x30 <= data[pos] <= 0x39:
            pos += 1
        return int(data[start:pos] or b"0"), pos

    while p < n and len(lines) < MAX_LINES:
        if data[p:p + 1] != b"[":
            p += 1
            continue
        mm, e = strtoul(p + 1)
        if e >= n or data[e:e + 1] != b":":
            p += 1
            continue
        ss, e = strtoul(e + 1)
        if e < n and data[e:e + 1] == b".":
            cc, e = strtoul(e + 1)
            cc = min(cc, 99)
        else:
            cc = 0
        if e >= n or data[e:e + 1] != b"]":
            p += 1
            continue
        e += 1
        stop = n
        for k in range(e, n):
            if data[k] in (0x0A, 0x0D):
                stop = k
                break
        lines.append(((mm * 60 + ss) * 1000 + cc * 10, data[e:stop]))
        nl = data.find(b"\n", e)
        p = (nl + 1) if nl >= 0 else n
    return lines


def main():
    s = open(DATA, encoding="utf-8", errors="ignore").read()
    blocks = re.findall(r'static const char (s_lrc\d)\[\] =((?:\s*"[^"]*"\s*)+);', s)
    if not blocks:
        print("lrc_data.h 里没有 s_lrcN"); return 2

    bad = 0
    for name, body in blocks:
        body = body.replace("\n", "").replace("\r", "")
        raw = c_string_bytes(body.strip()[1:-1] if body.strip().startswith('"') else body)
        lines = parse_like_c(raw)
        empty = sum(1 for _, t in lines if not t)
        print("== %s: %d 字节 -> 解析 %d 行, 空正文 %d" % (name, len(raw), len(lines), empty))
        if lines:
            for ms, t in lines[:2] + lines[-2:]:
                print("   %02d:%02d.%02d  %s" % (ms // 60000, ms // 1000 % 60, ms % 1000 // 10,
                                                 t.decode("gbk", "replace")))
        if empty or not lines:
            bad += 1
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
