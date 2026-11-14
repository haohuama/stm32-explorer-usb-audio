# -*- coding: utf-8 -*-
"""core_mcu.py —— 把任意音频转成「单片机（STM32 探索者 F407）能吃」的格式

## 板子端的硬约束（不能改，是 I2S 时钟决定的）
设备端 I2S 固定按 **176400 B/s** 消费 PCM，也就是：
    44100 Hz × 2 声道 × 16 bit
所以喂给板子的音频必须是 **44.1kHz / 16bit / 立体声 / PCM WAV**。
  * mp3 / flac / m4a 这些压缩格式 -> 板子解不了（没有解码器），必须先转。
  * 单声道 -> 转成立体声（否则设备按 2 声道取样会变速+错位）。
  * 其它采样率（48k/32k）-> 重采样到 44.1k。

## 为什么不能只转格式不改电平
之前实测过：数字端贴顶样本只占 0.002%，但「炸」的不是数字削波，
而是**模拟端满档过载**。所以这里默认带一个 -1 dBFS 的峰值限制器
（alimiter），把源文件里已经削顶的片段拉回来一点，避免推流后爆音。

## 用法
    from core_mcu import to_mcu_wav, verify_mcu_wav
    to_mcu_wav(ffmpeg, "a.mp3", "Tools/mcu/pl07.wav")
    print(verify_mcu_wav("Tools/mcu/pl07.wav"))
"""
import os
import re
import subprocess
import wave

# 与固件/上位机保持一致的常量
SR = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
BYTES_PER_SEC = SR * CHANNELS * SAMPLE_WIDTH        # 176400

AUDIO_EXT = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".ape", ".aiff")


def find_ffmpeg():
    """找 ffmpeg：优先环境变量，其次常见安装位置。"""
    import shutil
    cands = [
        os.environ.get("FFMPEG", ""),
        r"C:/Program Files/File Converter/ffmpeg.exe",
        r"C:/ffmpeg/bin/ffmpeg.exe",
        shutil.which("ffmpeg") or "",
    ]
    for p in cands:
        if p and os.path.isfile(p):
            return p
    return None


def probe_duration_ms(ffmpeg, path):
    """从 ffmpeg 的 stderr 里那行 Duration 取时长（不需要 ffprobe）。"""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                           capture_output=True, text=True, timeout=30,
                           encoding="utf-8", errors="ignore")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", r.stderr)
        if m:
            h, mi, s, cs = (int(x) for x in m.groups())
            return ((h * 60 + mi) * 60 + s) * 1000 + cs * 10
    except Exception:
        pass
    return 0


def to_mcu_wav(ffmpeg, src, dst, peak_db=-1.0, normalize=False, timeout=1800):
    """把 src 转成 44.1k/16bit/立体声 PCM WAV 写到 dst。

    peak_db   : 峰值限制（dBFS）。0 表示不限。默认 -1，给模拟端留余量。
    normalize : True 时额外做一次响度归一（loudnorm），适合各首歌电平差异大的场景。
    返回 (dst, duration_ms)
    """
    if not ffmpeg or not os.path.isfile(ffmpeg):
        raise RuntimeError("找不到 ffmpeg（设环境变量 FFMPEG 指向 ffmpeg.exe）")
    if not os.path.isfile(src):
        raise RuntimeError("源文件不存在：%s" % src)

    d = os.path.dirname(os.path.abspath(dst))
    if d and not os.path.isdir(d):
        os.makedirs(d)

    filters = []
    if peak_db is not None and peak_db < 0:
        # alimiter 的 limit 是线性幅度：-1 dBFS ≈ 0.891
        filters.append("alimiter=limit=%.4f:attack=5:release=50" % (10.0 ** (peak_db / 20.0)))
    if normalize:
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src]
    if filters:
        cmd += ["-filter:a", ",".join(filters)]
    cmd += ["-ar", str(SR), "-ac", str(CHANNELS),
            "-acodec", "pcm_s16le", "-f", "wav", dst]

    r = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if r.returncode != 0 or not os.path.isfile(dst) or os.path.getsize(dst) < 44:
        err = (r.stderr or b"").decode("utf-8", "ignore")[-400:]
        try:
            os.remove(dst)
        except OSError:
            pass
        raise RuntimeError("ffmpeg 转码失败：%s" % (err.strip() or "未知错误"))

    info = verify_mcu_wav(dst)
    if not info.get("ok"):
        raise RuntimeError("转码结果不合规：%s" % info)
    return dst, info["duration_ms"]


def verify_mcu_wav(path):
    """检查一个 wav 是否符合板子要求，返回诊断字典。"""
    out = {"path": path, "ok": False, "reason": ""}
    try:
        with wave.open(path, "rb") as w:
            out["channels"] = w.getnchannels()
            out["sampwidth"] = w.getsampwidth()
            out["framerate"] = w.getframerate()
            out["frames"] = w.getnframes()
    except Exception as e:
        out["reason"] = "打不开：%s" % e
        return out

    if out["channels"] != CHANNELS:
        out["reason"] = "声道数 %d != 2" % out["channels"]
    elif out["sampwidth"] != SAMPLE_WIDTH:
        out["reason"] = "位宽 %d != 16bit" % (out["sampwidth"] * 8)
    elif out["framerate"] != SR:
        out["reason"] = "采样率 %d != 44100" % out["framerate"]
    else:
        out["ok"] = True
    out["duration_ms"] = int(out["frames"] * 1000.0 / SR)
    out["bytes"] = os.path.getsize(path) if os.path.isfile(path) else 0
    out["bitrate_bps"] = BYTES_PER_SEC
    return out


def split_name(path):
    """从文件名 "歌名 - 歌手.mp3" 拆出 (歌名, 歌手)；没有分隔符就整名当歌名。"""
    base = os.path.splitext(os.path.basename(path))[0]
    head, sep, tail = base.partition(" - ")
    if not sep:
        return base.strip(), ""
    return head.strip(), tail.strip()


def gbk_safe(s):
    """裁掉 GBK 编不了的字符（板子屏上的中文是 GBK 字节）。"""
    out = s
    while out:
        try:
            out.encode("gbk")
            return out
        except UnicodeEncodeError:
            out = out[:-1]
    return ""


def scan_audio(folder, exts=AUDIO_EXT):
    """列出目录里的音频文件（按文件名排序）。"""
    if not os.path.isdir(folder):
        return []
    out = []
    for n in sorted(os.listdir(folder)):
        if os.path.splitext(n)[1].lower() in exts:
            out.append(os.path.join(folder, n))
    return out


def find_lrc(folder, stem):
    """在同目录找同名 .lrc（大小写不敏感）。"""
    if not os.path.isdir(folder):
        return None
    for n in os.listdir(folder):
        if os.path.splitext(n)[0].lower() == stem.lower() and n.lower().endswith(".lrc"):
            return os.path.join(folder, n)
    return None
