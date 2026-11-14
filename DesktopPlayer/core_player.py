# -*- coding: utf-8 -*-
"""core_player.py —— 播放引擎（后台线程）

设备端 I2S 时钟固定，只能以 176400 B/s 吃数据：
  * 停发  = 环形缓冲排空 = 静音（这就是「暂停」）
  * 发慢  = 每个 DMA 半区补静音 = 咔咔断续
  * 发快  = 环形溢出丢样本 = 咔哒
所以速率永远 176400 B/s；「倍速」在 ffmpeg 里做（core_track.render_segment），
出口仍是 44.1k，字节率不变。发送用绝对时刻调度 + timeBeginPeriod(1)，
否则 Windows 15.6ms 的 sleep 粒度会把 23ms 的节拍打成 31ms。
"""
import ctypes
import os
import struct
import threading
import time
import wave
from array import array

import core_track as T
from core_device import (Device, DeviceError, find_port, port_conflicts,
                         kill_port_conflicts)

BYTES_PER_SEC = T.BYTES_PER_SEC
CHUNK = 4096                      # 23.2ms
SLOT_COUNT = 6                    # 设备端内置曲目槽位数（lcd_ui.c SONG_COUNT）

STOPPED, PLAYING, PAUSED = "stopped", "playing", "paused"


def _boost_timer():
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
    except Exception:
        pass


def sleep_until(t_end):
    while True:
        rem = t_end - time.monotonic()
        if rem <= 0:
            return
        if rem > 0.0035:
            time.sleep(rem - 0.0025)


def apply_gain(data, g):
    """数字音量：16bit 就地缩放 + 饱和。g=1.0 直接原样返回（零开销）。"""
    if abs(g - 1.0) < 1e-3:
        return data
    a = array("h")
    a.frombytes(data)
    hi, lo = 32767, -32768
    for i in range(len(a)):
        v = int(a[i] * g)
        a[i] = hi if v > hi else (lo if v < lo else v)
    return a.tobytes()


class Player(object):
    def __init__(self, on_log=None, on_track_changed=None):
        self.tracks = []
        self.index = -1
        self.state = STOPPED
        self.speed = 1.0
        self.keep_pitch = True          # True = 变速不变调（atempo）
        self.volume = 0.38        # 与固件 38/100 对齐
        self.device = Device()
        self.port_name = ""
        self.lrc_lines = []
        self._pos_ms = 0
        self._dur_ms = 0
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._need_prepare = True
        self._want_cover = False
        self._msg = ""
        self._ffmpeg = T.find_ffmpeg()
        self._fh = None                  # wave handle
        self._tmp_wav = None
        self._base_ms = 0                # 当前渲染段对应的歌曲时间
        self._sent = 0                   # 本段已发字节
        self._next_t = 0.0
        self._on_log = on_log
        self._on_track = on_track_changed
        self._th = threading.Thread(target=self._run, daemon=True)

    # ---------------------------------------------------------- 生命周期
    def start(self):
        _boost_timer()
        if not self._ffmpeg:
            self.log("没找到 ffmpeg！导入 mp3 会失败（可设环境变量 FFMPEG）")
        self._th.start()
        threading.Thread(target=self._cmd_loop, daemon=True).start()

    def shutdown(self):
        self._stop.set()
        self._wake.set()
        self._close_stream()
        self.device.close()

    def log(self, s):
        self._msg = s
        if self._on_log:
            try:
                self._on_log(s)
            except Exception:
                pass

    # ---------------------------------------------------------- 只读状态
    @property
    def status(self):
        return self._msg

    @property
    def pos_ms(self):
        return self._pos_ms

    @property
    def duration_ms(self):
        return self._dur_ms

    @property
    def track(self):
        return self.tracks[self.index] if 0 <= self.index < len(self.tracks) else None

    # ---------------------------------------------------------- 控制
    def set_tracks(self, tracks):
        self.tracks = list(tracks)
        if self.index >= len(self.tracks):
            self.index = len(self.tracks) - 1

    def play_index(self, i, autoplay=True):
        if not (0 <= i < len(self.tracks)):
            return
        self.index = i
        tr = self.tracks[i]
        with self._lock:
            self._pos_ms = 0
            self._dur_ms = tr.duration_ms
            self.lrc_lines = tr.lines()
        self._base_ms = 0                 # 换曲必须把渲染起点清零，否则从上一首的 seek 位置开始
        self._close_stream()
        self._need_prepare = True
        self._want_cover = True
        if autoplay:
            self.state = PLAYING
        if self._on_track:
            try:
                self._on_track(i)
            except Exception:
                pass
        self._wake.set()

    def toggle(self):
        if self.state == PLAYING:
            self.pause()
        else:
            self.resume()

    def pause(self):
        if self.state == PLAYING:
            self.state = PAUSED
            self.log("已暂停（停止发送 PCM，设备自动静音）")

    def resume(self):
        if self.track is None:
            return
        if self.state in (PAUSED, STOPPED):
            self.state = PLAYING
            self._wake.set()
            self.log("播放中")

    def next(self):
        if self.tracks:
            self.play_index((self.index + 1) % len(self.tracks))

    def prev(self):
        if self.tracks:
            self.play_index((self.index - 1) % len(self.tracks))

    def seek(self, ms):
        with self._lock:
            self._pos_ms = max(0, min(ms, max(0, self._dur_ms - 200)))
            base = self._pos_ms
        self._close_stream()
        self._base_ms = base
        self._need_prepare = True
        self._wake.set()

    def set_speed(self, speed, keep_pitch=None):
        speed = max(0.5, min(2.0, float(speed)))
        if abs(speed - self.speed) < 1e-3 and (keep_pitch is None or keep_pitch == self.keep_pitch):
            return
        self.speed = speed
        if keep_pitch is not None:
            self.keep_pitch = bool(keep_pitch)
        # 重新渲染：保持当前歌曲位置
        self._close_stream()
        self._base_ms = self._pos_ms
        self._need_prepare = True
        self.log("倍速 %.2fx（%s）重新转码中…" % (self.speed, "不变调" if self.keep_pitch else "变调"))
        self._wake.set()

    # ---------------------------------------------------------- 内部
    def _close_stream(self):
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
        if self._tmp_wav:
            try:
                os.remove(self._tmp_wav)
            except OSError:
                pass
            self._tmp_wav = None

    def _prepare(self):
        """渲染当前段 + 把 元数据/歌词/封面 推给设备。"""
        tr = self.track
        if tr is None:
            self.state = STOPPED
            self._need_prepare = False
            return
        if not self._ffmpeg:
            self.log("没有 ffmpeg，无法解码")
            self.state = STOPPED
            self._need_prepare = False
            return

        base = self._base_ms
        self.log("正在转码…（从 %s，%.2fx）" % (self._fmt(base), self.speed))
        t0 = time.monotonic()
        try:
            path = T.render_segment(self._ffmpeg, tr.path, base,
                                    self.speed, self.keep_pitch)
        except Exception as e:
            self.log("转码失败：%s" % e)
            self.state = STOPPED
            self._need_prepare = False
            return
        self._tmp_wav = path
        self._fh = T.open_wav(path)
        self._sent = 0
        self._next_t = time.monotonic()
        self._need_prepare = False
        self.log("转码完成 %.1fs，开始播放" % (time.monotonic() - t0))

        self._push_to_device(tr, with_cover=self._want_cover, base_ms=base)
        self._want_cover = False

    def _push_to_device(self, tr, with_cover=False, base_ms=0):
        """把 歌名/歌手/歌词/封面 送到设备（失败只记日志，不影响放音）。"""
        try:
            if not self.device.is_open:
                name = self.device.open(self.port_name or None)
                self.port_name = name
                self.log("已连接 %s" % name)
            slot = self.index % SLOT_COUNT
            # 先让设备切槽（同时清零它的歌词时钟）
            self.device.select_slot(slot)
            lrc = T.scale_lrc(tr.lrc_text, self.speed) if tr.lrc_text else None
            # 设备按 PCM 字节计时（墙钟），LRC 时间戳已除以倍速 -> 基准同样要缩放
            pos_dev = int(base_ms / self.speed)
            self.device.push_track(slot, tr.title, tr.artist, lrc,
                                   tr.cover_path if with_cover else None,
                                   pos_ms=pos_dev)
            self.log("已同步到屏幕：%s%s" % (tr.title, "（含封面）" if with_cover else ""))
        except DeviceError as e:
            self.device.close()
            self.log("设备未连接/串口被占用：%s（%s）" % (e, self._busy_hint()))
        except Exception as e:
            self.device.close()
            self.log("推送元数据失败：%s" % e)

    @staticmethod
    def _busy_hint():
        """打不开串口时把「谁占着」说清楚，别只丢一句 PermissionError。"""
        c = port_conflicts()
        if not c:
            return "没发现旧推流脚本；检查串口调试助手或第二个播放器"
        return ("被 PID %s 的旧推流脚本占用 → 点顶部「释放串口」"
                % ", ".join(str(pid) for pid, _ in c))

    def release_port(self):
        """结束占用 CDC 口的旧推流脚本；播放线程下一轮会自动重连。"""
        killed = kill_port_conflicts()
        self.device.close()
        self._wake.set()
        return killed

    def _reconnect(self):
        self.device.close()
        for _ in range(2):
            if self._stop.is_set():
                return False
            name = find_port()
            if name:
                try:
                    self.device.open(name)
                    self.port_name = name
                    self.log("设备已重连 %s" % name)
                    tr = self.track
                    if tr is not None:
                        # 设备可能复位丢了歌词：补推一次（不带封面，快）
                        self.device.enter_control()
                        try:
                            self.device.push_meta(self.index % SLOT_COUNT, tr.title, tr.artist)
                            if tr.lrc_text:
                                self.device.push_lrc(T.scale_lrc(tr.lrc_text, self.speed))
                            self.device._frame(0x05, struct.pack(
                                "<I", int(self._pos_ms / self.speed) & 0xFFFFFFFF))
                        finally:
                            self.device.exit_control()
                    self._next_t = time.monotonic()
                    return True
                except Exception as e:
                    self.log("重连失败：%s（%s）" % (e, self._busy_hint()))
            time.sleep(0.8)
        return False

    @staticmethod
    def _fmt(ms):
        ms = max(0, int(ms))
        return "%02d:%02d" % (ms // 60000, (ms % 60000) // 1000)

    def _advance_to_next(self):
        if len(self.tracks) <= 1:
            self.seek(0)
            self._wake.set()
            return
        self.play_index((self.index + 1) % len(self.tracks), autoplay=(self.state == PLAYING))

    def _cmd_loop(self):
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

    def _run(self):
        _boost_timer()
        while not self._stop.is_set():
            try:
                if self.state != PLAYING:
                    self._wake.wait(0.05)
                    self._wake.clear()
                    self._next_t = time.monotonic()
                    continue
                if self._need_prepare or self._fh is None:
                    self._prepare()
                    continue

                data = self._fh.readframes(CHUNK // 4)      # 4 字节/帧
                if not data:
                    self.log("本曲结束")
                    self._advance_to_next()
                    continue

                out = apply_gain(data, self.volume)
                try:
                    if not self.device.is_open:
                        if not self._reconnect():
                            time.sleep(0.5)
                            continue
                    self.device.write_pcm(out)
                except DeviceError:
                    self.log("写入失败（设备掉线？）重连中…")
                    self._reconnect()
                    continue

                self._sent += len(out)
                with self._lock:
                    self._pos_ms = int(self._base_ms + self._sent * 1000.0
                                       * self.speed / BYTES_PER_SEC)

                self._next_t += len(out) / float(BYTES_PER_SEC)
                if self._next_t > time.monotonic():
                    sleep_until(self._next_t)
            except Exception as e:
                self.log("播放线程异常：%s" % e)
                time.sleep(0.3)
