#!/usr/bin/env python3
# 生成一个 44.1kHz / 16bit / 立体声 的测试 WAV（小星星第一句），用于验证音频链路。
# 用法： python gen_test_wav.py [输出文件名，默认 music.wav]
import wave, struct, math, sys, os

out = sys.argv[1] if len(sys.argv) > 1 else "music.wav"
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), out)

sr = 44100
# 小星星第一句: C C G G A A G
notes = [
    (523.25, 0.45), (523.25, 0.45),
    (783.99, 0.45), (783.99, 0.45),
    (880.00, 0.45), (880.00, 0.45),
    (783.99, 0.90),
]
amp = 0.22               # 幅度约 -13dBFS，避免刺耳/削顶
fade = int(sr * 0.010)   # 10ms 淡入淡出，避免爆音

frames = []
gap = b"\x00\x00\x00\x00" * int(sr * 0.04)   # 每音符间 40ms 静音
for freq, dur in notes:
    n = int(sr * dur)
    for i in range(n):
        env = 1.0
        if i < fade:
            env = i / fade
        elif i > n - fade:
            env = (n - i) / fade
        v = int(amp * env * math.sin(2 * math.pi * freq * i / sr) * 32767)
        frames.append(struct.pack('<hh', v, v))  # 左右相同
    frames.append(gap)

with wave.open(out, 'wb') as w:
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(sr)
    w.writeframes(b''.join(frames))

print("已生成:", out, " 时长约 %.2f 秒" % (len(b''.join(frames)) / (sr * 4)))
