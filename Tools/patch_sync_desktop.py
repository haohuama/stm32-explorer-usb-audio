# -*- coding: utf-8 -*-
"""patch_sync_desktop.py —— 桌面软件：接收屏上切歌命令 + 下发歌词时间轴基准"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---------------------------------------------------------------- core_device.py
p = os.path.join(ROOT, "DesktopPlayer", "core_device.py")
s = io.open(p, encoding="utf-8").read()

s = s.replace(
    "T_SONG, T_LRC, T_LRC_END, T_COVER_ROW = 0x01, 0x02, 0x03, 0x04",
    "T_SONG, T_LRC, T_LRC_END, T_COVER_ROW, T_POS = 0x01, 0x02, 0x03, 0x04, 0x05")

s = s.replace(
    "import time\n\nimport serial",
    "import struct\nimport time\n\nimport serial")

a = """    def push_track(self, idx, title, artist, lrc_text=None, cover_path=None,
                   progress=None):
        \"\"\"一次把 元数据 + 歌词 + 封面 推到设备（自动进出控制模式）。\"\"\"
        self.enter_control()
        try:
            self.push_meta(idx, title, artist)
            if lrc_text:
                self.push_lrc(lrc_text)
            if cover_path:
                self.push_cover(cover_path, progress)
        finally:
            self.exit_control()"""
b = """    def push_track(self, idx, title, artist, lrc_text=None, cover_path=None,
                   progress=None, pos_ms=0):
        \"\"\"一次把 元数据 + 歌词 + 时间轴基准 + 封面 推到设备（自动进出控制模式）。

        pos_ms 必须是「已按倍速缩放」的时间：设备按收到的 PCM 字节计时（墙钟），
        而下发的 LRC 时间戳已除以倍速，两边同尺度才能严格同步。
        \"\"\"
        self.enter_control()
        try:
            self.push_meta(idx, title, artist)
            if lrc_text:
                self.push_lrc(lrc_text)
            self._frame(T_POS, struct.pack("<I", int(pos_ms) & 0xFFFFFFFF))
            if cover_path:
                self.push_cover(cover_path, progress)
        finally:
            self.exit_control()"""
assert a in s, "push_track 未找到"
s = s.replace(a, b, 1)

# 供命令读线程用
a = """    def write_pcm(self, data):
        self._need()
        self.ser.write(data)"""
b = """    def write_pcm(self, data):
        self._need()
        self.ser.write(data)

    def read_byte(self):
        \"\"\"读一个 CDC IN 字节；没数据返回 None（超时 50ms）。\"\"\"
        if not self.is_open:
            return None
        try:
            b = self.ser.read(1)
            return b[0] if b else None
        except Exception:
            return None"""
assert a in s
s = s.replace(a, b, 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("已写 core_device.py")

# ---------------------------------------------------------------- core_player.py
p = os.path.join(ROOT, "DesktopPlayer", "core_player.py")
s = io.open(p, encoding="utf-8").read()

# 启动命令读线程
a = """    def start(self):
        _boost_timer()
        if not self._ffmpeg:
            self.log("没找到 ffmpeg！导入 mp3 会失败（可设环境变量 FFMPEG）")
        self._th.start()"""
b = """    def start(self):
        _boost_timer()
        if not self._ffmpeg:
            self.log("没找到 ffmpeg！导入 mp3 会失败（可设环境变量 FFMPEG）")
        self._th.start()
        threading.Thread(target=self._cmd_loop, daemon=True).start()"""
assert a in s
s = s.replace(a, b, 1)

# 下发时间轴基准
a = """            lrc = T.scale_lrc(tr.lrc_text, self.speed) if tr.lrc_text else None
            self.device.push_track(slot, tr.title, tr.artist, lrc,
                                   tr.cover_path if with_cover else None)"""
b = """            lrc = T.scale_lrc(tr.lrc_text, self.speed) if tr.lrc_text else None
            # 设备按 PCM 字节计时（墙钟），LRC 时间戳已除以倍速 -> 基准同样要缩放
            pos_dev = int(base_ms / self.speed)
            self.device.push_track(slot, tr.title, tr.artist, lrc,
                                   tr.cover_path if with_cover else None,
                                   pos_ms=pos_dev)"""
assert a in s, "push_track 调用未找到"
s = s.replace(a, b, 1)

# 重连时也补推 POS（不带封面，快）
a = """                            if tr.lrc_text:
                                self.device.push_lrc(T.scale_lrc(tr.lrc_text, self.speed))
                        finally:"""
b = """                            if tr.lrc_text:
                                self.device.push_lrc(T.scale_lrc(tr.lrc_text, self.speed))
                            self.device._frame(0x05, struct.pack(
                                "<I", int(self._pos_ms / self.speed) & 0xFFFFFFFF))
                        finally:"""
assert a in s
s = s.replace(a, b, 1)
s = s.replace("import os\nimport threading", "import os\nimport struct\nimport threading")

# 命令读线程实现（插到 _run 之前）
a = "    def _run(self):\n        _boost_timer()"
b = '''    def _cmd_loop(self):
        """接收板子的 CDC 上行命令：屏上切歌 -> 桌面软件也换对应 WAV。

        'S'+idx  绝对切曲（屏上按键/触屏切歌时设备发）
        'P'/'R'  暂停/继续   'N'/'B'  下一首/上一首
        """
        want_idx = False
        while not self._stop.is_set():
            if not self.device.is_open:
                time.sleep(0.15)
                continue
            c = self.device.read_byte()
            if c is None:
                continue
            try:
                if want_idx:
                    want_idx = False
                    self.log("屏幕切到第 %d 首 -> 桌面换歌" % (c + 1))
                    self.play_index(c % max(1, len(self.tracks)),
                                    autoplay=(self.state == PLAYING))
                    continue
                if c == ord("S"):
                    want_idx = True
                elif c == ord("P"):
                    self.pause()
                elif c == ord("R"):
                    self.resume()
                elif c == ord("N"):
                    self.next()
                elif c == ord("B"):
                    self.prev()
            except Exception as e:
                self.log("命令处理异常：%s" % e)

''' + a
assert a in s
s = s.replace(a, b, 1)
io.open(p, "w", encoding="utf-8", newline="\n").write(s)
print("已写 core_player.py")
