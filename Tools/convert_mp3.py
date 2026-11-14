#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""convert_mp3.py —— 把下载目录里的 mp3 批量转成「板子能吃」的格式

## 为什么需要这个
板子的 I2S 时钟固定按 **176400 B/s** 消费 PCM，只认：
    44.1kHz / 16bit / 立体声 / PCM WAV
mp3 是压缩格式，板子上没有解码器，**直接推 mp3 只会是噪音**。
host_cdc_sender.py 也明确只接受这种 WAV。

## 用法
    # 扫描默认下载目录，转换所有 mp3
    py Tools/convert_mp3.py

    # 指定目录
    py Tools/convert_mp3.py --src "C:/Users/mhh20/Downloads"

    # 只转换不配歌词 / 强制重新转
    py Tools/convert_mp3.py --no-lrc --force

    # 看看会做什么（不写文件）
    py Tools/convert_mp3.py --dry-run

## 产物
    Tools/mcu/plNN.wav       44.1k/16bit/立体声 PCM（板子可直接消费）
    Tools/mcu/plNN.lrc       配套歌词（清洗过：丢 JSON 头/版权行）
    Tools/mcu/manifest.json  清单（曲名/歌手/时长/文件）
"""
import argparse
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "DesktopPlayer"))

import core_mcu as M                                    # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "Tools", "mcu")
DEFAULT_SRC = os.path.join(os.path.expanduser("~"), "Downloads")

RE_TAG = re.compile(r"^\s*\[(\d{1,3}):(\d{2})(?:[.:](\d{1,3}))?\]\s*(.*)$")
CREDIT = ("制作人", "编曲", "出品", "作词", "作曲", "混音", "母带", "监制", "吉他", "和声",
          "本歌曲来自", "青云LAB", "网易云", "未经许可", "翻唱", "统筹", "企划", "营销",
          "录音", "混录", "母带后期", "后期制作", "和声编写", "吉他编写", "贝斯编写")


def clean_lrc(src, dst, title, artist):
    """清洗 LRC：丢 JSON 头 / 版权行 / 空行，时间统一成 mm:ss.xx。"""
    lines = []
    raw = open(src, "rb").read()
    text = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", "ignore")

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("{"):
            continue
        m = RE_TAG.match(line)
        if not m:
            continue
        body = m.group(4).strip()
        if not body:
            continue
        if any(k in body for k in CREDIT):
            continue
        if "：" in body or ":" in body:
            continue
        mm, ss, frac = m.group(1), m.group(2), (m.group(3) or "0")
        frac = (frac + "00")[:2] if len(frac) <= 2 else frac[:2]
        lines.append("[%s:%s.%s]%s" % (mm, ss, frac, body))

    head = ["[ti:%s]" % title, "[ar:%s]" % artist]
    with io.open(dst, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(head + lines) + "\n")
    return len(lines)


def main():
    ap = argparse.ArgumentParser(description="mp3 -> 板子格式批量转换")
    ap.add_argument("--src", default=DEFAULT_SRC, help="源目录（默认：下载目录）")
    ap.add_argument("--out", default=OUT_DIR, help="输出目录（默认：Tools/mcu）")
    ap.add_argument("--no-lrc", action="store_true", help="不处理歌词")
    ap.add_argument("--force", action="store_true", help="已存在也重新转")
    ap.add_argument("--dry-run", action="store_true", help="只列出，不写文件")
    ap.add_argument("--peak", type=float, default=-1.0,
                    help="峰值限制 dBFS，0 = 不限（默认 -1，给模拟端留余量）")
    ap.add_argument("--normalize", action="store_true", help="额外做响度归一")
    args = ap.parse_args()

    ffmpeg = M.find_ffmpeg()
    if not ffmpeg:
        print("[错误] 找不到 ffmpeg。设置环境变量 FFMPEG 指向 ffmpeg.exe 后重试。")
        return 2

    src_dir = os.path.abspath(args.src)
    if not os.path.isdir(src_dir):
        print("[错误] 源目录不存在：%s" % src_dir)
        return 2

    files = M.scan_audio(src_dir)
    if not files:
        print("源目录里没有音频文件：%s" % src_dir)
        return 1

    # 已有产物 -> 跳过（用 manifest 里的源文件路径判断）
    manifest_path = os.path.join(args.out, "manifest.json")
    done = {}
    if os.path.isfile(manifest_path):
        try:
            for it in json.load(open(manifest_path, encoding="utf-8")):
                done[it.get("src", "")] = it
        except Exception:
            done = {}

    if not args.dry_run and not os.path.isdir(args.out):
        os.makedirs(args.out)

    print("源目录 : %s" % src_dir)
    print("输出   : %s" % os.path.abspath(args.out))
    print("ffmpeg : %s" % ffmpeg)
    print("格式   : 44100Hz / 16bit / 立体声 / PCM（%d B/s）" % M.BYTES_PER_SEC)
    print("-" * 68)

    items = []
    ok_n = skip_n = fail_n = 0

    for i, src in enumerate(files, 1):
        title, artist = M.split_name(src)
        title = M.gbk_safe(title) or "歌曲"
        artist = M.gbk_safe(artist)
        stem = os.path.splitext(os.path.basename(src))[0]
        idx = i
        wav = os.path.join(args.out, "pl%02d.wav" % idx)

        prev = done.get(src)
        if prev and not args.force and os.path.isfile(prev.get("wav", "")):
            print("[%2d] 跳过（已转） %s" % (idx, os.path.basename(src)))
            items.append(prev)
            skip_n += 1
            continue

        if args.dry_run:
            print("[%2d] 将转换 %-42s -> pl%02d.wav  《%s》 %s"
                  % (idx, os.path.basename(src), idx, title, artist))
            continue

        try:
            M.to_mcu_wav(ffmpeg, src, wav, peak_db=args.peak, normalize=args.normalize)
            info = M.verify_mcu_wav(wav)
            if not info["ok"]:
                raise RuntimeError(info["reason"])
        except Exception as e:
            print("[%2d] 失败 %s：%s" % (idx, os.path.basename(src), e))
            fail_n += 1
            continue

        lrc_out = ""
        nlines = 0
        if not args.no_lrc:
            lrc_src = M.find_lrc(src_dir, stem)
            if lrc_src:
                lrc_out = os.path.join(args.out, "pl%02d.lrc" % idx)
                try:
                    nlines = clean_lrc(lrc_src, lrc_out, title, artist)
                except Exception as e:
                    print("     歌词处理失败：%s" % e)
                    lrc_out = ""

        size_mb = os.path.getsize(wav) / 1048576.0
        print("[%2d] OK  %-42s -> pl%02d.wav  %5.1fs  %5.1f MB  《%s》%s%s"
              % (idx, os.path.basename(src), idx, info["duration_ms"] / 1000.0,
                 size_mb, title, (" / " + artist) if artist else "",
                 ("  歌词 %d 行" % nlines) if lrc_out else ""))
        ok_n += 1
        items.append({
            "idx": idx,
            "src": src,
            "wav": wav,
            "lrc": lrc_out,
            "title": title,
            "artist": artist,
            "duration_ms": info["duration_ms"],
            "bytes": info["bytes"],
        })

    if not args.dry_run:
        with io.open(manifest_path, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(items, ensure_ascii=False, indent=2))
        print("-" * 68)
        print("清单已写入 %s" % manifest_path)
        print("共 %d 个：成功 %d / 跳过 %d / 失败 %d" % (len(items), ok_n, skip_n, fail_n))
        if ok_n:
            print("\n下一步：把 Tools/mcu/plNN.wav 拷到 Tools/ 下对应 plNN.wav，"
                  "再用 py Tools/host_cdc_sender.py --playlist 推流。")
    else:
        print("-" * 68)
        print("dry-run：共 %d 个文件待转换" % len(files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
