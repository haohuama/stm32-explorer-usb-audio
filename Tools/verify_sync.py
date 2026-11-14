# -*- coding: utf-8 -*-
"""verify_sync.py —— 离线验证「切歌同步 + 时间轴基准」协议（不碰真串口）"""
import io
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "DesktopPlayer"))

ok = True


def chk(name, cond, extra=""):
    global ok
    print(("  [OK]   " if cond else "  [FAIL] ") + name + ("  " + extra if extra else ""))
    ok = ok and cond


print("== 固件侧帧定义 ==")
ctrl = io.open(os.path.join(ROOT, "User/APP/cdc_ctrl.c"), encoding="utf-8").read()
chk("固件定义 T_POS=0x05", "#define T_POS       0x05u" in ctrl)
chk("固件 T_POS 解出 4 字节 LE 毫秒", "audio_stream_set_position(ms)" in ctrl
    and "((uint32_t)p[2] << 16)" in ctrl)
chk("固件提供 audio_stream_set_position",
    "void audio_stream_set_position(uint32_t ms)" in
    io.open(os.path.join(ROOT, "User/Hardware/AUDIO/i2s_audio.c"), encoding="utf-8").read())
main = io.open(os.path.join(ROOT, "User/main.c"), encoding="utf-8").read()
chk("实体键切歌发 'S'+idx", main.count("CDC_Cmd_Send2((uint8_t)'S'") == 2)
chk("触屏切歌也发 'S'+idx", "CDC_Cmd_Send2" in main and main.count("CDC_Cmd_Send2((uint8_t)'S'") >= 2)
chk("固件提供 2 字节上行发送",
    "int CDC_Cmd_Send2(uint8_t c, uint8_t d)" in
    io.open(os.path.join(ROOT, "Middlewares/USB/USB_APP/usbd_cdc_if.c"),
            encoding="utf-8").read())

print("== 桌面软件：T_POS 帧 ==")
import core_device as D


class FakeSer(object):
    def __init__(self):
        self.buf = bytearray()
        self.baudrate = D.BAUD_AUDIO
        self.is_open = True

    def write(self, d):
        self.buf += d

    def read(self, n):
        return b""

    def close(self):
        self.is_open = False


dev = D.Device.__new__(D.Device)
dev.ser = FakeSer()
dev.port = "FAKE"
dev.push_track(3, "忘不掉的你", "h3R3", "[00:01.00]a", None, pos_ms=45000)
frames = bytes(dev.ser.buf).split(b"ATK")[1:]
types = [f[0] for f in frames if len(f) >= 3]
chk("push_track 含 POS 帧", 0x05 in types, str(types))
pos = [f for f in frames if f and f[0] == 0x05][0]
payload = pos[3:3 + (pos[1] | (pos[2] << 8))]
chk("POS 载荷 = 4 字节 LE 45000", payload == struct.pack("<I", 45000), repr(payload))
chk("POS 在 LRC_END 之后", types.index(0x05) > types.index(0x03))

print("== host_cdc_sender.py：'S'+idx 解析 ==")
import importlib.util as iu
spec = iu.spec_from_file_location("sender", os.path.join(ROOT, "Tools", "host_cdc_sender.py"))
sender = iu.module_from_spec(spec)
spec.loader.exec_module(sender)


class FakePort(object):
    def __init__(self, data):
        self.data = bytearray(data)

    def read(self, n):
        if not self.data:
            return b""
        return bytes([self.data.pop(0)])


ks = sender.KeyState()
import threading
import time
_t = threading.Thread(target=ks._run, args=(FakePort(b"P" + b"R" + b"S\x05" + b"B" + b"N"),),
                      daemon=True)
_t.start()
time.sleep(0.25)
ks._stop = True
_t.join(1.0)
n, p, a = ks.take()
chk("KeyState 解出绝对切曲 idx=5", a == 5, "abs=%r" % a)
chk("KeyState 'B' = 上一首", p is True)
chk("KeyState 'N' = 下一首", n is True)
chk("KeyState 暂停被 'R' 复位", ks.paused is False)
loop = io.open(os.path.join(ROOT, "Tools", "host_cdc_sender.py"), encoding="utf-8").read()
chk("播放循环改成显式索引", "cur = 0" in loop and "jump = _a % n" in loop)

print("== 桌面软件：屏上切歌命令 ==")
cp = io.open(os.path.join(ROOT, "DesktopPlayer", "core_player.py"), encoding="utf-8").read()
chk("有命令读线程", "def _cmd_loop" in cp and "self._cmd_loop" in cp)
chk("收到 'S' 调 play_index", "self.play_index(c % max(1, len(self.tracks))" in cp)
chk("下发 POS 前按倍速缩放", "int(base_ms / self.speed)" in cp)

print("\n结果：" + ("全部通过" if ok else "有失败项"))
raise SystemExit(0 if ok else 1)
