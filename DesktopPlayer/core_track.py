# -*- coding: utf-8 -*-
"""core_track.py —— 曲目模型：ffmpeg 解码/变速、LRC 解析与时间缩放

要点（踩过的坑都在这）：
1. 设备端 I2S 时钟固定，**永远以 176400 B/s 消耗 PCM**。
   所以「倍速」不能靠改发送速率 —— 改慢了设备欠载补静音（断续），
   改快了环形缓冲溢出丢样本（咔哒）。正确做法是：先用 ffmpeg 重采样，
   输出仍然是 44.1k/立体声/16bit，再按原速率发。
   - 变速变调：asetrate=44100*S, aresample=44100
   - 变速不变调：atempo=S（0.5~2.0，超出范围串接多级）
2. 歌词时间戳必须按 speed 缩放后再发给设备，否则设备（按字节计时）
   在非 1.0 倍速下会和电脑端越走越偏。
"""
import os
import re
import shutil
import subprocess
import tempfile
import wave

BYTES_PER_SEC = 176400          # 44100 * 2ch * 2byte
SR = 44100

FFMPEG_CANDIDATES = [
    os.environ.get("FFMPEG", ""),
    r"C:/Program Files/File Converter/ffmpeg.exe",
    r"C:/ffmpeg/bin/ffmpeg.exe",
    shutil.which("ffmpeg") or "",
]

AUDIO_EXT = (".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".ape")


def find_ffmpeg():
    for p in FFMPEG_CANDIDATES:
        if p and os.path.isfile(p):
            return p
    return None


# ---------------------------------------------------------------- LRC 解析
RE_TS = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
CREDIT_WORDS = ("制作人", "编曲", "出品", "作词", "作曲", "混音", "母带", "监制",
                "统筹", "企划", "营销", "本歌曲来自", "网易云", "未经许可")


def parse_lrc(text):
    """-> [(ms, text)]，已按时间排序；自动丢掉 JSON 头、空行、版权行。"""
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("{"):
            continue
        m = RE_TS.match(line)
        if not m:
            continue
        txt = line[m.end():].strip()
        if not txt:
            continue
        if any(k in txt for k in CREDIT_WORDS) or "：" in txt:
            continue
        ms = (int(m.group(1)) * 60 + int(m.group(2))) * 1000
        frac = m.group(3) or "0"
        ms += int((frac + "00")[:2]) * 10
        out.append((ms, txt))
    out.sort(key=lambda x: x[0])
    return out


def read_text_any(path):
    """LRC 可能是 UTF-8 / UTF-8-BOM / GBK，全试一遍。"""
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "utf-8", "gbk", "big5"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def scale_lrc(text, speed):
    """把 [mm:ss.xx] 全部除以 speed（设备按字节计时，必须跟着缩）。"""
    if abs(speed - 1.0) < 1e-3:
        return text

    def repl(m):
        mm, ss, frac = m.group(1), m.group(2), m.group(3)
        ms = (int(mm) * 60 + int(ss)) * 1000
        if frac:
            ms += int((frac + "00")[:2]) * 10
        ms = int(round(ms / speed))
        return "[%02d:%05.2f]" % (ms // 60000, (ms % 60000) / 1000.0)

    return RE_TS.sub(repl, text)


# ---------------------------------------------------------------- 曲目
class Track(object):
    """一首歌：源文件 + 可选歌词 + 可选封面。"""

    def __init__(self, path):
        self.path = os.path.abspath(path)
        base, _ = os.path.splitext(self.path)
        self.title = os.path.basename(base)
        self.artist = ""
        self.lrc_path = None
        self.lrc_text = ""
        self.cover_path = None
        self.duration_ms = 0
        self._auto_bind()

    # ---- 自动绑定同目录同名 .lrc / 图片 ----
    def _auto_bind(self):
        base, _ = os.path.splitext(self.path)
        for ext in (".lrc", ".LRC"):
            if os.path.isfile(base + ext):
                self.set_lrc(base + ext)
                break
        for ext in (".jpg", ".jpeg", ".png", ".bmp"):
            for cand in (base + ext, base + ext.upper()):
                if os.path.isfile(cand):
                    self.cover_path = cand
                    return

    def set_lrc(self, path):
        self.lrc_path = path
        self.lrc_text = read_text_any(path)
        m = re.search(r"\[ti:(.*?)\]", self.lrc_text)
        if m and m.group(1).strip():
            self.title = m.group(1).strip()
        m = re.search(r"\[ar:(.*?)\]", self.lrc_text)
        if m:
            self.artist = m.group(1).strip()

    def set_cover(self, path):
        self.cover_path = path

    def lines(self):
        return parse_lrc(self.lrc_text) if self.lrc_text else []

    def __repr__(self):
        return "<Track %s>" % os.path.basename(self.path)


def probe_duration_ms(ffmpeg, path):
    """用 ffmpeg -i 的 stderr 里那行 Duration 拿时长（不需要 ffprobe）。"""
    try:
        r = subprocess.run([ffmpeg, "-hide_banner", "-i", path],
                           capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="ignore")
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+)\.(\d+)", r.stderr)
        if m:
            h, mi, s, cs = (int(x) for x in m.groups())
            return ((h * 60 + mi) * 60 + s) * 1000 + cs * 10
    except Exception:
        pass
    return 0


def render_segment(ffmpeg, src, start_ms, speed=1.0, keep_pitch=True, out_dir=None):
    """把 src 从 start_ms 开始的一段，按 speed 变速，渲染成 44.1k/16bit/立体声 wav。

    返回 wav 路径（调用方负责删除）。这一步是「倍速」的唯一正确实现：
    出口永远是 44.1k，字节率不变，设备才不会欠载/溢出。
    """
    out_dir = out_dir or tempfile.gettempdir()
    fd, out = tempfile.mkstemp(suffix=".wav", dir=out_dir)
    os.close(fd)

    if abs(speed - 1.0) < 1e-3:
        af = None
    elif keep_pitch:
        # atempo 单级只支持 0.5~2.0，超出就串两级
        s = speed
        parts = []
        while s > 2.0:
            parts.append(2.0)
            s /= 2.0
        while s < 0.5:
            parts.append(0.5)
            s /= 0.5
        parts.append(s)
        af = ",".join("atempo=%.4f" % p for p in parts)
    else:
        af = "asetrate=%d,aresample=%d" % (int(SR * speed), SR)

    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y"]
    if start_ms > 0:
        cmd += ["-ss", "%.3f" % (start_ms / 1000.0)]
    cmd += ["-i", src]
    if af:
        cmd += ["-filter:a", af]
    cmd += ["-ar", str(SR), "-ac", "2", "-acodec", "pcm_s16le", out]

    r = subprocess.run(cmd, capture_output=True, timeout=600)
    if r.returncode != 0 or not os.path.exists(out) or os.path.getsize(out) < 44:
        try:
            os.remove(out)
        except OSError:
            pass
        err = (r.stderr or b"").decode("utf-8", "ignore")[-300:]
        raise RuntimeError("ffmpeg 转码失败: %s" % (err or "未知错误"))
    return out


def open_wav(path):
    w = wave.open(path, "rb")
    if w.getnchannels() != 2 or w.getsampwidth() != 2:
        w.close()
        raise RuntimeError("WAV 不是 16bit 立体声：%s" % path)
    return w
