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
# ============================================================
import os
import re
import sys
import time
import wave
import array
import serial
import serial.tools.list_ports
import argparse

CDC_VID = 0x0483
CDC_PID = 0x5722


def apply_gain(data, gain):
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
    return a.tobytes()


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
    """按列表顺序发送全部 WAV；绝对时间调度跨曲目连续，切歌插入短静音防爆音。
    正常播完整个列表返回 True；异常时抛给外层重连。"""
    chunk_frames = 1024  # 每次读 1024 帧 ≈ 23ms
    next_t = time.monotonic()

    while True:
        for idx, path in enumerate(playlist, 1):
            wf = wave.open(path, "rb")
            print("[%d/%d] 正在播放: %s" % (idx, len(playlist), os.path.basename(path)), flush=True)
            # 通知 MCU 当前曲目序号（0 基）→ 切歌词 + 歌词时钟清零
            select_song(ser, song_index_of(path, idx - 1))
            while True:
                data = wf.readframes(chunk_frames)
                if not data:
                    break
                if args.gain != 1.0:
                    data = apply_gain(data, args.gain)
                ser.write(data)
                next_t += len(data) / eff_rate
                dt = next_t - time.monotonic()
                if dt > 0:
                    time.sleep(dt)   # dt<=0 表示已落后，立即继续下一批追赶
            wf.close()

            # 曲目之间插一小段静音：保持设备端环形缓冲有数据（不欠载），
            # 同时避免两首歌首尾样本直接拼接产生咔哒声。
            if gap_silence:
                ser.write(gap_silence)
                next_t += len(gap_silence) / eff_rate
                gap_dt = next_t - time.monotonic()
                if gap_dt > 0:
                    time.sleep(gap_dt)
            print("[%d/%d] 播放结束" % (idx, len(playlist)), flush=True)

        if args.no_loop:
            return True
        print("---- 列表播完，回到第 1 首循环 ----", flush=True)


def main():
    ap = argparse.ArgumentParser(description="Send 44.1k/16bit/stereo WAV(s) over CDC serial to STM32")
    ap.add_argument("-p", "--port", default="COM3", help="serial port, e.g. COM3 or /dev/ttyACM0")
    ap.add_argument("-f", "--file", nargs="+", default=["music.wav"],
                    help="one or more WAV files, played in order (44.1k, 16bit, stereo)")
    ap.add_argument("--baud", type=int, default=115200, help="baud (nominal for CDC, default 115200)")
    ap.add_argument("--no-loop", action="store_true", help="stop after the whole playlist instead of looping")
    ap.add_argument("--rate", type=float, default=1.0,
                    help="发送速率倍数（默认 1.0；偶尔断音调到 1.002~1.005，偶尔爆音调到 0.998）")
    ap.add_argument("--gain", type=float, default=10.0,
                    help="发送前音量增益倍数（默认 10.0；1.0=不处理；放大会硬限幅防爆音）")
    ap.add_argument("--auto", action="store_true",
                    help="自动按 VID_0483/PID_5722 查找 CDC 虚拟串口（COM 号变了也不怕）")
    ap.add_argument("--wait", action="store_true",
                    help="端口不存在时持续等待；播放中掉线（如按 RESET）自动重连从头续播")
    args = ap.parse_args()

    playlist = args.file

    # ---- 校验所有 WAV 格式一致 ----
    nch = fr = sw = None
    for path in playlist:
        c, r, s = check_wav(path)
        nch, fr, sw = c, r, s

    bytes_per_sec = nch * sw * fr  # 2*2*44100 = 176400 B/s（标称）
    eff_rate = bytes_per_sec * args.rate

    # ---- 峰值扫描 + 增益提示 ----
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
          (args.gain, len(playlist), not args.no_loop, args.rate, args.auto, args.wait), flush=True)

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
