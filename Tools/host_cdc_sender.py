#!/usr/bin/env python3
# ============================================================
# host_cdc_sender.py —— 电脑端：经 USB CDC 虚拟串口把 WAV 发给 STM32
#
# 设备端链路：电脑 -> USB_SLAVE(CDC) -> MCU -> I2S -> WM8978 -> 喇叭
# 流程：读 44.1k/16bit/立体声 WAV -> 可选数字增益(+硬限幅) -> 按实时匀速发给虚拟串口。
#
# 依赖：pip install pyserial
# 用法：
#   python host_cdc_sender.py -p COM6 -f song.wav
#   python host_cdc_sender.py -p COM6 -f song.wav --gain 10
#   python host_cdc_sender.py --auto --wait -f a.wav b.wav --gain 1.0   # 播放列表，顺序播放
#   python host_cdc_sender.py --auto --wait -f a.wav b.wav --no-loop     # 整个列表播一遍后停
# 参数：
#   -p / --port   串口（默认 COM3）
#   -f / --file   一个或多个 WAV（均需 44.1k/16bit/立体声）；按顺序播放，默认 music.wav
#   --baud        波特率（CDC 名义值，默认 115200）
#   --no-loop     整个列表播一遍后停止（默认播完最后一首回到第一首循环）
#   --rate        发送速率倍数（默认 1.0；偶尔断音调 1.003，偶尔爆音调 0.998）
#   --gain        发送前音量增益倍数（默认 10.0；1.0＝不处理；放大会硬限幅）
#   --auto        自动按 VID_0483 / PID_5722 查找 CDC 虚拟串口，忽略 -p
#   --wait        端口不存在时持续等待（板子未枚举/按了 RESET 时用）；配合断线重连
#   --playlist    直接用本工程 Tools/pl01.wav ... plNN.wav（按序号排序），免去逐个 -f
#   --lrc/--cover/--title/--artist
#                 播放前把这些内容经同一条 USB 线下发给设备（换歌词/封面不用重烧固件）
#   --meta-for    这些内容属于第几首（0 基，默认=第一个 WAV 的序号）
#   --keys        接收板子按键命令（KEY0 长按=播放/暂停，KEY0/1 短按=下一首/重播）
# ============================================================
import os
import re
import sys
import glob
import time
import wave
import array
import serial
import serial.tools.list_ports
import argparse

CDC_VID = 0x0483
CDC_PID = 0x5722


KNEE = 0.70 * 32767.0          # 软膝起点：到这里开始平滑压缩
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
    return min(g, cap)


def check_wav(path):
    """校验单文件是否为 44.1k/16bit/立体声。返回 (nch, fr, sw)。"""
    try:
        wf = wave.open(path, "rb")
    except Exception as e:
        print("无法打开 WAV %s :" % path, e)
        sys.exit(1)
    nch = wf.getnchannels()
    fr = wf.getframerate()
    sw = wf.getsampwidth()
    wf.close()
    if not (nch == 2 and fr == 44100 and sw == 2):
        print("WAV 格式不符: %s" % path)
        print("需要 立体声 / 44100Hz / 16bit；实际 声道=%d 采样率=%d 位宽=%d" % (nch, fr, sw * 8))
        sys.exit(1)
    return nch, fr, sw


def scan_peak(path):
    """流式分块扫描整段 WAV 的峰值绝对值（0~32768），避免一次读入几十 MB。"""
    peak = 0
    wf = wave.open(path, "rb")
    block = 65536
    while True:
        data = wf.readframes(block)
        if not data:
            break
        a = array.array('h')
        a.frombytes(data[:len(data) - (len(data) % 2)])
        if len(a):
            p = max(abs(min(a)), abs(max(a)))
            if p > peak:
                peak = p
    wf.close()
    return peak


def find_cdc_port():
    """按 VID/PID 找板载 CDC 虚拟串口；找不到返回 None。
    注意：DFU bootloader 是 PID_DF11，不匹配，会被正确忽略。"""
    for p in serial.tools.list_ports.comports():
        try:
            if p.vid == CDC_VID and p.pid == CDC_PID:
                return p.device
        except Exception:
            pass
    return None


def port_exists(port):
    return any(p.device == port for p in serial.tools.list_ports.comports())


def resolve_port(args):
    """返回可用端口名，或 None（--wait 时调用方循环重试）。"""
    if args.auto:
        return find_cdc_port()
    return args.port if port_exists(args.port) else None


def open_serial(port, baud):
    # write_timeout=None：写不设超时，靠阻塞保证整块完整发出，
    # 避免 USB 偶发卡顿(瞬时 NAK/系统调度)导致 Write timeout 让整个脚本退出；
    # 且整块写出可保持 4 字节帧对齐，不会因丢半帧产生错位噪声。
    return serial.Serial(port, baud, timeout=1, write_timeout=None)


CDC_CTRL_BAUD = 200000          # 与固件 cdc_ctrl.h 的 CDC_CTRL_BAUD 一致
FR_SONG, FR_LRC, FR_LRC_END, FR_COVER_ROW = 0x01, 0x02, 0x03, 0x04


def _frame(ser, ftype, payload):
    """ATK + type + len(LE16) + payload"""
    ser.write(b"ATK" + bytes([ftype, len(payload) & 0xFF, (len(payload) >> 8) & 0xFF]) + payload)


def read_lrc_text(path):
    """自适应编码读文本（UTF-8/BOM/GBK 都试），后面统一转 GBK 发下去。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except Exception:
            pass
    return raw.decode("utf-8", "ignore")


def send_song_extras(ser, song_idx, lrc_path=None, cover_path=None, title=None, artist=None):
    """控制模式下把 歌名/歌手 + 歌词 + 封面 发给设备。

    时序：波特率设成 200000 → 设备进控制模式 → 发帧 → 设回 115200 → 恢复 PCM。
    播放期间设备完全不解析帧，所以这条通道不影响音频链路。
    """
    ser.baudrate = CDC_CTRL_BAUD
    time.sleep(0.06)                      # 等 SET_LINE_CODING 生效

    t = (title or "").encode("gbk", "replace")[:40]
    a = (artist or "").encode("gbk", "replace")[:40]
    _frame(ser, FR_SONG, bytes([song_idx & 0xFF, len(t)]) + t + bytes([len(a)]) + a)

    if lrc_path and os.path.exists(lrc_path):
        data = read_lrc_text(lrc_path).encode("gbk", "replace")
        for i in range(0, len(data), 480):
            _frame(ser, FR_LRC, data[i:i + 480])
        _frame(ser, FR_LRC_END, b"")
        print("  已下发歌词 %d 字节 (%s)" % (len(data), os.path.basename(lrc_path)), flush=True)

    if cover_path and os.path.exists(cover_path):
        try:
            from PIL import Image
            im = Image.open(cover_path).convert("RGB")
            w, h = im.size
            s0 = min(w, h)
            im = im.crop(((w - s0) // 2, (h - s0) // 2,
                          (w - s0) // 2 + s0, (h - s0) // 2 + s0)).resize((240, 240))
            px = im.tobytes()
            for row in range(240):
                out = bytearray([row & 0xFF, row >> 8])
                base = row * 240 * 3
                for x in range(240):
                    r = px[base + x * 3]
                    g = px[base + x * 3 + 1]
                    b = px[base + x * 3 + 2]
                    v = ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                    out += bytes([v & 0xFF, v >> 8])
                _frame(ser, FR_COVER_ROW, bytes(out))
                if row % 40 == 0:
                    time.sleep(0.005)     # 有硬件流控，这里只是保险
            print("  已下发封面 240x240 (%s)" % os.path.basename(cover_path), flush=True)
        except Exception as e:
            print("  封面上传失败:", e)

    ser.baudrate = 115200
    time.sleep(0.06)


class KeyState(object):
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
                    print("\n[KEY] 屏幕切到第 %d 首 -> 电脑换歌" % (c[0] + 1), flush=True)
                    continue
                if c == b"S":
                    want_idx = True
                elif c == b"P":
                    self.paused = True
                    print("\n[KEY] 暂停", flush=True)
                elif c == b"R":
                    self.paused = False
                    print("\n[KEY] 继续", flush=True)
                elif c == b"N":
                    self.next_req = True
                    print("\n[KEY] 下一首", flush=True)
                elif c == b"B":
                    self.prev_req = True
                    print("\n[KEY] 上一首", flush=True)

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


def _boost_timer_resolution():
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


def song_index_of(path, fallback):
    """从文件名末尾数字推断曲目序号(0 基)：pl01.wav -> 0, pl02.wav -> 1。"""
    stem = os.path.splitext(os.path.basename(path))[0]
    m = re.search(r"(\d+)\s*$", stem)
    if m:
        try:
            return max(0, int(m.group(1)) - 1)
        except ValueError:
            pass
    return fallback


def select_song(ser, idx):
    """告诉设备"现在放第几首"（0 基）。两条通道同时发，互不冲突：
      1) 主通道：baudrate = 100000+idx → CDC_SET_LINE_CODING，任意首数都行；
      2) 兼容通道：DTR=bit0 / RTS=bit1（只覆盖 0..2；3 是设备眼中的"刚打开"默认态，
         会被忽略，所以 idx=3 只靠主通道生效）。
    两者都走 USB 控制端点，不占音频数据通道，也不会打断 PCM。"""
    try:
        # 主通道：把波特率设成 100000+idx（触发 CDC_SET_LINE_CODING，0 字节音频开销）。
        # 这是可扩展的，任意首数都行。
        ser.baudrate = 100000 + idx
    except Exception:
        pass
    try:
        # 兼容通道：0/1 两首用 DTR/RTS 表达（老固件也能正确切曲）
        ser.rts = bool(idx & 2)
        ser.dtr = bool(idx & 1)
    except Exception:
        pass


def stream_playlist(ser, playlist, args, eff_rate, gap_silence):
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


def main():
    _boost_timer_resolution()          # 1ms 定时器精度（治「炸」的关键一步）
    ap = argparse.ArgumentParser(description="Send 44.1k/16bit/stereo WAV(s) over CDC serial to STM32")
    ap.add_argument("-p", "--port", default="COM3", help="serial port, e.g. COM3 or /dev/ttyACM0")
    ap.add_argument("-f", "--file", nargs="+", default=["music.wav"],
                    help="one or more WAV files, played in order (44.1k, 16bit, stereo)")
    ap.add_argument("--baud", type=int, default=115200, help="baud (nominal for CDC, default 115200)")
    ap.add_argument("--no-loop", action="store_true", help="stop after the whole playlist instead of looping")
    ap.add_argument("--rate", type=float, default=1.0,
                    help="发送速率倍数（默认 1.0；偶尔断音调到 1.002~1.005，偶尔爆音调到 0.998）")
    ap.add_argument("--gain", type=float, default=1.0,
                    help="额外音量倍数（默认 1.0）。以前默认 10 倍会把满量程歌直接削爆，已改")
    ap.add_argument("--peak", type=float, default=-3.0,
                    help="自动归一的目标峰值 dBFS（默认 -3，留余量不炸）；--no-norm 可关闭")
    ap.add_argument("--no-norm", action="store_true", help="不做峰值归一，只按 --gain 处理")
    ap.add_argument("--auto", action="store_true",
                    help="自动按 VID_0483/PID_5722 查找 CDC 虚拟串口（COM 号变了也不怕）")
    ap.add_argument("--wait", action="store_true",
                    help="端口不存在时持续等待；播放中掉线（如按 RESET）自动重连从头续播")
    ap.add_argument("--lrc", default=None, help="歌词文件，播放前经 USB 下发（不用重烧固件）")
    ap.add_argument("--cover", default=None, help="封面图片 jpg/png/bmp，同上")
    ap.add_argument("--title", default=None, help="下发的歌名（需 GBK 可编码）")
    ap.add_argument("--artist", default=None, help="下发的歌手")
    ap.add_argument("--keys", action="store_true",
                    help="接收板子按键命令：长按 KEY0=播放/暂停，短按 KEY0/1=下一首/重播")
    ap.add_argument("--meta-for", type=int, default=None,
                    help="这些内容属于第几首（0 基）；默认=第一个 WAV 的序号")
    ap.add_argument("--prefill", type=float, default=0.0,
                    help="开播前不按节拍预灌多少秒音频（默认 0=关闭）。"
                         "实测一次性灌 21KB 会让设备 USB OUT 端点卡死 -> Write timeout，别随便开")
    ap.add_argument("--playlist", action="store_true",
                    help="自动用本工程 Tools/pl01.wav..plNN.wav（按序号排序），忽略 -f")
    args = ap.parse_args()

    playlist = args.file
    if args.playlist:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        playlist = sorted(glob.glob(os.path.join(root, "Tools", "pl[0-9][0-9].wav")))
        if not playlist:
            print("没找到 Tools/pl01.wav ... plNN.wav")
            return 2

    # ---- 校验所有 WAV 格式一致 ----
    nch = fr = sw = None
    for path in playlist:
        c, r, s = check_wav(path)
        nch, fr, sw = c, r, s

    bytes_per_sec = nch * sw * fr  # 2*2*44100 = 176400 B/s（标称）
    eff_rate = bytes_per_sec * args.rate

    # ---- 峰值扫描 + 逐曲算增益（软膝限幅兜底）----
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
          (len(playlist), not args.no_loop, args.rate, args.auto, args.wait), flush=True)

    tail_silence = b"\x00" * (nch * sw * fr)          # 收尾 1 秒静音
    gap_silence = b"\x00" * (nch * sw * fr // 10)     # 曲目间隔 100ms 静音
    announced = False

    try:
        while True:
            # ---- 找端口（--wait 时持续等）----
            port = resolve_port(args)
            while port is None and args.wait:
                if not announced:
                    print("等待 CDC 设备 (VID_0483/PID_5722) 出现… "
                          "若设备管理器显示 'STM32 Bootloader'(PID_DF11)，说明板子在 DFU，"
                          "需把 BOOT0 拨回 0 再按 RESET。", flush=True)
                    announced = True
                time.sleep(0.5)
                port = resolve_port(args)

            if port is None:
                print("无法找到串口 %s（加 --wait 可等待设备插入）" % args.port)
                sys.exit(1)

            # ---- 打开串口 ----
            try:
                ser = open_serial(port, args.baud)
            except Exception as e:
                if args.wait:
                    print("打开 %s 失败: %s —— 重试中" % (port, e), flush=True)
                    time.sleep(0.5)
                    continue
                print("无法打开串口 %s :" % port, e)
                sys.exit(1)

            # ---- 就绪探测 ----
            # Windows 在设备重新枚举期间会残留"幽灵 COM 口"：open 成功但底层
            # USB 已断开，第一次 write 才报 PermissionError / Write timeout。
            # 先写 4 字节静音探针，写不通就关掉继续等，避免误报"开始发送"。
            try:
                ser.write(b"\x00" * 4)
                ser.flush()
            except Exception as e:
                print("端口 %s 未就绪（%s），继续等待设备稳定…" % (port, e), flush=True)
                try:
                    ser.close()
                except Exception:
                    pass
                time.sleep(1.0)
                announced = True
                continue

            print("端口 %s 已打开，开始发送 %d 首 (gain=%.2fx)；按 Ctrl+C 停止" %
                  (port, len(playlist), args.gain), flush=True)
            announced = False

            # ---- 发送 ----
            try:
                stream_playlist(ser, playlist, args, eff_rate, gap_silence)
                try:
                    ser.write(tail_silence)
                    time.sleep(0.05)
                    ser.flush()
                except Exception:
                    pass
                ser.close()
                print("播放结束", flush=True)
                return
            except KeyboardInterrupt:
                print("\n已停止", flush=True)
                try:
                    ser.write(tail_silence)
                    time.sleep(0.05)
                    ser.flush()
                except Exception:
                    pass
                ser.close()
                return
            except Exception as e:
                print("发送中断: %s" % e, flush=True)
                try:
                    ser.close()
                except Exception:
                    pass
                if not args.wait:
                    return
                print("设备可能重新枚举（按了 RESET？），等待后自动从第 1 首续播…", flush=True)
                time.sleep(1.0)
                continue
    finally:
        pass


if __name__ == "__main__":
    main()
