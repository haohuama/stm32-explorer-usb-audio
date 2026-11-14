# -*- coding: utf-8 -*-
"""core_device.py —— 板子这一侧的 USB CDC 通道

三种"模式"都是靠 CDC_SET_LINE_CODING 的波特率字段编码（0 字节音频开销）：

  115200           普通模式：OUT 数据 = PCM
  100000 + n       选曲：设备切到第 n 首（n < 16）
  200000           控制模式：OUT 数据 = 控制帧（歌名/歌词/封面）

控制帧（小端）： 'A''T''K' | type | len_lo len_hi | payload
  0x01 SONG      : idx, tlen, title[GBK], alen, artist[GBK]
  0x02 LRC       : 歌词文本块（GBK，可多帧累加）
  0x03 LRC_END   : 空载荷 -> 设备解析并生效
  0x04 COVER_ROW : row_lo, row_hi, 240×RGB565(小端)
"""
import struct
import time

import serial
import serial.tools.list_ports

VID, PID = 0x0483, 0x5722
BAUD_AUDIO = 115200
BAUD_SLOT = 100000
BAUD_CTRL = 200000

T_SONG, T_LRC, T_LRC_END, T_COVER_ROW, T_POS = 0x01, 0x02, 0x03, 0x04, 0x05
FR_MAX_PAYLOAD = 480          # 设备单帧上限 512，留 6 字节头


class DeviceError(Exception):
    pass


def find_port():
    """按 VID/PID 找板子；找不到返回 None。"""
    for p in serial.tools.list_ports.comports():
        if p.vid == VID and p.pid == PID:
            return p.device
    return None


def port_conflicts():
    """列出可能独占板子 CDC 口的旧推流进程 [(pid, cmdline), ...]。

    Windows 串口是独占的：host_cdc_sender.py（play.bat 起的、尤其带 --wait
    常驻的）只要没关，桌面播放器再打开同一个 COM 就会 PermissionError(13)。
    依赖 pywin32 的 WMI；没装时返回空列表，不影响主流程。
    """
    import os
    try:
        import win32com.client
    except ImportError:
        return []
    me = os.getpid()
    try:
        rows = win32com.client.GetObject("winmgmts:").ExecQuery(
            "select ProcessId, CommandLine from Win32_Process "
            "where Name='python.exe' or Name='pythonw.exe'")
    except Exception:
        return []
    out = []
    for p in rows:
        cmd = p.CommandLine or ""
        pid = int(p.ProcessId)
        if pid == me:
            continue
        if "host_cdc_sender.py" in cmd or "play.bat" in cmd:
            out.append((pid, cmd))
    return out


def kill_port_conflicts():
    """强制结束旧推流进程、释放串口。返回 [(pid, cmdline), ...]。"""
    import subprocess
    killed = []
    for pid, cmd in port_conflicts():
        try:
            subprocess.check_output(["taskkill", "/PID", str(pid), "/F"],
                                    stderr=subprocess.STDOUT, text=True)
            killed.append((pid, cmd))
        except Exception:
            pass
    return killed


class Device(object):
    def __init__(self, port=None):
        self.port = port
        self.ser = None

    # ------------------------------------------------------------ 连接
    @property
    def is_open(self):
        return self.ser is not None and self.ser.is_open

    def open(self, port=None, write_timeout=2.0):
        self.close()
        name = port or self.port or find_port()
        if not name:
            raise DeviceError("没找到板子（VID 0483 / PID 5722）")
        try:
            self.ser = serial.Serial(name, BAUD_AUDIO, timeout=0.05,
                                     write_timeout=write_timeout)
        except Exception as e:
            raise DeviceError("打不开 %s: %s" % (name, e))
        self.port = name
        return name

    def close(self):
        if self.ser is not None:
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None

    def _need(self):
        if not self.is_open:
            raise DeviceError("串口未打开")

    def _set_baud(self, baud, settle=0.06):
        self._need()
        self.ser.baudrate = baud
        if settle:
            time.sleep(settle)

    # ------------------------------------------------------------ 帧
    def _frame(self, ftype, payload=b""):
        self._need()
        n = len(payload)
        hdr = b"ATK" + bytes([ftype, n & 0xFF, (n >> 8) & 0xFF])
        try:
            self.ser.write(hdr + payload)
        except serial.SerialException as e:
            raise DeviceError("写控制帧失败：%s" % e)

    # ------------------------------------------------------------ 选曲
    def select_slot(self, idx):
        """让设备切到第 idx 首（0 基）。设备端会清零歌词时钟并重画封面。"""
        self._set_baud(BAUD_SLOT + (idx % 16), 0.02)
        self._set_baud(BAUD_AUDIO, 0.02)

    # ------------------------------------------------------------ 控制模式
    def enter_control(self):
        self._set_baud(BAUD_CTRL, 0.08)

    def exit_control(self):
        self._set_baud(BAUD_AUDIO, 0.08)

    def push_meta(self, idx, title, artist):
        t = (title or "").encode("gbk", "replace")[:40]
        a = (artist or "").encode("gbk", "replace")[:40]
        self._frame(T_SONG, bytes([idx & 0xFF, len(t)]) + t + bytes([len(a)]) + a)

    def push_lrc(self, lrc_text, progress=None):
        data = (lrc_text or "").encode("gbk", "replace")
        total = max(1, (len(data) + FR_MAX_PAYLOAD - 1) // FR_MAX_PAYLOAD)
        for i in range(0, len(data), FR_MAX_PAYLOAD):
            self._frame(T_LRC, data[i:i + FR_MAX_PAYLOAD])
            if progress:
                progress(min(1.0, (i // FR_MAX_PAYLOAD + 1) / float(total)))
        self._frame(T_LRC_END, b"")

    def push_cover(self, image_path, progress=None):
        """逐行推 240×240 封面（每行 482 字节），设备边收边画。"""
        from PIL import Image
        im = Image.open(image_path).convert("RGB")
        w, h = im.size
        side = min(w, h)
        im = im.crop(((w - side) // 2, (h - side) // 2,
                      (w - side) // 2 + side, (h - side) // 2 + side)).resize((240, 240))
        px = im.tobytes()
        for row in range(240):
            out = bytearray([row & 0xFF, row >> 8])
            base = row * 240 * 3
            for x in range(240):
                i = base + x * 3
                r, g, b = px[i], px[i + 1], px[i + 2]
                v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                out += bytes([v & 0xFF, v >> 8])
            self._frame(T_COVER_ROW, bytes(out))
            if progress and row % 20 == 0:
                progress(row / 240.0)

    def push_track(self, idx, title, artist, lrc_text=None, cover_path=None,
                   progress=None, pos_ms=0):
        """一次把 元数据 + 歌词 + 时间轴基准 + 封面 推到设备（自动进出控制模式）。

        pos_ms 必须是「已按倍速缩放」的时间：设备按收到的 PCM 字节计时（墙钟），
        而下发的 LRC 时间戳已除以倍速，两边同尺度才能严格同步。
        """
        self.enter_control()
        try:
            self.push_meta(idx, title, artist)
            if lrc_text:
                self.push_lrc(lrc_text)
            self._frame(T_POS, struct.pack("<I", int(pos_ms) & 0xFFFFFFFF))
            if cover_path:
                self.push_cover(cover_path, progress)
        finally:
            self.exit_control()

    # ------------------------------------------------------------ 音频
    def write_pcm(self, data):
        self._need()
        try:
            self.ser.write(data)
        except serial.SerialException as e:
            # SerialTimeoutException 也属于 SerialException：
            # 必须转成 DeviceError，播放线程的 except DeviceError 分支
            # 才会 close + 重连；否则会卡死在
            # 「播放线程异常: Write timeout」的无限循环里。
            raise DeviceError("写 PCM 失败：%s" % e)

    def read_byte(self):
        """读一个 CDC IN 字节；没数据返回 None（超时 50ms）。"""
        if not self.is_open:
            return None
        try:
            b = self.ser.read(1)
            return b[0] if b else None
        except Exception:
            return None
