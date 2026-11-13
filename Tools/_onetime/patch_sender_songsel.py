#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 host_cdc_sender.py 增加"按曲目序号通知设备"的能力（用 DTR/RTS，不占音频带宽）。

规则：从 WAV 文件名里取末尾数字作为曲目序号（pl01.wav -> 0，pl02.wav -> 1）；
取不到就用它在 -f 列表中的位置。设备端据此切换歌词并把歌词时钟清零。
"""
import re
import sys

P = r"C:/stm32TEST/Tools/host_cdc_sender.py"

HELPER = '''

def song_index_of(path, fallback):
    """从文件名末尾数字推断曲目序号(0 基)：pl01.wav -> 0, pl02.wav -> 1。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"(\\d+)\\s*$", stem)
    if m:
        try:
            return max(0, int(m.group(1)) - 1)
        except ValueError:
            pass
    return fallback


def select_song(ser, idx):
    """用串口控制线告诉设备"现在放第几首"：DTR=bit0，RTS 固定拉低。
    注意 RTS 必须为 0，否则 DTR|RTS = 3 会被设备当成"端口刚打开"的默认态忽略。
    该请求走 USB 控制端点，不占音频数据通道，也不会打断 PCM。"""
    try:
        ser.rts = False
        ser.dtr = bool(idx & 1)
    except Exception:
        pass
'''


def main():
    s = open(P, encoding="utf-8").read()
    if "def select_song(" in s:
        print("已存在 select_song，跳过")
        return 0

    # 1) 在 open_serial 之后插入两个工具函数
    anchor = "def stream_playlist(ser, playlist, args, eff_rate, gap_silence):"
    if anchor not in s:
        print("找不到 stream_playlist"); return 1
    s = s.replace(anchor, HELPER.strip() + "\n\n\n" + anchor, 1)

    # 2) 每首歌开始前通知设备
    old = '''            wf = wave.open(path, "rb")
            print("[%d/%d] 正在播放: %s" % (idx, len(playlist), os.path.basename(path)), flush=True)'''
    new = '''            wf = wave.open(path, "rb")
            print("[%d/%d] 正在播放: %s" % (idx, len(playlist), os.path.basename(path)), flush=True)
            # 通知 MCU 当前曲目序号（0 基）→ 切歌词 + 歌词时钟清零
            select_song(ser, song_index_of(path, idx - 1))'''
    if old not in s:
        print("找不到播放循环锚点"); return 1
    s = s.replace(old, new, 1)

    open(P, "w", encoding="utf-8", newline="").write(s)
    print("host_cdc_sender.py 已更新：逐曲 select_song()")
    return 0


if __name__ == "__main__":
    sys.exit(main())
