# -*- coding: utf-8 -*-
"""app.py —— 桌面端控制台（Tkinter，零第三方 UI 依赖）

功能
  1. 导入音乐（mp3/wav/flac/m4a/ogg…，自动用 ffmpeg 转成设备能吃的 44.1k/16bit/立体声）
  2. 导入/绑定歌词（.lrc），桌面大字滚动显示，当前句高亮
  3. 播放 / 暂停 / 上一首 / 下一首 / 拖动进度
  4. 倍速 0.5x~2.0x（可选「保持音调」，默认开）
  5. 音量（电脑端数字音量，0~150%）
  6. 顺带把 歌名/歌手/歌词/封面 推给板子，小屏同步显示

启动：双击 启动播放器.bat，或  py DesktopPlayer/app.py
自检：py DesktopPlayer/app.py --selftest
"""
import argparse
import os
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import core_track as T
from core_device import find_port, port_conflicts
from core_player import Player, PLAYING, PAUSED

# ---------------------------------------------------------------- 配色
BG = "#0f1116"
PANEL = "#181b23"
PANEL2 = "#20242e"
FG = "#e8eaf0"
MUT = "#8890a4"
ACC = "#4ea1ff"
HILITE = "#ffd166"

SPEEDS = ["0.5x", "0.75x", "1.0x", "1.25x", "1.5x", "2.0x"]


def fmt(ms):
    ms = max(0, int(ms))
    return "%02d:%02d" % (ms // 60000, (ms % 60000) // 1000)


class App(object):
    def __init__(self, root):
        self.root = root
        self.ffmpeg = T.find_ffmpeg()
        self.player = Player(on_log=self._on_log, on_track_changed=self._on_track)
        self.tracks = []
        self._lyr_key = None
        self._last_dev = None
        self._dev_txt = ""
        self._conflict = []
        self._conflict_at = 0.0

        root.title("STM32 音乐播放器 — 桌面控制台")
        root.configure(bg=BG)
        root.geometry("1060x680")
        root.minsize(900, 600)

        self.f_lyric = tkfont.Font(family="Microsoft YaHei", size=15)
        self.f_lyric_cur = tkfont.Font(family="Microsoft YaHei", size=19, weight="bold")
        self.f_title = tkfont.Font(family="Microsoft YaHei", size=22, weight="bold")
        self.f_sub = tkfont.Font(family="Microsoft YaHei", size=11)
        self.f_ui = tkfont.Font(family="Microsoft YaHei", size=10)

        self._build()
        self.player.start()
        self._load_builtin_playlist()      # 把工程里现成的歌带进列表，打开就能用
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<space>", lambda e: self._toggle())
        root.bind("<Left>", lambda e: self.player.prev())
        root.bind("<Right>", lambda e: self.player.next())
        self.root.after(80, self._tick)

    # ------------------------------------------------------------ UI
    def _btn(self, parent, text, cmd, w=10, bg=PANEL2, fg=FG):
        b = tk.Button(parent, text=text, command=cmd, width=w, bg=bg, fg=fg,
                      activebackground=ACC, activeforeground="#000",
                      relief="flat", bd=0, font=self.f_ui, cursor="hand2",
                      padx=8, pady=5)
        return b

    def _build(self):
        # ---- 顶部工具条 ----
        top = tk.Frame(self.root, bg=PANEL, height=52)
        top.pack(side="top", fill="x")
        top.pack_propagate(False)
        self._btn(top, "导入音乐", self.import_music, 10).pack(side="left", padx=(12, 6), pady=9)
        self._btn(top, "绑定歌词", self.bind_lyric, 10).pack(side="left", padx=6, pady=9)
        self._btn(top, "选择封面", self.bind_cover, 10).pack(side="left", padx=6, pady=9)

        self.lbl_dev = tk.Label(top, text="设备：检测中…", bg=PANEL, fg=MUT, font=self.f_ui)
        self.lbl_dev.pack(side="left", padx=18)
        self._btn(top, "释放串口", self.release_port, 10).pack(side="left", padx=(0, 8), pady=9)

        # 右侧：倍速
        tk.Label(top, text="倍速", bg=PANEL, fg=MUT, font=self.f_ui).pack(side="right", padx=(0, 4))
        self.cmb_speed = tk.OptionMenu(top, tk.StringVar(value="1.0x"), *SPEEDS,
                                      command=self._on_speed)
        self.cmb_speed.configure(bg=PANEL2, fg=FG, activebackground=ACC,
                                 relief="flat", bd=0, highlightthickness=0,
                                 font=self.f_ui, width=6)
        self.cmb_speed["menu"].configure(bg=PANEL2, fg=FG)
        self.cmb_speed.pack(side="right", padx=(0, 12))

        self.var_pitch = tk.BooleanVar(value=True)
        chk = tk.Checkbutton(top, text="保持音调", variable=self.var_pitch,
                             command=self._on_pitch, bg=PANEL, fg=MUT,
                             selectcolor=PANEL2, activebackground=PANEL,
                             activeforeground=FG, font=self.f_ui, bd=0)
        chk.pack(side="right", padx=(0, 8))

        # ---- 底部播放条 ----
        bottom = tk.Frame(self.root, bg=PANEL, height=62)
        bottom.pack(side="bottom", fill="x")
        bottom.pack_propagate(False)

        self.btn_prev = self._btn(bottom, "⏮", self.player.prev, 4)
        self.btn_prev.pack(side="left", padx=(14, 4), pady=12)
        self.btn_play = self._btn(bottom, "▶", self._toggle, 4, bg=ACC, fg="#000")
        self.btn_play.pack(side="left", padx=4, pady=12)
        self.btn_next = self._btn(bottom, "⏭", self.player.next, 4)
        self.btn_next.pack(side="left", padx=(4, 16), pady=12)

        tk.Label(bottom, text="音量", bg=PANEL, fg=MUT, font=self.f_ui).pack(side="left")
        self.var_vol = tk.DoubleVar(value=38)
        sc = tk.Scale(bottom, from_=0, to=100, orient="horizontal", variable=self.var_vol,
                      command=self._on_vol, bg=PANEL, fg=FG, troughcolor=PANEL2,
                      highlightthickness=0, bd=0, showvalue=True, length=170,
                      font=self.f_ui, sliderrelief="flat")
        sc.pack(side="left", padx=8)

        self.lbl_status = tk.Label(bottom, text="就绪", bg=PANEL, fg=MUT, font=self.f_ui,
                                   anchor="w")
        self.lbl_status.pack(side="left", fill="x", expand=True, padx=(16, 12))

        # ---- 主体 ----
        body = tk.Frame(self.root, bg=BG)
        body.pack(side="top", fill="both", expand=True, padx=12, pady=(10, 6))

        # 左：列表
        left = tk.Frame(body, bg=PANEL, width=300)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)
        tk.Label(left, text="播放列表", bg=PANEL, fg=MUT, font=self.f_ui,
                 anchor="w").pack(fill="x", padx=12, pady=(10, 4))
        self.lst = tk.Listbox(left, bg=PANEL, fg=FG, selectbackground=ACC,
                              selectforeground="#000", bd=0, highlightthickness=0,
                              font=self.f_ui, activestyle="none")
        self.lst.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.lst.bind("<Double-Button-1>", self._on_list_dbl)

        # 右：信息 + 进度 + 歌词
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True, padx=(12, 0))

        # 封面缩略图 + 歌名/歌手
        info = tk.Frame(right, bg=BG)
        info.pack(fill="x")
        self.cv_cover = tk.Canvas(info, width=124, height=124, bg=PANEL2,
                                  highlightthickness=0)
        self.cv_cover.pack(side="left", padx=(0, 14))
        self._cover_ref = None
        txt = tk.Frame(info, bg=BG)
        txt.pack(side="left", fill="both", expand=True)
        self.lbl_title = tk.Label(txt, text="没有在播放", bg=BG, fg=FG,
                                  font=self.f_title, anchor="w", justify="left")
        self.lbl_title.pack(fill="x", pady=(16, 2))
        self.lbl_artist = tk.Label(txt, text="", bg=BG, fg=MUT,
                                   font=self.f_sub, anchor="w")
        self.lbl_artist.pack(fill="x")
        self._draw_cover_placeholder()

        self.cv_prog = tk.Canvas(right, height=26, bg=BG, highlightthickness=0)
        self.cv_prog.pack(fill="x")
        self.cv_prog.bind("<Button-1>", self._on_seek)

        self.cv_lyr = tk.Canvas(right, bg=BG, highlightthickness=0)
        self.cv_lyr.pack(fill="both", expand=True, pady=(6, 0))
        self.cv_lyr.bind("<Configure>", lambda e: self._draw_lyrics(force=True))

    # ------------------------------------------------------------ 事件
    def _on_log(self, s):
        self.root.after(0, lambda: self.lbl_status.configure(text=s))

    def _on_track(self, i):
        def upd():
            self.lst.selection_clear(0, "end")
            if 0 <= i < self.lst.size():
                self.lst.selection_set(i)
                self.lst.see(i)
            tr = self.player.track
            if tr:
                self.lbl_title.configure(text=tr.title or os.path.basename(tr.path))
                self.lbl_artist.configure(text=tr.artist or "")
                self._show_cover(tr)
            self._lyr_key = None
            self._draw_lyrics(force=True)
        self.root.after(0, upd)

    # ------------------------------------------------------------ 封面
    def _draw_cover_placeholder(self, ch="♪"):
        c = self.cv_cover
        c.delete("all")
        c.create_rectangle(0, 0, 123, 123, fill=PANEL2, outline="")
        c.create_text(62, 62, text=ch, fill=MUT, font=("Microsoft YaHei", 34))

    def _show_cover(self, tr):
        path = getattr(tr, "cover_path", None)
        if not path or not os.path.isfile(path):
            self._draw_cover_placeholder((tr.title or "♪")[:1])
            return
        try:
            from PIL import Image, ImageTk
            im = Image.open(path).convert("RGB")
            w, h = im.size
            s = min(w, h)
            im = im.crop(((w - s) // 2, (h - s) // 2,
                          (w - s) // 2 + s, (h - s) // 2 + s)).resize((124, 124))
            self._cover_ref = ImageTk.PhotoImage(im)
            self.cv_cover.delete("all")
            self.cv_cover.create_image(0, 0, anchor="nw", image=self._cover_ref)
        except Exception:
            self._draw_cover_placeholder((tr.title or "♪")[:1])

    def _toggle(self):
        self.player.toggle()

    def _on_list_dbl(self, _e):
        sel = self.lst.curselection()
        if sel:
            self.player.play_index(sel[0])

    def _on_speed(self, val):
        try:
            s = float(val.replace("x", ""))
        except ValueError:
            s = 1.0
        self.player.set_speed(s, self.var_pitch.get())

    def _on_pitch(self):
        self.player.set_speed(self.player.speed, self.var_pitch.get())

    def _on_vol(self, _v):
        self.player.volume = max(0.0, self.var_vol.get() / 100.0)

    def _on_seek(self, e):
        w = max(1, self.cv_prog.winfo_width())
        ratio = max(0.0, min(1.0, e.x / float(w)))
        self.player.seek(int(ratio * self.player.duration_ms))

    # ------------------------------------------------------------ 内置播放列表
    def _load_builtin_playlist(self):
        """把 C:/stm32TEST/Tools/plNN.wav + Tools/lyrics/plNN.lrc 预置进列表。

        这样双击快捷方式就能直接看到《忘不掉的你》，不用每次重新导入。
        用户后面用「导入音乐」加的歌会追加在后面，不覆盖。
        """
        import glob
        import re as _re
        import wave as _wave

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools = os.path.join(root, "Tools")
        lyric_dir = os.path.join(tools, "lyrics")
        cover = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "default_cover.jpg")
        wavs = sorted(glob.glob(os.path.join(tools, "pl*.wav")))
        if not wavs:
            return

        def num(p):
            m = _re.search(r"pl(\d+)\.wav$", p, _re.I)
            return int(m.group(1)) if m else 999

        wavs.sort(key=num)
        for wav in wavs:
            if any(t.path == wav for t in self.tracks):
                continue
            tr = T.Track(wav)
            stem = os.path.splitext(os.path.basename(wav))[0]
            for lrc in (os.path.join(lyric_dir, stem + ".lrc"),
                        os.path.join(tools, stem + ".lrc"),
                        os.path.join(lyric_dir, stem + "_single.lrc")):
                if os.path.isfile(lrc):
                    tr.set_lrc(lrc)
                    break
            try:
                with _wave.open(wav, "rb") as w:
                    tr.duration_ms = int(w.getnframes() * 1000.0 / w.getframerate())
            except Exception:
                pass
            if os.path.isfile(cover):
                tr.cover_path = cover
            self.tracks.append(tr)

        self.lst.delete(0, "end")
        for t in self.tracks:
            self.lst.insert("end", "  %s%s" % (t.title, "  ♪" if t.lrc_text else ""))
        self.player.set_tracks(self.tracks)
        # 默认停在第 6 首《忘不掉的你》，但不自动播放（串口可能被别的推流进程占着）
        pick = 0
        for i, t in enumerate(self.tracks):
            if "忘不掉" in t.title:
                pick = i
                break
        self.lst.selection_set(pick)
        self.player.index = pick
        self.player.lrc_lines = self.tracks[pick].lines()
        self.player._dur_ms = self.tracks[pick].duration_ms
        tr = self.tracks[pick]
        self.lbl_title.configure(text=tr.title)
        self.lbl_artist.configure(text=tr.artist or "")
        self._show_cover(tr)
        self.lbl_status.configure(text="已载入 %d 首（双击列表开始播放）" % len(self.tracks))
        self._lyr_key = None
        self._draw_lyrics(0, force=True)
        self._draw_progress(0, tr.duration_ms)

    # ------------------------------------------------------------ 导入
    def import_music(self):
        paths = filedialog.askopenfilenames(
            title="选择音乐文件",
            filetypes=[("音频", " ".join("*" + e for e in T.AUDIO_EXT)), ("全部", "*.*")])
        if not paths:
            return
        if not self.ffmpeg:
            messagebox.showerror("缺少 ffmpeg", "没找到 ffmpeg.exe。\n"
                                 "请把 ffmpeg 放到 PATH，或设置环境变量 FFMPEG 指向它。")
            return
        self.lbl_status.configure(text="正在读取文件信息…")
        threading.Thread(target=self._add_files, args=(paths,), daemon=True).start()

    def _add_files(self, paths):
        added = 0
        for p in paths:
            if any(os.path.abspath(p) == t.path for t in self.tracks):
                continue
            tr = T.Track(p)
            tr.duration_ms = T.probe_duration_ms(self.ffmpeg, tr.path)
            self.tracks.append(tr)
            added += 1
        def done():
            self.lst.delete(0, "end")
            for t in self.tracks:
                self.lst.insert("end", "  %s%s" % (t.title, "  ♪" if t.lrc_text else ""))
            self.player.set_tracks(self.tracks)
            self.lbl_status.configure(text="已导入 %d 首（共 %d 首）" % (added, len(self.tracks)))
            if self.player.track is None and self.tracks:
                self.player.play_index(0, autoplay=False)
        self.root.after(0, done)

    def _sel_track(self):
        sel = self.lst.curselection()
        if not sel:
            messagebox.showinfo("提示", "先在播放列表里点一首歌")
            return None
        return self.tracks[sel[0]] if sel[0] < len(self.tracks) else None

    def bind_lyric(self):
        tr = self._sel_track()
        if not tr:
            return
        p = filedialog.askopenfilename(title="选择歌词",
                                       filetypes=[("LRC 歌词", "*.lrc *.LRC"), ("全部", "*.*")])
        if not p:
            return
        tr.set_lrc(p)
        sel = self.lst.curselection()
        at = sel[0] if sel else 0
        self.lst.delete(at)
        self.lst.insert(at, "  %s  ♪" % tr.title)
        self.lst.selection_set(at)
        if self.player.track is tr:
            self.player.lrc_lines = tr.lines()
            self._lyr_key = None
            self._draw_lyrics(force=True)
        self.lbl_status.configure(text="已绑定歌词：%s（%d 句）" % (os.path.basename(p), len(tr.lines())))

    def bind_cover(self):
        tr = self._sel_track()
        if not tr:
            return
        p = filedialog.askopenfilename(title="选择封面图片",
                                       filetypes=[("图片", "*.jpg *.jpeg *.png *.bmp")])
        if not p:
            return
        tr.set_cover(p)
        self._lyr_key = None
        if self.player.track is tr:
            self.player.play_index(self.tracks.index(tr),
                                   autoplay=(self.player.state == PLAYING))
        self.lbl_status.configure(text="封面已设置：%s（换曲后推到板子）" % os.path.basename(p))

    # ------------------------------------------------------------ 刷新
    def _tick(self):
        try:
            st = self.player.state
            self.btn_play.configure(text="⏸" if st == PLAYING else "▶",
                                    bg=ACC if st == PLAYING else PANEL2,
                                    fg="#000" if st == PLAYING else FG)
            pos, dur = self.player.pos_ms, self.player.duration_ms
            self._draw_progress(pos, dur)
            self._draw_lyrics(pos)
            dev = find_port()
            now = time.monotonic()
            if now - self._conflict_at > 2.0:      # WMI 查询较重，2 秒一次
                self._conflict_at = now
                self._conflict = port_conflicts()
            self._last_dev = dev
            txt = ("设备：%s ●" % dev) if dev else "设备：未连接 ○"
            if self._conflict:
                txt += "（串口被占用）"
            if txt != self._dev_txt:
                self._dev_txt = txt
                self.lbl_dev.configure(
                    text=txt,
                    fg=("#ff6b6b" if self._conflict else (ACC if dev else MUT)))
        except Exception:
            pass
        self.root.after(80, self._tick)

    def _draw_progress(self, pos, dur):
        c = self.cv_prog
        w = max(1, c.winfo_width())
        c.delete("all")
        y = 13
        c.create_rectangle(0, y - 3, w, y + 3, fill=PANEL2, outline="")
        if dur > 0:
            x = int(w * min(1.0, pos / float(dur)))
            c.create_rectangle(0, y - 3, x, y + 3, fill=ACC, outline="")
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=ACC, outline="")
        c.create_text(6, y, text=fmt(pos), fill=FG, anchor="w", font=self.f_ui)
        c.create_text(w - 6, y, text=fmt(dur), fill=MUT, anchor="e", font=self.f_ui)

    def _active_index(self, pos):
        idx = -1
        for i, (ms, _t) in enumerate(self.player.lrc_lines):
            if ms <= pos:
                idx = i
            else:
                break
        return idx

    def _draw_lyrics(self, pos=0, force=False):
        lines = self.player.lrc_lines
        idx = self._active_index(pos)
        key = (idx, len(lines), self.cv_lyr.winfo_height())
        if not force and key == self._lyr_key:
            return
        self._lyr_key = key

        c = self.cv_lyr
        c.delete("all")
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())
        if not lines:
            c.create_text(w // 2, h // 2, text="没有歌词\n（顶层「绑定歌词」载入 .lrc）",
                          fill=MUT, font=self.f_sub, justify="center")
            return

        rows = 7
        start = max(0, idx - rows // 2) if idx >= 0 else 0
        start = min(start, max(0, len(lines) - rows))
        y = h // (rows + 1)
        step = h // (rows + 1)
        for k in range(rows):
            i = start + k
            if i >= len(lines):
                break
            cur = (i == idx)
            c.create_text(w // 2, y + k * step, text=lines[i][1],
                          fill=HILITE if cur else MUT,
                          font=self.f_lyric_cur if cur else self.f_lyric,
                          width=w - 24, justify="center")

    # ------------------------------------------------------------ 串口
    def release_port(self):
        """一键结束旧的 host_cdc_sender 推流进程，让播放线程自动重连。"""
        killed = self.player.release_port()
        if killed:
            desc = "\n".join(
                "PID %d  %s" % (pid, (cmd.split("python.exe")[-1] or cmd)[:80].strip())
                for pid, cmd in killed)
            messagebox.showinfo(
                "已释放串口",
                "已结束占用 COM 口的旧推流程序：\n\n%s\n\n"
                "播放器会在 1~2 秒内自动重连；若进度条仍不动，双击列表里的歌。" % desc)
            self.lbl_status.configure(text="已释放串口，正在重连…")
        else:
            messagebox.showinfo(
                "没有发现旧推流程序",
                "没找到 host_cdc_sender.py / play.bat 的残留进程。\n\n"
                "若状态栏仍提示「拒绝访问」，依次检查：\n"
                "· 串口调试助手 / SSCOM / XCOM / Putty 是否开着\n"
                "· 是否开了两个桌面播放器\n"
                "· 设备管理器里该 COM 口是否有感叹号（重插 USB_SLAVE 线）")
            self.lbl_status.configure(text="未发现旧推流进程；请检查其它串口工具")

    # ------------------------------------------------------------ 关闭
    def _on_close(self):
        try:
            self.player.shutdown()
        finally:
            self.root.destroy()


# ---------------------------------------------------------------- 自检
def selftest():
    ok = True

    def chk(name, cond, extra=""):
        nonlocal ok
        print(("  [OK]   " if cond else "  [FAIL] ") + name + ("  " + extra if extra else ""))
        ok = ok and cond

    print("== 环境 ==")
    ff = T.find_ffmpeg()
    chk("ffmpeg", bool(ff), str(ff))
    lst = T.parse_lrc("[00:01.00]第一句\n[00:03.50]第二句\n{\"t\":0}\n[00:05.00]制作人：xxx\n")
    chk("LRC 解析（丢 JSON/版权行）", len(lst) == 2, str(lst))
    sc = T.scale_lrc("[00:10.00]a\n[01:00.00]b", 2.0)
    chk("LRC 时间缩放 2x", "[00:05.00]a" in sc and "[00:30.00]b" in sc, sc.replace("\n", " | "))

    print("== 转码 ==")
    if ff:
        import tempfile
        import wave as _w
        src = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Tools", "t_1k_m6.wav")
        if os.path.isfile(src):
            for sp, kp in ((1.0, True), (1.5, True), (1.5, False)):
                t0 = __import__("time").monotonic()
                p = T.render_segment(ff, src, 0, sp, kp)
                with _w.open(p, "rb") as w:
                    okfmt = (w.getframerate() == 44100 and w.getnchannels() == 2
                             and w.getsampwidth() == 2)
                    n = w.getnframes()
                os.remove(p)
                chk("render %.1fx keep_pitch=%s -> 44.1k/立体声/16bit" % (sp, kp), okfmt,
                    "%d 帧 %.2fs" % (n, __import__("time").monotonic() - t0))
        else:
            print("  (跳过：没有 Tools/t_1k_m6.wav)")

    print("== 控制帧（假串口，不动真设备）==")
    try:
        import core_device as D

        class FakeSer(object):
            def __init__(self):
                self.buf = bytearray()
                self.baudrate = D.BAUD_AUDIO
                self.is_open = True
                self.bauds = []

            def write(self, d):
                self.buf += d

            def close(self):
                self.is_open = False

        dev = D.Device.__new__(D.Device)
        dev.ser = FakeSer()
        dev.port = "FAKE"
        dev.push_meta(3, "忘不掉的你", "h3R3")
        b = bytes(dev.ser.buf)
        chk("SONG 帧头 'ATK'+type+len", b[:4] == b"ATK\x01" and b[4] | (b[5] << 8) == len(b) - 6,
            "%d 字节" % len(b))
        t = "忘不掉的你".encode("gbk")
        chk("SONG 载荷（idx/title/artist）", b[6] == 3 and b[7] == len(t) and t in b)
        dev.ser.buf = bytearray()
        dev.push_lrc("[00:01.00]a\n" * 60)
        frames = bytes(dev.ser.buf).count(b"ATK")
        chk("LRC 分块（每帧 <= 480 字节 + 结束帧）",
            frames >= 2 and bytes(dev.ser.buf)[-1:] == b"\x00"
            and all(len(x) <= 486 for x in bytes(dev.ser.buf).split(b"ATK")[1:]))
        chk("设备发现", True, str(find_port()))
    except Exception as e:
        chk("控制帧测试", False, repr(e))


    print("结果：" + ("全部通过" if ok else "有失败项"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
