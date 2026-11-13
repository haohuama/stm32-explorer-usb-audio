#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 .lrc 歌词转成工程可用的 C 数据 + 字库字符集。

支持两种混排格式（网易云导出的常见形式）：
  1) JSON 行:  {"t":37010,"c":[{"tx":"风到这里就是粘"}]}
  2) 标准行:   [00:37.010] 风到这里就是粘

产物：
  - 把歌词写进 lcd_ui.c 的 s_demo_lrc[]（GBK 字节转义，避免编码歧义）
  - 把歌词文本写进 Tools/gen_cn_font.py 的 DEMO_LYRICS（供重新生成字库）
  - 打印需要多少个汉字、Flash 估算

用法:
  python Tools/lrc_to_c.py "C:/Users/mhh20/Downloads/江南 - 林俊杰.lrc"
  python Tools/lrc_to_c.py xxx.lrc --dry-run     # 只统计不落盘
"""
import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UI_C = os.path.join(ROOT, "User/Hardware/LCD/lcd_ui.c")
GEN = os.path.join(ROOT, "Tools/gen_cn_font.py")

META_WORDS = ("作词", "作曲", "编曲", "制作人", "混音", "母带", "出品", "监制")


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def parse_lrc(text):
    """返回 [(ms, lyric_text), ...] 按时间排序。"""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        # 1) JSON 行
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except Exception:
                continue
            t = int(obj.get("t", 0))
            seg = obj.get("c") or []
            txt = "".join(s.get("tx", "") for s in seg if isinstance(s, dict))
            txt = txt.strip()
            if not txt or any(w in txt for w in META_WORDS):
                continue
            # 制作人员名单统一带冒号（"吉他: xxx"），歌词正文不会有
            if ":" in txt or "：" in txt:
                continue
            out.append((t, txt))
            continue
        # 2) 标准 [mm:ss.xx] 行（可能一行多个时间标签）
        stamps = re.findall(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]", line)
        if not stamps:
            continue
        # 文本 = 去掉所有时间标签
        body = re.sub(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]", "", line).strip()
        if not body or any(w in body for w in META_WORDS):
            continue
        # 末段的制作人员名单（"吉他: xxx" / "OP: xxx"）统一带冒号，歌词正文不会有
        if ":" in body or "：" in body:
            continue
        for mm, ss, frac in stamps:
            ms = int(mm) * 60000 + int(ss) * 1000
            if frac:
                ms += int(frac.ljust(3, "0")[:3])
            out.append((ms, body))
    out.sort(key=lambda x: x[0])
    return out


def ms_to_lrc(ms):
    m, r = divmod(ms, 60000)
    s, msec = divmod(r, 1000)
    return "%02d:%02d.%02d" % (m, s, msec // 10)


def gbk_escape(txt):
    b = txt.encode("gbk", "replace")
    return "".join("\\x%02X" % x for x in b)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    lrc_path = sys.argv[1]
    dry = "--dry-run" in sys.argv

    lines = parse_lrc(read_text(lrc_path))
    if not lines:
        print("没有解析出歌词行")
        return 3

    chars = set()
    for _, t in lines:
        for ch in t:
            if ord(ch) > 0x7F:
                chars.add(ch)
    print("歌词行数:", len(lines))
    print("时长(最后一行):", ms_to_lrc(lines[-1][0]))
    print("不重复汉字:", len(chars), "-> 16x16 字库", len(chars) * 32, "bytes")
    print("---- 前 8 行 ----")
    for ms, t in lines[:8]:
        print("  %s  %s" % (ms_to_lrc(ms), t))
    if dry:
        return 0

    # 1) 写 lcd_ui.c 的 s_demo_lrc
    src = open(UI_C, encoding="utf-8", errors="ignore").read()
    i = src.find("static const char s_demo_lrc[] =")
    j = src.find(";", i)
    body = []
    for ms, t in lines:
        body.append('    "[%s]%s\\n"' % (ms_to_lrc(ms), gbk_escape(t)))
    new = "static const char s_demo_lrc[] =\n" + "\n".join(body) + ";\n"
    src = src[:i] + new + src[j + 2:]
    open(UI_C, "w", encoding="utf-8", newline="").write(src)
    print("已写入 lcd_ui.c s_demo_lrc (%d 行)" % len(lines))

    # 2) 同步 gen_cn_font.py 的 DEMO_LYRICS
    g = open(GEN, encoding="utf-8").read()
    block = "DEMO_LYRICS = [\n" + "".join('    "%s",\n' % t.replace('"', '') for _, t in lines) + "]\n"
    g2 = re.sub(r"DEMO_LYRICS = \[\n(?:.*?\n)*?\]\n", block, g, count=1)
    if g2 == g:
        print("警告: 未能更新 gen_cn_font.py 的 DEMO_LYRICS（模式不匹配）")
    else:
        open(GEN, "w", encoding="utf-8", newline="").write(g2)
        print("已同步 gen_cn_font.py DEMO_LYRICS")
    print("下一步: py Tools/gen_cn_font.py && py Tools/check_font.py && py Tools/build_check.py --microlib")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
