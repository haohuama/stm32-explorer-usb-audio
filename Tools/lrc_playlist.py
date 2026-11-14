#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 N 个 .lrc 生成 User/Hardware/LCD/lrc_data.h（播放列表 + 每首歌词）。

产物（每首一份）：
    s_title1[]  歌名（GBK 字节，屏上标题）
    s_artist1[] 歌手（GBK 字节，可为空 -> 屏上不画）
    s_dur1      时长 ms（由同名 Tools/plNN.wav 推算；无 wav 则为 0 -> 不画进度条）
    s_lrc1[]    歌词 "[mm:ss.xx]正文\\n"，正文内用 \\x01 分隔「原文」与「译文」

双语歌词（同一时间戳上有两行，如英文原词 + 中文翻译）会自动合并成一条：
    [00:00.41]Too many lonely days...\\x01太多的孤单时日...
屏上渲染为「原文一行 + 译文一行」，仍算同一条时间轴记录。

歌名/歌手来源优先级：[ti:]/[ar:] 标签 > 文件名 " - " 拆分。
文件名没有中文（英文歌）时，保留 ASCII 部分作为歌名。

同时把全部歌词写进 Tools/gen_cn_font.py 的 DEMO_LYRICS，
供 gen_cn_font.py 只渲染用到的汉字。

用法:
    python Tools/lrc_playlist.py Tools/lyrics/pl01.lrc ... Tools/lyrics/pl05.lrc
    python Tools/lrc_playlist.py --dry-run a.lrc b.lrc
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "User/Hardware/LCD/lrc_data.h")
GEN = os.path.join(ROOT, "Tools/gen_cn_font.py")
MAX_SONGS = 6          # 与 lcd_ui.c 的 SONG_COUNT 对应
MAX_TEXT = 95          # 与 lcd_ui.c 的 ui_line_t.text[96] 对应（字节，含 \\x01）
PAIR_MS = 80           # 同一时间戳的判定容差
SEP = "\x01"           # 原文 / 译文 分隔符（lcd_ui.c 里同值）

BYTES_PER_SEC = 176400         # 44100 * 2ch * 2byte
META_WORDS = ("作词", "作曲", "编曲", "制作人", "混音", "母带", "出品", "监制")


def read_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def read_tags(text):
    tags = {}
    for key, val in re.findall(r"^\[(ti|ar|al|by):(.*?)\]\s*$", text, re.M | re.I):
        tags[key.lower()] = val.strip()
    return tags


def parse_lrc(text):
    """返回 [(ms, 正文)]，已按时间升序。保留同一时间戳的多行（双语歌词）。"""
    import json
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("{"):
            try:
                obj = json.loads(line)
            except Exception:
                continue
            t = int(obj.get("t", 0))
            seg = obj.get("c") or []
            txt = "".join(s.get("tx", "") for s in seg if isinstance(s, dict)).strip()
            if not txt or any(w in txt for w in META_WORDS):
                continue
            if ":" in txt or "：" in txt:      # 制作人员行
                continue
            out.append((t, txt))
            continue
        stamps = re.findall(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]", line)
        if not stamps:
            continue
        body = re.sub(r"\[\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?\]", "", line).strip()
        if not body or any(w in body for w in META_WORDS):
            continue
        if ":" in body or "：" in body:
            continue
        if re.fullmatch(r"(VERSE|CHORUS|HOOK|BRIDGE|OUTRO|INTRO)\s*\d*", body, re.I):
            continue
        for mm, ss, frac in stamps:
            ms = int(mm) * 60000 + int(ss) * 1000
            if frac:
                ms += int(frac.ljust(3, "0")[:3])
            out.append((ms, body))
    out.sort(key=lambda x: x[0])
    return out


def cjk_count(s):
    return sum(1 for ch in s if ord(ch) > 0x7F)


def merge_pairs(entries):
    """把同一时间戳的两行合成 (ms, 原文, 译文)；单行则译为空。"""
    groups = []
    for ms, txt in entries:
        if groups and ms - groups[-1][0] < PAIR_MS:
            groups[-1][1].append(txt)
        else:
            groups.append((ms, [txt]))

    out = []
    for ms, texts in groups:
        if len(texts) == 1:
            out.append((ms, texts[0], ""))
            continue
        a, b = texts[0], texts[1]
        # 汉字多的那行当译文（英文原词 + 中文翻译的常见排版）
        if cjk_count(a) > cjk_count(b):
            a, b = b, a
        out.append((ms, a, b))
    return out


def trunc_gbk(s, limit):
    """按 GBK 字节数截断，且不切断双字节汉字。"""
    out, used = [], 0
    for ch in s:
        n = len(ch.encode("gbk", "replace"))
        if used + n > limit:
            break
        out.append(ch)
        used += n
    return "".join(out)


def ms_to_lrc(ms):
    m, r = divmod(ms, 60000)
    s, msec = divmod(r, 1000)
    return "%02d:%02d.%02d" % (m, s, msec // 10)


def gbk_escape(txt):
    return "".join("\\x%02X" % b for b in txt.encode("gbk", "replace"))


def split_name(path):
    """从 [ti:]/[ar:] 或文件名得到 (歌名, 歌手)。英文歌名保留 ASCII 原文。"""
    text = read_text(path)
    tags = read_tags(text)
    base = os.path.splitext(os.path.basename(path))[0]
    head, _, tail = base.partition(" - ")

    title = tags.get("ti") or head.strip()
    artist = tags.get("ar") or tail.strip()

    def gbk_safe(s):
        while s:
            try:
                s.encode("gbk")
                return s
            except UnicodeEncodeError:
                s = s[:-1]
        return ""

    title = gbk_safe(title) or "歌曲"
    return title, gbk_safe(artist)


def wav_duration_ms(idx):
    """Tools/plNN.wav（与曲目序号对应）的时长；没有该文件返回 0。"""
    p = os.path.join(ROOT, "Tools", "pl%02d.wav" % idx)
    if not os.path.exists(p):
        return 0
    return int((os.path.getsize(p) - 44) * 1000 / BYTES_PER_SEC)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    if not args:
        print(__doc__)
        return 2
    if len(args) > MAX_SONGS:
        print("最多 %d 首（与 lcd_ui.c 的 SONG_COUNT 一致）" % MAX_SONGS)
        return 2

    songs = []
    for p in args:
        entries = parse_lrc(read_text(p))
        if not entries:
            print("解析失败:", p)
            return 3
        title, artist = split_name(p)
        merged = merge_pairs(entries)
        songs.append((title, artist, merged))
        chars = set(ch for _, a, b in merged for ch in (a + b) if ord(ch) > 0x7F)
        chars |= set(ch for ch in title + artist if ord(ch) > 0x7F)
        print("%s -> 《%s》/ %s : %d 行 -> %d 条, %d 汉字, 末行 %s"
              % (os.path.basename(p), title, artist or "-", len(entries),
                 len(merged), len(chars), ms_to_lrc(merged[-1][0])))

    total_chars = set()
    for title, artist, merged in songs:
        for _, a, b in merged:
            total_chars |= set(ch for ch in (a + b) if ord(ch) > 0x7F)
        total_chars |= set(ch for ch in title + artist if ord(ch) > 0x7F)
    print("并集汉字 %d 个 -> 16x16 字库 %.1f KB"
          % (len(total_chars), len(total_chars) * 32 / 1024.0))

    if dry:
        return 0

    # ---------- 生成 lrc_data.h ----------
    buf = ["/* Auto-generated by Tools/lrc_playlist.py -- DO NOT EDIT.",
           " * 播放列表歌词数据：每首一个 [mm:ss.xx] + GBK 字节流。",
           " * 正文里的 \\x01 分隔「原文」与「译文」（双语歌词），渲染时另起一行。",
           " * 中文一律 \\xNN 转义，避免源文件编码歧义。",
           " */",
           "#ifndef __LRC_DATA_H",
           "#define __LRC_DATA_H",
           "",
           "#include <stdint.h>",
           ""]
    for i, (title, artist, merged) in enumerate(songs, 1):
        dur = wav_duration_ms(i)
        buf.append("/* ---- 第 %d 首：%s%s ---- */"
                   % (i, title, (" / " + artist) if artist else ""))
        buf.append('static const char s_title%d[] = "%s";' % (i, gbk_escape(title)))
        buf.append('static const char s_artist%d[] = "%s";' % (i, gbk_escape(artist)))
        buf.append("static const uint32_t s_dur%d = %du;   /* ms，来自 Tools/pl%02d.wav */"
                   % (i, dur, i))
        buf.append("static const char s_lrc%d[] =" % i)
        body = []
        for ms, orig, trans in merged:
            txt = orig + (SEP + trans if trans else "")
            body.append('    "[%s]%s\\n"' % (ms_to_lrc(ms), gbk_escape(trunc_gbk(txt, MAX_TEXT))))
        buf.append("\n".join(body) + ";")
        buf.append("")
    # 补齐：lcd_ui.c 固定引用到 SONG_COUNT
    for i in range(len(songs) + 1, MAX_SONGS + 1):
        buf.append("/* ---- 第 %d 首：未使用 ---- */" % i)
        buf.append('static const char s_title%d[] = "";' % i)
        buf.append('static const char s_artist%d[] = "";' % i)
        buf.append("static const uint32_t s_dur%d = 0u;" % i)
        buf.append('static const char s_lrc%d[] = "";' % i)
        buf.append("")
    buf.append("#endif /* __LRC_DATA_H */")
    open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(buf) + "\n")
    print("已生成", OUT)

    # ---------- 同步 gen_cn_font.py ----------
    all_lines = []
    for title, artist, merged in songs:
        all_lines.append(title)
        if artist:
            all_lines.append(artist)
        for _, a, b in merged:
            all_lines.append(a)
            if b:
                all_lines.append(b)
    block = "DEMO_LYRICS = [\n" + "".join('    "%s",\n' % s.replace('"', "").replace(SEP, " ")
                                          for s in all_lines) + "]\n"
    g = open(GEN, encoding="utf-8").read()
    g2 = re.sub(r"DEMO_LYRICS = \[\n(?:.*?\n)*?\]\n", block, g, count=1)
    if g2 == g:
        print("警告: gen_cn_font.py 的 DEMO_LYRICS 未更新")
    else:
        open(GEN, "w", encoding="utf-8", newline="").write(g2)
        print("已同步 gen_cn_font.py DEMO_LYRICS（%d 行）" % len(all_lines))

    print("下一步: py Tools/gen_cn_font.py && py Tools/check_font.py && py Tools/check_lrc.py"
          " && py Tools/build_check.py --microlib")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
