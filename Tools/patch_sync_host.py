# -*- coding: utf-8 -*-
"""patch_sync_host.py —— host_cdc_sender.py 支持设备的 'S'+idx 绝对切曲命令

原来 'B' 被解释成「重播当前曲」，和板上 KEY2=上一首 不一致；一并修正。
播放循环从 for-enumerate 改成 while + 显式索引，才能跳到任意曲目。
"""
import io
import os

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "Tools", "host_cdc_sender.py")
s = io.open(P, encoding="utf-8").read()

# ---------------------------------------------------------------- KeyState
a = s.index("class KeyState(object):")
b = s.index("def _boost_timer_resolution():")
new_key = '''class KeyState(object):
    """板子 -> 电脑的 CDC 上行命令。

      'P' 暂停 / 'R' 继续 / 'N' 下一首 / 'B' 上一首
      'S' + 1 字节 idx  = 屏上切到了第 idx 首（0 基），电脑要跳到对应 WAV。
       这条是「切到哪首歌词就唱哪首」的关键：以前屏上切歌只换歌词不换声音。
    """
    def __init__(self):
        import threading
        self.paused = False
        self.next_req = False
        self.prev_req = False
        self.abs_req = None
        self._stop = False
        self._lock = threading.Lock()

    def start(self, ser):
        import threading
        self._th = threading.Thread(target=self._run, args=(ser,), daemon=True)
        self._th.start()

    def stop(self):
        self._stop = True

    def _run(self, ser):
        want_idx = False
        while not self._stop:
            try:
                c = ser.read(1)
            except Exception:
                return
            if not c:
                continue
            with self._lock:
                if want_idx:
                    want_idx = False
                    self.abs_req = c[0]
                    print("\\n[KEY] 屏幕切到第 %d 首 -> 电脑换歌" % (c[0] + 1), flush=True)
                    continue
                if c == b"S":
                    want_idx = True
                elif c == b"P":
                    self.paused = True
                    print("\\n[KEY] 暂停", flush=True)
                elif c == b"R":
                    self.paused = False
                    print("\\n[KEY] 继续", flush=True)
                elif c == b"N":
                    self.next_req = True
                    print("\\n[KEY] 下一首", flush=True)
                elif c == b"B":
                    self.prev_req = True
                    print("\\n[KEY] 上一首", flush=True)

    def wait_if_paused(self):
        """暂停时挂起，返回暂停了多久（秒），供上层平移时间基准。"""
        import time
        if not self.paused:
            return 0.0
        t0 = time.monotonic()
        while self.paused and not self._stop:
            time.sleep(0.02)
        return time.monotonic() - t0

    def take(self):
        """-> (下一首, 上一首, 绝对索引或 None)"""
        with self._lock:
            n, p, a = self.next_req, self.prev_req, self.abs_req
            self.next_req = self.prev_req = False
            self.abs_req = None
        return n, p, a


'''
s = s[:a] + new_key + s[b:]

# ---------------------------------------------------------------- stream_playlist
a = s.index("def stream_playlist(ser, playlist, args, eff_rate, gap_silence):")
b = s.index("def main():")
new_loop = '''def stream_playlist(ser, playlist, args, eff_rate, gap_silence):
    """按列表播放；支持设备端 'S'+idx 跳到任意曲目（屏上切歌 -> 真的换 WAV）。

    绝对时间调度跨曲目连续；切歌插一小段静音防爆音。
    正常播完整个列表返回 True；异常时抛给外层重连。
    """
    chunk_frames = 1024  # 每次读 1024 帧 ≈ 23ms
    next_t = time.monotonic()
    meta_sent = False
    prefilled = False
    key_state = None
    if getattr(args, 'keys', False):
        key_state = KeyState()
        key_state.start(ser)

    n = len(playlist)
    cur = 0                       # 0 基当前曲目

    while True:
        path = playlist[cur]
        idx = cur + 1             # 打印用 1 基
        wf = wave.open(path, "rb")
        print("[%d/%d] 正在播放: %s" % (idx, n, os.path.basename(path)), flush=True)
        # 通知 MCU 当前曲目序号 -> 切歌词 + 歌词时钟清零（与音频同源，天然同步）
        si = song_index_of(path, cur)
        select_song(ser, si)
        if args.lrc or args.cover or args.title or args.artist:
            if (args.meta_for is None or si == args.meta_for) and not meta_sent:
                send_song_extras(ser, si, args.lrc, args.cover, args.title, args.artist)
                meta_sent = True
        if not prefilled:
            pf = float(getattr(args, "prefill", 0.0) or 0.0)
            if pf > 0.0:
                pre = wf.readframes(int(44100 * pf))
                if pre:
                    ser.write(pre)
                    next_t = time.monotonic()
                    print("  预灌 %.0fms 音频（%d 字节）" % (pf * 1000, len(pre)), flush=True)
            prefilled = True

        jump = None               # 本曲因为「切歌」提前结束时要去哪
        while True:
            if key_state is not None:
                next_t += key_state.wait_if_paused()   # 暂停期间不推进发送进度
                _n, _p, _a = key_state.take()
                if _a is not None:
                    jump = _a % n                      # 屏幕指定了绝对曲目
                    break
                if _p:
                    jump = (cur - 1) % n
                    break
                if _n:
                    jump = (cur + 1) % n
                    break
            data = wf.readframes(chunk_frames)
            if not data:
                break
            g_now = getattr(args, "gains", {}).get(path, args.gain)
            if g_now != 1.0:
                data = apply_gain(data, g_now)
            ser.write(data)
            next_t += len(data) / eff_rate
            if next_t > time.monotonic():
                sleep_until(next_t)
        wf.close()

        # 曲目之间插一小段静音：保持环形缓冲有数据，避免首尾样本直接拼接
        if gap_silence:
            ser.write(gap_silence)
            next_t += len(gap_silence) / eff_rate
            if next_t > time.monotonic():
                sleep_until(next_t)
        print("[%d/%d] 播放结束" % (idx, n), flush=True)

        if jump is not None:
            cur = jump
        else:
            cur = (cur + 1) % n
            if cur == 0 and args.no_loop:
                return True
            if cur == 0:
                print("---- 列表播完，回到第 1 首循环 ----", flush=True)


'''
s = s[:a] + new_loop + s[b:]

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("host_cdc_sender.py 已支持绝对切曲")
