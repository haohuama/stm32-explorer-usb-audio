#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 host_cdc_sender.py 打补丁：新增 --lrc/--cover/--title/--artist 的 USB 下发通道。"""
import os
import sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "Tools/host_cdc_sender.py")


def main():
    s = open(P, encoding="utf-8").read()
    if "send_song_extras" in s:
        print("已打过补丁，跳过")
        return 0
    orig = s

    # 1) 用法说明
    s = s.replace(
        "#   --playlist    直接用本工程 Tools/pl01.wav ... plNN.wav（按序号排序），免去逐个 -f",
        "#   --playlist    直接用本工程 Tools/pl01.wav ... plNN.wav（按序号排序），免去逐个 -f\n"
        "#   --lrc/--cover/--title/--artist\n"
        "#                 播放前把这些内容经同一条 USB 线下发给设备（换歌词/封面不用重烧固件）\n"
        "#   --meta-for    这些内容属于第几首（0 基，默认=第一个 WAV 的序号）")

    # 2) 控制通道实现
    block = '''CDC_CTRL_BAUD = 200000          # 与固件 cdc_ctrl.h 的 CDC_CTRL_BAUD 一致
FR_SONG, FR_LRC, FR_LRC_END, FR_COVER_ROW = 0x01, 0x02, 0x03, 0x04


def _frame(ser, ftype, payload):
    """ATK + type + len(LE16) + payload"""
    ser.write(b"ATK" + bytes([ftype, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF]) + payload)


def read_lrc_text(path):
    """自适应编码读文本（UTF-8/BOM/GBK 都试），后面统一转 GBK 发下去。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def send_song_extras(ser, song_idx, lrc_path=None, cover_path=None, title=None, artist=None):
    """控制模式下把 歌名/歌手 + 歌词 + 封面 发给设备。

    时序：波特率设成 200000 → 设备进控制模式 → 发帧 → 设回 115200 → 恢复 PCM。
    播放期间设备完全不解析帧，所以这条通道不影响音频链路。
    """
    ser.baudrate = CDC_CTRL_BAUD
    time.sleep(0.06)                      # 等 SET_LINE_CODING 生效

    t = (title or "").encode("gbk", "replace")[:40]
    a = (artist or "").encode("gbk", "replace")[:40]
    _frame(ser, FR_SONG, bytes([song_idx & 0xFF, len(t)]) + t + bytes([len(a)]) + a)

    if lrc_path and os.path.exists(lrc_path):
        data = read_lrc_text(lrc_path).encode("gbk", "replace")
        for i in range(0, len(data), 480):
            _frame(ser, FR_LRC, data[i:i + 480])
        _frame(ser, FR_LRC_END, b"")
        print("  已下发歌词 %d 字节 (%s)" % (len(data), os.path.basename(lrc_path)), flush=True)

    if cover_path and os.path.exists(cover_path):
        try:
            from PIL import Image
            im = Image.open(cover_path).convert("RGB")
            w, h = im.size
            s0 = min(w, h)
            im = im.crop(((w - s0) // 2, (h - s0) // 2,
                          (w - s0) // 2 + s0, (h - s0) // 2 + s0)).resize((240, 240))
            px = im.tobytes()
            for row in range(240):
                out = bytearray([row & 0xFF, row >> 8])
                base = row * 240 * 3
                for x in range(240):
                    r = px[base + x * 3]
                    g = px[base + x * 3 + 1]
                    b = px[base + x * 3 + 2]
                    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                    out += bytes([v & 0xFF, v >> 8])
                _frame(ser, FR_COVER_ROW, bytes(out))
                if row % 40 == 0:
                    time.sleep(0.005)     # 有硬件流控，这里只是保险
            print("  已下发封面 240x240 (%s)" % os.path.basename(cover_path), flush=True)
        except Exception as e:
            print("  封面上传失败:", e)

    ser.baudrate = 115200
    time.sleep(0.06)


def song_index_of(path, fallback):'''
    s = s.replace("def song_index_of(path, fallback):", block, 1)

    # 3) 命令行参数
    s = s.replace(
        '    ap.add_argument("--playlist", action="store_true",',
        '    ap.add_argument("--lrc", default=None, help="歌词文件，播放前经 USB 下发（不用重烧固件）")\n'
        '    ap.add_argument("--cover", default=None, help="封面图片 jpg/png/bmp，同上")\n'
        '    ap.add_argument("--title", default=None, help="下发的歌名（需 GBK 可编码）")\n'
        '    ap.add_argument("--artist", default=None, help="下发的歌手")\n'
        '    ap.add_argument("--meta-for", type=int, default=None,\n'
        '                    help="这些内容属于第几首（0 基）；默认=第一个 WAV 的序号")\n'
        '    ap.add_argument("--playlist", action="store_true",', 1)

    # 4) 每首发声前插入
    s = s.replace(
        "            # 通知 MCU 当前曲目序号（0 基）→ 切歌词 + 歌词时钟清零\n"
        "            select_song(ser, song_index_of(path, idx - 1))",
        "            # 通知 MCU 当前曲目序号（0 基）→ 切歌词 + 歌词时钟清零\n"
        "            si = song_index_of(path, idx - 1)\n"
        "            select_song(ser, si)\n"
        "            if args.lrc or args.cover or args.title or args.artist:\n"
        "                if (args.meta_for is None or si == args.meta_for) and not meta_sent:\n"
        "                    send_song_extras(ser, si, args.lrc, args.cover, args.title, args.artist)\n"
        "                    meta_sent = True", 1)

    s = s.replace(
        "    chunk_frames = 1024  # 每次读 1024 帧 ≈ 23ms\n"
        "    next_t = time.monotonic()",
        "    chunk_frames = 1024  # 每次读 1024 帧 ≈ 23ms\n"
        "    next_t = time.monotonic()\n"
        "    meta_sent = False", 1)

    if s == orig:
        print("没有匹配到任何锚点，未修改")
        return 1
    open(P, "w", encoding="utf-8", newline="\n").write(s)
    print("已写入", P)
    return 0


if __name__ == "__main__":
    sys.exit(main())
