# -*- coding: utf-8 -*-
"""清洗歌词：
1) 新的那首「忘不掉的你」是网易格式（前面几行是 {"t":...,"c":[...]} 的 JSON），
   只保留 [mm:ss.xx]正文，丢掉 JSON、空行和「制作人/编曲/出品」这类版权行。
2) 第 5 首英文歌按用户要求**去掉中文翻译**：只保留英文行，
   这样一句能占满 40px 大字，不再因为挤两行中文变小号马赛克。
"""
import io
import os
import re

RE_TAG = re.compile(r"^\s*\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)$")
ZH = re.compile(r"[\u4e00-\u9fff]")
CREDIT = ("制作人", "编曲", "出品", "作词", "作曲", "混音", "母带", "监制", "吉他", "和声",
          "本歌曲来自", "青云LAB", "网易云", "未经许可", "翻唱")

OUT_DIR = "Tools/lyrics"


def clean_new(src, dst, title, artist):
    lines_out = []
    with io.open(src, encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("{"):
                continue                      # JSON 元数据
            m = RE_TAG.match(line)
            if not m:
                continue
            text = m.group(4).strip()
            if not text:
                continue
            if any(k in text for k in CREDIT):
                continue
            if "：" in text or ":" in text:
                continue                      # 版权行常见「统筹：xxx」格式
            # 时间统一成 mm:ss.xx
            mm, ss, frac = m.group(1), m.group(2), (m.group(3) or "0")
            frac = (frac + "00")[:2] if len(frac) <= 2 else frac[:2]
            lines_out.append("[%s:%s.%s]%s" % (mm, ss, frac, text))

    head = ["[ti:%s]" % title, "[ar:%s]" % artist]
    with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(head + lines_out) + "\n")
    print("%s -> %d 行" % (os.path.basename(dst), len(lines_out)))


def strip_chinese(src, dst):
    """英文歌去中文翻译：只留不含汉字的行（[ti:]/[ar:] 也保留）。"""
    out, removed = [], 0
    with io.open(src, encoding="utf-8") as f:
        for raw in f:
            line = raw.rstrip("\n")
            s = line.strip()
            if not s:
                continue
            if s.startswith("[ti:") or s.startswith("[ar:"):
                out.append(s)
                continue
            m = RE_TAG.match(s)
            if not m:
                continue
            text = m.group(4).strip()
            if not text:
                continue
            if ZH.search(text):
                removed += 1
                continue
            out.append(s)
    with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(out) + "\n")
    print("%s 去中文：删 %d 行，剩 %d 行" % (os.path.basename(dst), removed, len(out)))


if __name__ == "__main__":
    clean_new(r"C:/Users/mhh20/Downloads/忘不掉的你 - h3R3.lrc",
              os.path.join(OUT_DIR, "pl06.lrc"), "忘不掉的你", "h3R3")
    strip_chinese(os.path.join(OUT_DIR, "pl05.lrc"),
                  os.path.join(OUT_DIR, "pl05_single.lrc"))
