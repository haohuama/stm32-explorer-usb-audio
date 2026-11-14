# -*- coding: utf-8 -*-
"""给 host_cdc_sender.py 加「开播预灌」，治欠载咔哒/发炸。

原理：
  设备端 DMA 从开机起一直按 44.1kHz 播，环形缓冲里没数据就补静音。
  上位机如果严格按实时速率送、且起始时环形是空的，那么上位机永远
  「刚好落后一点点」，任何一次 sleep 抖动（Windows 十几 ms）都会让
  环形见底 -> 补一小段静音 -> 听感就是咔哒/发毛/发炸。

  做法：开播瞬间先把 ~120ms 音频不按节拍地灌进去（环形 32KB≈185ms），
  之后照常按实时速率送。环形从此常驻 100ms 以上余量，抖动吃不穿。

幂等：重复运行不会重复插入。
"""
import io
import os
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host_cdc_sender.py")
s = io.open(P, encoding="utf-8").read()

if "prefilled" in s:
    print("已经打过预灌补丁，跳过")
    sys.exit(0)

# 1) 参数：--prefill
old_arg = '''    ap.add_argument("--playlist", action="store_true",'''
new_arg = '''    ap.add_argument("--prefill", type=float, default=0.12,
                    help="开播前不按节拍预灌多少秒音频进设备环形（0=关闭，默认 0.12）")
    ap.add_argument("--playlist", action="store_true",'''
assert old_arg in s
s = s.replace(old_arg, new_arg, 1)

# 2) 函数签名加 args 已有；在循环里加预灌标志
old_sig = '''    chunk_frames = 1024  # 每次读 1024 帧 ≈ 23ms
    next_t = time.monotonic()
    meta_sent = False'''
new_sig = '''    chunk_frames = 1024  # 每次读 1024 帧 ≈ 23ms
    next_t = time.monotonic()
    meta_sent = False
    prefilled = False'''
assert old_sig in s
s = s.replace(old_sig, new_sig, 1)

# 3) 进入本曲内层循环前预灌
old_in = '''            while True:
                if key_state is not None:'''
new_in = '''            if not prefilled:
                # 开播预灌：先用「不按节拍」的方式塞满一段，让环形有底
                pf = float(getattr(args, "prefill", 0.12) or 0.0)
                if pf > 0.0:
                    n_pf = int(44100 * pf) * 4          # 立体声 16bit = 4 字节/帧
                    pre = wf.readframes(int(44100 * pf))
                    if pre:
                        ser.write(pre)
                        next_t = time.monotonic()      # 从这里重新起算节拍
                        print("  预灌 %.0fms 音频（%d 字节）" % (pf * 1000, len(pre)),
                              flush=True)
                prefilled = True

            while True:
                if key_state is not None:'''
assert old_in in s
s = s.replace(old_in, new_in, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("预灌补丁完成")
