# -*- coding: utf-8 -*-
"""让 host_cdc_sender.py 的发送节拍变精确。

问题：Windows 默认 time.sleep 粒度 15.6ms，而每批数据只需要 23.2ms，
      于是 sleep(23.2) 实际睡 31.2ms -> 之后一批立刻补发 -> 4KB 一涌。
      设备端 32KB 环形缓冲被这种「一停一涌」打得时干时满：
      干=欠载(爆点/间断)，满=丢最旧样本(咔哒) —— 这就是「音质炸」。

修法：
  1) winmm.timeBeginPeriod(1) 把系统定时器精度提到 1ms；
  2) sleep_until() 绝对时刻调度：粗睡 + 最后 2.5ms 自旋；
  3) 节拍计算改成「以已发送字节数为基准」，避免误差累积。

幂等：重复运行不会重复插入。
"""
import io
import os
import sys

P = os.path.join(os.path.dirname(os.path.abspath(__file__)), "host_cdc_sender.py")
s = io.open(P, encoding="utf-8").read()

if "def sleep_until(" in s:
    print("已经打过补丁，跳过")
    sys.exit(0)

# ---------- 1) 插入工具函数（放在 song_index_of 之前） ----------
anchor = "def song_index_of(path, fallback):"
helpers = '''def _boost_timer_resolution():
    """Windows：把系统定时器精度从 15.6ms 提到 1ms。

    USB 音频要每 23ms 送一批 4KB，15.6ms 的粒度会让实际间隔在
    23ms 和 31ms 之间跳变，直接把设备端环形缓冲打干/打满 -> 咔哒声。
    """
    try:
        import ctypes
        ctypes.windll.winmm.timeBeginPeriod(1)
        return True
    except Exception:
        return False


def sleep_until(t_end):
    """精确睡到绝对时刻 t_end（time.monotonic() 口径，单位秒）。

    前段用 sleep（省 CPU），最后 2.5ms 自旋（拿微秒级精度）。
    单次调用自旋 <=2.5ms，占空比约 10%，只用一个核。
    """
    while True:
        rem = t_end - time.monotonic()
        if rem <= 0.0:
            return
        if rem > 0.0035:
            time.sleep(rem - 0.0025)


'''
assert anchor in s, "找不到 song_index_of"
s = s.replace(anchor, helpers + anchor, 1)

# ---------- 2) 播放循环里的两处 sleep 换成 sleep_until ----------
old1 = """                next_t += len(data) / eff_rate
                dt = next_t - time.monotonic()
                if dt > 0:
                    time.sleep(dt)   # dt<=0 表示已落后，立即继续下一批追赶"""
new1 = """                next_t += len(data) / eff_rate
                # 绝对时刻调度：dt<=0 表示已落后，立即继续下一批追赶
                if next_t > time.monotonic():
                    sleep_until(next_t)"""
assert old1 in s, "找不到发送循环里的 sleep"
s = s.replace(old1, new1, 1)

old2 = """                next_t += len(gap_silence) / eff_rate
                gap_dt = next_t - time.monotonic()
                if gap_dt > 0:
                    time.sleep(gap_dt)"""
new2 = """                next_t += len(gap_silence) / eff_rate
                if next_t > time.monotonic():
                    sleep_until(next_t)"""
assert old2 in s, "找不到曲间静音的 sleep"
s = s.replace(old2, new2, 1)

# ---------- 3) main() 一开始就提精度 ----------
old3 = """def main():
    ap = argparse.ArgumentParser"""
new3 = """def main():
    _boost_timer_resolution()          # 1ms 定时器精度（治「炸」的关键一步）
    ap = argparse.ArgumentParser"""
assert old3 in s
s = s.replace(old3, new3, 1)

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("host_cdc_sender.py 节拍补丁完成")
