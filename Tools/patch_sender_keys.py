#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""给 host_cdc_sender.py 加 --keys：接收板子按键发上来的 1 字节命令。"""
import os
import sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "Tools/host_cdc_sender.py")


def main():
    s = open(P, encoding="utf-8").read()
    if "KeyState" in s:
        print("已打过 --keys 补丁，跳过")
        return 0
    orig = s

    s = s.replace(
        "#   --meta-for    这些内容属于第几首（0 基，默认=第一个 WAV 的序号）",
        "#   --meta-for    这些内容属于第几首（0 基，默认=第一个 WAV 的序号）\n"
        "#   --keys        接收板子按键命令（KEY0 长按=播放/暂停，KEY0/1 短按=下一首/重播）")

    # 1) 线程 + 状态
    s = s.replace("def song_index_of(path, fallback):",
'''class KeyState(object):
    """板子按键 -> 电脑端动作。设备通过 CDC IN 端点发 1 字节：
       'P' 暂停 / 'R' 继续 / 'N' 下一首 / 'B' 重播当前这首。"""
    def __init__(self):
        import threading
        self.paused = False
        self.next_req = False
        self.rewind_req = False
        self._stop = False
        self._lock = threading.Lock()

    def start(self, ser):
        import threading
        self._th = threading.Thread(target=self._run, args=(ser,), daemon=True)
        self._th.start()

    def stop(self):
        self._stop = True

    def _run(self, ser):
        while not self._stop:
            try:
                c = ser.read(1)
            except Exception:
                return
            if not c:
                continue
            with self._lock:
                if c == b"P":
                    self.paused = True
                    print("\\n[KEY] 暂停", flush=True)
                elif c == b"R":
                    self.paused = False
                    print("\\n[KEY] 继续", flush=True)
                elif c == b"N":
                    self.next_req = True
                    print("\\n[KEY] 下一首", flush=True)
                elif c == b"B":
                    self.rewind_req = True
                    print("\\n[KEY] 重播当前曲", flush=True)

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
        with self._lock:
            n, r = self.next_req, self.rewind_req
            self.next_req = self.rewind_req = False
        return n, r


def song_index_of(path, fallback):''', 1)

    # 2) 参数
    s = s.replace('    ap.add_argument("--meta-for", type=int, default=None,',
                  '    ap.add_argument("--keys", action="store_true",\n'
                  '                    help="接收板子按键命令：长按 KEY0=播放/暂停，短按 KEY0/1=下一首/重播")\n'
                  '    ap.add_argument("--meta-for", type=int, default=None,', 1)

    # 3) 循环里处理暂停/切歌
    s = s.replace(
        "                data = wf.readframes(chunk_frames)",
        "                if key_state is not None:\n"
        "                    next_t += key_state.wait_if_paused()      # 暂停期间不推进发送进度\n"
        "                    _n, _r = key_state.take()\n"
        "                    if _r:\n"
        "                        wf.rewind()\n"
        "                        next_t = time.monotonic()\n"
        "                        continue\n"
        "                    if _n:\n"
        "                        break                                    # 跳出本曲 → for 进入下一首\n"
        "                data = wf.readframes(chunk_frames)", 1)

    # 4) 创建 KeyState
    s = s.replace("    meta_sent = False",
                  "    meta_sent = False\n"
                  "    key_state = None\n"
                  "    if getattr(args, 'keys', False):\n"
                  "        key_state = KeyState()\n"
                  "        key_state.start(ser)", 1)

    if s == orig:
        print("没有匹配到锚点，未修改")
        return 1
    open(P, "w", encoding="utf-8", newline="\n").write(s)
    print("已写入", P)
    return 0


if __name__ == "__main__":
    sys.exit(main())
