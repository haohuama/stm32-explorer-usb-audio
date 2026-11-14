#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二轮补丁：
   1) 键位按用户指定重排（KEY0=下一首 / KEY2=上一首 / KEY1=音量- / WK_UP=音量+）
   2) 音频质量：默认不再 10 倍增益；软膝限幅代替硬削波；按峰值自动归一（默认 -3dBFS）
两者都幂等。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def patch_text(path, pairs, marker=None):
    s = open(path, encoding="utf-8").read()
    if marker and marker in s:
        print("%s: 已打过补丁，跳过" % os.path.basename(path))
        return
    orig = s
    for old, new in pairs:
        if old not in s:
            print("  !! 未匹配: %r" % old[:60])
            continue
        s = s.replace(old, new, 1)
    if s == orig:
        print("%s: 没有改动" % os.path.basename(path))
        return
    open(path, "w", encoding="utf-8", newline="\n").write(s)
    print("%s: 已更新" % os.path.basename(path))


# ---------------- 1. 键位 ----------------
patch_text(os.path.join(ROOT, "User/Hardware/KEY/key.c"), [
    ("""#define MAP_KEY0      KEY_NEXT
#define MAP_KEY1      KEY_PREV
#define MAP_WKUP      KEY_VOL_UP
#define MAP_KEY2      KEY_VOL_DN""",
     """#define MAP_KEY0      KEY_NEXT
#define MAP_KEY1      KEY_VOL_DN
#define MAP_WKUP      KEY_VOL_UP
#define MAP_KEY2      KEY_PREV"""),
    (""" * 现在的分配：左右切歌用 KEY0/KEY1，上下加减音量用 WK_UP/KEY2。
 * 播放/暂停没有独立键位：**KEY0 长按 0.7 秒**（短按仍是下一首）。""",
     """ * 用户指定(2026-11-14)：KEY0=下一首 KEY2=上一首 KEY1=音量- WK_UP=音量+
 * 播放/暂停没有独立键位：**KEY0 长按 0.7 秒**（短按仍是下一首）。"""),
    # 松手触发短按的只有 KEY0；KEY1 现在改成音量键，按下即触发
    ("""                    if (i < 2u && !k->long_fired && evt == KEY_NONE) evt = map_event(i);""",
     """                    if (i == 0u && !k->long_fired && evt == KEY_NONE) evt = map_event(i);"""),
], marker="KEY_VOL_DN\n#define MAP_WKUP")

patch_text(os.path.join(ROOT, "User/Hardware/KEY/key.h"), [
    (""" * 默认映射（key.c 顶部 4 个 MAP_KEYx 宏可改）：
 *   KEY0 短按 = 下一首    KEY0 长按(0.7s) = 播放/暂停
 *   KEY1 短按 = 上一首    WK_UP = 音量+    KEY2 = 音量-""",
     """ * 用户指定映射（key.c 顶部 4 个 MAP_KEYx 宏可改）：
 *   KEY0 短按 = 下一首    KEY0 长按(0.7s) = 播放/暂停
 *   KEY2 短按 = 上一首    KEY1 = 音量-    WK_UP = 音量+"""),
])

patch_text(os.path.join(ROOT, "User/main.c"), [
    ("""    uart_puts("[7] KEY       : KEY0短按=下一首 / KEY0长按=播放暂停 / KEY1=上一首\\r\\n");
    uart_puts("              : WK_UP=音量+ / KEY2=音量-  (暂停需电脑端 --keys 在监听)\\r\\n");""",
     """    uart_puts("[7] KEY       : KEY0=下一首 / KEY2=上一首 / KEY1=音量- / WK_UP=音量+\\r\\n");
    uart_puts("              : KEY0长按0.7s=播放暂停 (需电脑端 --keys 在监听)\\r\\n");"""),
])

# ---------------- 2. 音频质量 ----------------
patch_text(os.path.join(ROOT, "Tools/host_cdc_sender.py"), [
    # 软膝限幅
    ('''def apply_gain(data, gain):
    """把 16bit 小端交错 PCM 字节按 gain 放大，并硬限幅到 int16 范围 [-32768,32767]，
    防止数值溢出回绕（回绕会产生刺耳爆音）。左右声道同倍数，立体声关系不变。"""
    a = array.array('h')
    a.frombytes(data)
    for i in range(len(a)):
        v = int(a[i] * gain)
        if v > 32767:
            v = 32767
        elif v < -32768:
            v = -32768
        a[i] = v
    return a.tobytes()''',
     '''KNEE = 0.70 * 32767.0          # 软膝起点：到这里开始平滑压缩
FS = 32767.0


def apply_gain(data, gain):
    """按 gain 放大 + **软膝限幅**（不是硬削波）。

    为什么改：以前是"超了就砍平"，满量程的流行歌被放大后大量样本贴顶，
    听感就是"炸/发毛"。现在超过 70% 满量程以后用 tanh 平滑逼近满量程，
    谐波少得多，声音仍有冲击力但不会破。
    左右声道同倍数、逐样本独立处理，立体声关系不变。"""
    import math
    a = array.array('h')
    a.frombytes(data)
    rng = FS - KNEE
    for i in range(len(a)):
        x = a[i] * gain
        ax = -x if x < 0 else x
        if ax > KNEE:
            y = KNEE + rng * math.tanh((ax - KNEE) / rng)
            x = -y if x < 0 else y
        a[i] = int(x)
    return a.tobytes()


def gain_for_peak(peak, target_db, base_gain=1.0, cap=4.0):
    """按源文件峰值算一个让峰值落在 target_db 的增益（默认 -3dBFS 留余量）。"""
    if peak <= 0:
        return base_gain
    tgt = 10.0 ** (target_db / 20.0) * 32767.0
    g = base_gain * tgt / float(peak)
    return min(g, cap)'''),
    # 默认增益
    ('    ap.add_argument("--gain", type=float, default=10.0,\n'
     '                    help="发送前音量增益倍数（默认 10.0；1.0=不处理；放大会硬限幅防爆音）")',
     '    ap.add_argument("--gain", type=float, default=1.0,\n'
     '                    help="额外音量倍数（默认 1.0）。以前默认 10 倍会把满量程歌直接削爆，已改")\n'
     '    ap.add_argument("--peak", type=float, default=-3.0,\n'
     '                    help="自动归一的目标峰值 dBFS（默认 -3，留余量不炸）；--no-norm 可关闭")\n'
     '    ap.add_argument("--no-norm", action="store_true", help="不做峰值归一，只按 --gain 处理")'),
    # 峰值提示 -> 计算每首的实际增益
    ('''    # ---- 峰值扫描 + 增益提示 ----
    for path in playlist:
        peak = scan_peak(path)
        print("源文件峰值: %s = %d (%.1f%% 满量程)" %
              (os.path.basename(path), peak, (peak / 32768.0 * 100.0)))
        # 仅在实际放大(gain>1)且会超顶时提示。
        # peak 可能为 32768（即 -32768 的绝对值），gain=1.0 时并未削波，不应误报。
        if args.gain > 1.0 and peak > 0 and peak * args.gain > 32767:
            print("  ⚠ 增益 %.2fx 会超过满量程→削波(可能失真)。建议 --gain %.2f。" %
                  (args.gain, 32767.0 / peak))
    print("增益: %.2fx   列表: %d 首   循环=%s   rate=%.3f   自动找口=%s   等待设备=%s" %
          (args.gain, len(playlist), not args.no_loop, args.rate, args.auto, args.wait), flush=True)''',
     '''    # ---- 峰值扫描 + 逐曲算增益（软膝限幅兜底）----
    args.gains = {}
    for path in playlist:
        peak = scan_peak(path)
        if args.no_norm:
            g = args.gain
        else:
            g = gain_for_peak(peak, args.peak, args.gain)
        args.gains[path] = g
        print("源文件峰值: %s = %d (%.1f%% 满量程) -> 实际增益 %.2fx%s" %
              (os.path.basename(path), peak, (peak / 32768.0 * 100.0), g,
               "" if args.no_norm else "  (归一峰值 %.1fdBFS)" % args.peak))
    print("增益: 见上   列表: %d 首   循环=%s   rate=%.3f   自动找口=%s   等待设备=%s" %
          (len(playlist), not args.no_loop, args.rate, args.auto, args.wait), flush=True)'''),
    # 逐曲增益 + 软膝
    ('''                if args.gain != 1.0:
                    data = apply_gain(data, args.gain)''',
     '''                g_now = getattr(args, "gains", {}).get(path, args.gain)
                if g_now != 1.0:
                    data = apply_gain(data, g_now)'''),
], marker="gain_for_peak")

print("done")
