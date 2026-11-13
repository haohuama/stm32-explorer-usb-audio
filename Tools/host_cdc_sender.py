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
# 参数：
#   -p / --port   串口（默认 COM3）
#   -f / --file   WAV 文件（默认 music.wav，需 44.1k/16bit/立体声）
#   --baud        波特率（CDC 名义值，默认 115200）
#   --no-loop     只播一遍
#   --rate        发送速率倍数（默认 1.0；偶尔断音调 1.003，偶尔爆音调 0.998）
#   --gain        发送前音量增益倍数（默认 10.0；1.0＝不处理；放大会硬限幅）
# ============================================================
import sys
import time
import wave
import array
import serial
import argparse


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


def scan_peak(wf):
    """扫描整段 WAV 的峰值绝对值（0~32768），扫描后回卷到开头。"""
    wf.rewind()
    n = wf.getnframes()
    data = wf.readframes(n)
    wf.rewind()
    if not data:
        return 0
    a = array.array('h')
    a.frombytes(data[:len(data) - (len(data) % 2)])
    if len(a) == 0:
        return 0
    return max(abs(min(a)), abs(max(a)))


def main():
    ap = argparse.ArgumentParser(description="Send a 44.1k/16bit/stereo WAV over CDC serial to STM32")
    ap.add_argument("-p", "--port", default="COM3", help="serial port, e.g. COM3 or /dev/ttyACM0")
    ap.add_argument("-f", "--file", default="music.wav", help="input WAV (44.1k, 16bit, stereo)")
    ap.add_argument("--baud", type=int, default=115200, help="baud (nominal for CDC, default 115200)")
    ap.add_argument("--no-loop", action="store_true", help="stop after one play instead of looping")
    ap.add_argument("--rate", type=float, default=1.0,
                    help="发送速率倍数（默认 1.0；偶尔断音调到 1.002~1.005，偶尔爆音调到 0.998）")
    ap.add_argument("--gain", type=float, default=10.0,
                    help="发送前音量增益倍数（默认 10.0；1.0=不处理；放大会硬限幅防爆音）")
    args = ap.parse_args()

    # ---- 校验 WAV 格式 ----
    try:
        wf = wave.open(args.file, "rb")
    except Exception as e:
        print("无法打开 WAV:", e)
        sys.exit(1)

    nch = wf.getnchannels()
    fr = wf.getframerate()
    sw = wf.getsampwidth()
    if not (nch == 2 and fr == 44100 and sw == 2):
        print("WAV 格式不符：需要 立体声 / 44100Hz / 16bit")
        print("实际：声道=%d 采样率=%d 位宽=%d" % (nch, fr, sw * 8))
        wf.close()
        sys.exit(1)

    bytes_per_sec = nch * sw * fr  # 2*2*44100 = 176400 B/s（标称）
    eff_rate = bytes_per_sec * args.rate

    # ---- 峰值扫描 + 增益提示（帮你判断 10x 会不会削得太狠）----
    peak = scan_peak(wf)
    print("源文件峰值: %d (%.1f%% 满量程)   增益: %.2fx" %
          (peak, (peak / 32768.0 * 100.0), args.gain))
    if peak > 0 and peak * args.gain > 32767:
        print("  ⚠ 增益后峰值≈%d 会超过满量程→削波(可能失真)。想要干净又响，--gain 取 %.2f 左右。" %
              (int(peak * args.gain), 32767.0 / peak))

    # ---- 打开串口 ----
    try:
        # write_timeout=None：写不设超时，靠阻塞保证整块完整发出，
        # 避免 USB 偶发卡顿(瞬时 NAK/系统调度)导致 Write timeout 让整个脚本退出；
        # 且整块写出可保持 4 字节帧对齐，不会因丢半帧产生错位噪声。
        ser = serial.Serial(args.port, args.baud, timeout=1, write_timeout=None)
    except Exception as e:
        print("无法打开串口 %s :" % args.port, e)
        wf.close()
        sys.exit(1)

    print("端口 %s 已打开，开始发送 %s (循环=%s, gain=%.2fx)" %
          (args.port, args.file, not args.no_loop, args.gain))
    print("按 Ctrl+C 停止")

    chunk_frames = 1024  # 每次读 1024 帧 ≈ 23ms
    tail_silence = b"\x00" * (nch * sw * fr)   # 收尾 1 秒静音

    try:
        # 绝对时间调度：消除每次 sleep 过冲的累积误差，平均速率 == eff_rate
        next_t = time.monotonic()
        while True:
            data = wf.readframes(chunk_frames)
            if not data:
                if args.no_loop:
                    break
                wf.rewind()
                data = wf.readframes(chunk_frames)
                if not data:
                    break

            if args.gain != 1.0:
                data = apply_gain(data, args.gain)   # 增益 + 限幅

            ser.write(data)
            next_t += len(data) / eff_rate
            dt = next_t - time.monotonic()
            if dt > 0:
                time.sleep(dt)   # dt<=0 表示已落后，立即继续下一批追赶，不再额外睡
    except KeyboardInterrupt:
        print("\n已停止")
    except Exception as e:
        print("发送异常:", e)
    finally:
        try:
            ser.write(tail_silence)
            time.sleep(0.05)
            ser.flush()
            ser.close()
        except Exception:
            pass
        wf.close()


if __name__ == "__main__":
    main()
