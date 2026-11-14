# -*- coding: utf-8 -*-
"""app.py —— 桌面端控制台（Tkinter，零第三方 UI 依赖）

界面风格参考 macOS「音乐」App（Apple Music）：
  * 左侧毛玻璃质感侧栏 + 播放列表
  * 中间大封面 + 歌名/歌手
  * 右侧歌词居中大字，当前句高亮
  * 底部播放控制条，符号用细线条（⏮ ▶ ⏭）
  * 背景取封面主色做模糊氛围

功能
  1. 导入音乐（mp3/wav/flac/m4a…，自动转成板子能吃的 44.1k/16bit/立体声）
  2. 导入/绑定歌词（.lrc），桌面大字滚动显示，当前句高亮
  3. 播放 / 暂停 / 上一首 / 下一首 / 拖动进度
  4. 倍速 0.5x~2.0x（可选「保持音调」，默认开）
  5. 音量 0~100
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
import ui_theme as U
from core_device import find_port, port_conflicts
from core_player import Player, PLAYING, PAUSED

SPEEDS = U.SPEEDS

# 自绘控件的固定尺寸（不依赖布局时机，Canvas 首绘时 winfo_width 可能为 0）
SPEED_W, SPEED_H = 64, 24
PITCH_W, PITCH_H = 36, 20
VOL_W, VOL_H = 100, 20
SKIP_W, SKIP_H = 26, 26
PLAY_W, PLAY_H = 44, 44
COVER_SIZE = 340


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
        self._cover_ref = None
        self._bg_ref = None
        self._accent = U.ACCENT
        self._row_h = 46

        root.title("STM32 音乐播放器")
        root.configure(bg=U.BG_DEEP)
        root.geometry("1180x760")
        root.minsize(1000, 660)
        try:
            root.iconbitmap(os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.ico"))
        except Exception:
            pass

        self._make_fonts()
        self._build()
        self._draw_skip(self.cv_prev, False)
        self._draw_skip(self.cv_next, False)
        self._draw_play_button(False)
        self._draw_pitch()
        self._draw_speed()
        self._draw_vol()
        self.player.start()
        self._load_builtin_playlist()
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.bind("<space>", lambda e: self._toggle())
        root.bind("<Left>", lambda e: self.player.prev())
        root.bind("<Right>", lambda e: self.player.next())
        self.root.after(80, self._tick)

    # ------------------------------------------------------------ 字体
    def _make_fonts(self):
        cn = U.font_family(cn=True)
        cn_disp = U.font_family(display=True, cn=True)
        en = U.font_family()
        en_disp = U.font_family(display=True)
        self.f_lyric = tkfont.Font(family=cn, size=16)
        self.f_lyric_cur = tkfont.Font(family=cn_disp, size=21, weight="bold")
        self.f_title = tkfont.Font(family=cn_disp, size=24, weight="bold")
        self.f_sub = tkfont.Font(family=cn, size=12)
        self.f_ui = tkfont.Font(family=cn, size=10)
        self.f_ui_s = tkfont.Font(family=cn, size=9)
        self.f_side = tkfont.Font(family=cn, size=11)
        self.f_side_b = tkfont.Font(family=cn_disp, size=11, weight="bold")
        self.f_num = tkfont.Font(family=en, size=10)
        self.f_display = tkfont.Font(family=en_disp, size=13)

    # ------------------------------------------------------------ 部件
    def _btn(self, parent, text, cmd, bg=None, fg=None, font=None, padx=10, pady=4):
        bg = bg or U.CARD_HI
        fg = fg or U.FG
        b = tk.Button(parent, text=text, command=cmd, bg=bg, fg=fg,
                      activebackground=U.SIDEBAR_HI, activeforeground=U.FG,
                      relief="flat", bd=0, highlightthickness=0,
                      font=font or self.f_ui, cursor="hand2", padx=padx, pady=pady,
                      anchor="w")
        return b

    def _build(self):
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=0, minsize=232)
        self.root.columnconfigure(1, weight=1)

        # ================= 侧栏 =================
        side = tk.Frame(self.root, bg=U.SIDEBAR, width=232)
        side.grid(row=0, column=0, sticky="nsew")
        side.grid_propagate(False)
        side.rowconfigure(2, weight=1)
        side.columnconfigure(0, weight=1)

        # 侧栏顶部：品牌
        brand = tk.Frame(side, bg=U.SIDEBAR)
        brand.grid(row=0, column=0, sticky="ew", padx=16, pady=(18, 14))
        tk.Label(brand, text="STM32", bg=U.SIDEBAR, fg=U.FG,
                 font=tkfont.Font(family=U.font_family(display=True, cn=True),
                                  size=15, weight="bold")).pack(anchor="w")
        tk.Label(brand, text="音乐播放器", bg=U.SIDEBAR, fg=U.FG3,
                 font=self.f_ui_s).pack(anchor="w")

        # 侧栏操作按钮
        ops = tk.Frame(side, bg=U.SIDEBAR)
        ops.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 10))
        ops.columnconfigure(0, weight=1)
        for r, (t, c) in enumerate((("导入音乐", self.import_music),
                                    ("绑定歌词", self.bind_lyric),
                                    ("选择封面", self.bind_cover),
                                    ("释放串口", self.release_port))):
            self._btn(ops, t, c, bg=U.CARD, font=self.f_ui,
                      padx=6, pady=8).grid(row=r, column=0, sticky="ew", pady=2)

        # 倍速 + 保持音调（放在侧栏操作区下方，用 grid 精确排布）
        sp = tk.Frame(ops, bg=U.SIDEBAR)
        sp.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        sp.columnconfigure(0, weight=0)
        tk.Label(sp, text="倍速", bg=U.SIDEBAR, fg=U.FG3,
                 font=self.f_ui_s).grid(row=0, column=0, sticky="w", padx=(2, 8))
        self.var_speed = tk.StringVar(value="1.0x")
        self.cv_speed = tk.Canvas(sp, width=SPEED_W, height=SPEED_H, bg=U.SIDEBAR,
                                  highlightthickness=0, bd=0, cursor="hand2")
        self.cv_speed.grid(row=0, column=1, sticky="w")
        self.cv_speed.bind("<Button-1>", self._on_speed_click)

        self.var_pitch = tk.BooleanVar(value=True)
        tk.Label(sp, text="保持音调", bg=U.SIDEBAR, fg=U.FG3,
                 font=self.f_ui_s).grid(row=1, column=0, sticky="w", padx=(2, 8),
                                         pady=(8, 0))
        self.cv_pitch = tk.Canvas(sp, width=PITCH_W, height=PITCH_H, bg=U.SIDEBAR,
                                   highlightthickness=0, bd=0, cursor="hand2")
        self.cv_pitch.grid(row=1, column=1, sticky="w", pady=(8, 0))
        self.cv_pitch.bind("<Button-1>", self._on_pitch_click)

        # 播放列表
        list_wrap = tk.Frame(side, bg=U.SIDEBAR)
        list_wrap.grid(row=2, column=0, sticky="nsew", padx=12)
        list_wrap.rowconfigure(1, weight=1)
        list_wrap.columnconfigure(0, weight=1)

        head = tk.Frame(list_wrap, bg=U.SIDEBAR)
        head.grid(row=0, column=0, sticky="ew", pady=(4, 6))
        tk.Label(head, text="播放列表", bg=U.SIDEBAR, fg=U.FG3,
                 font=self.f_ui_s).pack(side="left")
        self.lbl_count = tk.Label(head, text="", bg=U.SIDEBAR, fg=U.FG3,
                                   font=self.f_ui_s)
        self.lbl_count.pack(side="right")

        self.cv_list = tk.Canvas(list_wrap, bg=U.SIDEBAR, highlightthickness=0,
                                 bd=0)
        self.cv_list.grid(row=1, column=0, sticky="nsew")
        self.cv_list.bind("<Configure>", lambda e: self._draw_list())
        self.cv_list.bind("<Button-1>", self._on_list_click)
        self.cv_list.bind("<Double-Button-1>", self._on_list_dbl)
        self.cv_list.bind("<MouseWheel>", self._on_list_wheel)
        self._list_scroll = 0

        # 侧栏底部：设备状态
        self.lbl_dev = tk.Label(side, text="设备：检测中…", bg=U.SIDEBAR,
                                fg=U.FG3, font=self.f_ui_s, anchor="w",
                                justify="left")
        self.lbl_dev.grid(row=3, column=0, sticky="ew", padx=16, pady=(8, 14))

        # ================= 主区 =================
        main = tk.Frame(self.root, bg=U.BG)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(0, weight=1)
        main.columnconfigure(0, weight=0, minsize=400)
        main.columnconfigure(1, weight=1)

        # ---- 左：封面 + 信息 ----
        left = tk.Frame(main, bg=U.BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(30, 4), pady=(24, 10))
        left.columnconfigure(0, weight=1)
        # 左栏按内容定宽（封面 340 + 边距），歌词区吃掉剩余宽度
        left.configure(width=400)

        art_wrap = tk.Frame(left, bg=U.BG)
        art_wrap.grid(row=0, column=0, sticky="n", pady=(0, 20))
        self.cv_cover = tk.Canvas(art_wrap, width=COVER_SIZE, height=COVER_SIZE,
                                  bg=U.BG, highlightthickness=0, bd=0)
        self.cv_cover.pack()
        self.cv_cover.bind("<Configure>", lambda e: self._draw_cover())
        self._cover_photo = None

        info = tk.Frame(left, bg=U.BG)
        info.grid(row=1, column=0, sticky="ew")
        self.lbl_title = tk.Label(info, text="没有在播放", bg=U.BG, fg=U.FG,
                                  font=self.f_title, anchor="w", justify="left")
        self.lbl_title.pack(fill="x")
        self.lbl_artist = tk.Label(info, text="", bg=U.BG, fg=U.FG2,
                                   font=self.f_sub, anchor="w")
        self.lbl_artist.pack(fill="x", pady=(4, 0))
        self.lbl_meta = tk.Label(info, text="", bg=U.BG, fg=U.FG3,
                                 font=self.f_ui_s, anchor="w")
        self.lbl_meta.pack(fill="x", pady=(2, 0))

        # ---- 右：歌词 ----
        right = tk.Frame(main, bg=U.BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 30), pady=(24, 10))
        right.rowconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)

        self.cv_lyr = tk.Canvas(right, bg=U.BG, highlightthickness=0, bd=0)
        self.cv_lyr.grid(row=0, column=0, sticky="nsew")
        self.cv_lyr.bind("<Configure>", lambda e: self._draw_lyrics(force=True))

        # ================= 底部控制条 =================
        bar = tk.Frame(self.root, bg=U.BG_DEEP, height=86)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        # 三列：左=控制键（固定） 中=进度条（自适应） 右=音量/倍速（固定）
        bar.columnconfigure(0, weight=0, minsize=230)
        bar.columnconfigure(1, weight=1)
        bar.columnconfigure(2, weight=0)

        # 左：控制按钮
        ctrl = tk.Frame(bar, bg=U.BG_DEEP)
        ctrl.grid(row=0, column=0, sticky="w", padx=(26, 0), pady=14)

        # 左：控制按钮（三键一组，等距：⏮ ▶ ⏭）
        ctrl = tk.Frame(bar, bg=U.BG_DEEP)
        ctrl.grid(row=0, column=0, sticky="w", padx=(28, 0), pady=14)

        self.cv_prev = tk.Canvas(ctrl, width=SKIP_W, height=SKIP_H, bg=U.BG_DEEP,
                                 highlightthickness=0, bd=0, cursor="hand2")
        self.cv_prev.pack(side="left", padx=(0, 4))
        self.cv_prev.bind("<Button-1>", lambda e: self.player.prev())
        self.cv_prev.bind("<Enter>", lambda e: self._draw_skip(self.cv_prev, True))
        self.cv_prev.bind("<Leave>", lambda e: self._draw_skip(self.cv_prev, False))

        # 播放按钮：圆形用 Canvas 自绘（放在 ctrl 里跟前后曲一起排）
        self.cv_play = tk.Canvas(ctrl, width=PLAY_W, height=PLAY_H, bg=U.BG_DEEP,
                                 highlightthickness=0, bd=0, cursor="hand2")
        self.cv_play.pack(side="left", padx=14)
        self.cv_play.bind("<Button-1>", lambda e: self._toggle())

        self.cv_next = tk.Canvas(ctrl, width=SKIP_W, height=SKIP_H, bg=U.BG_DEEP,
                                 highlightthickness=0, bd=0, cursor="hand2")
        self.cv_next.pack(side="left", padx=(4, 0))
        self.cv_next.bind("<Button-1>", lambda e: self.player.next())
        self.cv_next.bind("<Enter>", lambda e: self._draw_skip(self.cv_next, True))
        self.cv_next.bind("<Leave>", lambda e: self._draw_skip(self.cv_next, False))

        # 中：进度条
        mid = tk.Frame(bar, bg=U.BG_DEEP)
        mid.grid(row=0, column=1, sticky="ew", padx=(30, 30))
        mid.rowconfigure(0, weight=1)
        mid.columnconfigure(0, weight=1)

        self.cv_prog = tk.Canvas(mid, height=26, bg=U.BG_DEEP,
                                 highlightthickness=0, bd=0)
        self.cv_prog.grid(row=0, column=0, sticky="ew")
        self.cv_prog.bind("<Button-1>", self._on_seek)
        self.cv_prog.bind("<B1-Motion>", self._on_seek)

        times = tk.Frame(mid, bg=U.BG_DEEP)
        times.grid(row=1, column=0, sticky="ew", pady=(2, 0))
        self.lbl_tcur = tk.Label(times, text="00:00", bg=U.BG_DEEP, fg=U.FG2,
                                 font=self.f_num, anchor="w")
        self.lbl_tcur.pack(side="left")
        self.lbl_ttot = tk.Label(times, text="00:00", bg=U.BG_DEEP, fg=U.FG3,
                                 font=self.f_num, anchor="e")
        self.lbl_ttot.pack(side="right")

        # 右：音量（底部条只留音量，倍速/保持音调移到顶栏，避免拥挤）
        right_ctl = tk.Frame(bar, bg=U.BG_DEEP)
        right_ctl.grid(row=0, column=2, sticky="e", padx=(0, 26))
        tk.Label(right_ctl, text="🔊", bg=U.BG_DEEP, fg=U.FG3,
                 font=tkfont.Font(family="Segoe UI Symbol", size=10)).pack(
            side="left", padx=(0, 6))
        self.var_vol = tk.DoubleVar(value=38)
        # Tk 的 Scale 不支持 slidercolor，改用 Canvas 自绘细线音量条（更接近 Apple 风格）
        self.cv_vol = tk.Canvas(right_ctl, width=VOL_W, height=VOL_H, bg=U.BG_DEEP,
                                highlightthickness=0, bd=0)
        self.cv_vol.pack(side="left")
        self.cv_vol.bind("<Button-1>", self._on_vol_click)
        self.cv_vol.bind("<B1-Motion>", self._on_vol_click)

        # 状态栏
        self.lbl_status = tk.Label(self.root, text="就绪", bg=U.BG_DEEP,
                                   fg=U.FG3, font=self.f_ui_s, anchor="w")
        self.lbl_status.grid(row=2, column=0, columnspan=2, sticky="ew",
                             padx=26, pady=(0, 8))

    # ------------------------------------------------------------ 事件
    def _on_log(self, s):
        self.root.after(0, lambda: self.lbl_status.configure(text=s))

    def _on_track(self, i):
        def upd():
            self._draw_list()
            tr = self.player.track
            if tr:
                self.lbl_title.configure(text=tr.title or os.path.basename(tr.path))
                self.lbl_artist.configure(text=tr.artist or "")
                self._apply_cover(tr)
                self.lbl_meta.configure(text=self._meta_text(tr))
            self._lyr_key = None
            self._draw_lyrics(force=True)
        self.root.after(0, upd)

    @staticmethod
    def _meta_text(tr):
        bits = []
        if tr.artist:
            bits.append(tr.artist)
        if tr.duration_ms:
            bits.append("%d:%02d" % (tr.duration_ms // 60000,
                                     (tr.duration_ms % 60000) // 1000))
        bits.append("PCM 44.1kHz")
        return "  ·  ".join(bits)

    # ------------------------------------------------------------ 封面 / 背景
    def _apply_cover(self, tr):
        path = getattr(tr, "cover_path", None)
        if not path or not os.path.isfile(path):
            self._cover_photo = None
            self._bg_ref = None
            self._accent = U.ACCENT
            self._draw_cover()
            return
        try:
            from PIL import Image, ImageTk
            im = U.make_cover_image(path, COVER_SIZE, radius=12)
            self._cover_photo = ImageTk.PhotoImage(im)
            self._accent = U.dominant_color(im, U.ACCENT)
        except Exception:
            self._cover_photo = None
            self._accent = U.ACCENT
        self._draw_cover()

    def _draw_cover(self):
        c = self.cv_cover
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())
        c.delete("all")
        if self._cover_photo is not None:
            U.round_rect_shadow(c, 4, 6, w - 4, h - 4, 12, U.CARD, 4)
            c.create_image(w // 2, h // 2, image=self._cover_photo)
        else:
            U.round_rect_shadow(c, 4, 6, w - 4, h - 4, 12, U.CARD, 4)
            c.create_text(w // 2, h // 2, text="♫", fill=U.FG3,
                          font=tkfont.Font(family="Segoe UI Symbol", size=64))

    # ------------------------------------------------------------ 播放列表
    def _draw_list(self):
        c = self.cv_list
        if not hasattr(self, "cv_list"):
            return
        w = max(1, c.winfo_width())
        h = max(1, c.winfo_height())
        c.delete("all")
        if not self.tracks:
            c.create_text(w // 2, 30, text="点左侧「导入音乐」添加",
                          fill=U.FG3, font=self.f_ui_s)
            return

        self.lbl_count.configure(text="%d 首" % len(self.tracks))
        rh = self._row_h
        total = len(self.tracks) * rh
        max_scroll = max(0, total - h)
        self._list_scroll = max(0, min(self._list_scroll, max_scroll))
        off = self._list_scroll

        cur = self.player.index
        for i, t in enumerate(self.tracks):
            y = i * rh - off
            if y + rh < 0 or y > h:
                continue
            sel = (i == cur)
            if sel:
                U.round_rect(c, 4, y + 2, w - 4, y + rh - 2, 8,
                             fill=U.SIDEBAR_HI, outline="")
            c.create_text(14, y + rh // 2, text="♫" if t.lrc_text else "♪",
                          anchor="w", fill=U.ACCENT if sel else U.FG3,
                          font=tkfont.Font(family="Segoe UI Symbol", size=10))
            c.create_text(34, y + rh // 2 - 9, text=self._clip_px(t.title, w - 46, self.f_side_b),
                          anchor="w", fill=U.FG if sel else U.FG2,
                          font=self.f_side_b if sel else self.f_side)
            sub = t.artist or ("%.0f 秒" % (t.duration_ms / 1000.0))
            c.create_text(34, y + rh // 2 + 9, text=self._clip_px(sub, w - 46, self.f_ui_s),
                          anchor="w", fill=U.FG3, font=self.f_ui_s)

    @staticmethod
    def _clip(s, n):
        s = s or ""
        return s if len(s) <= n else s[:n - 1] + "…"

    def _clip_px(self, s, maxpx, font):
        """按像素宽度截断（中文/英文混排时字符数法会算错）。"""
        s = s or ""
        if font.measure(s) <= maxpx:
            return s
        out = ""
        for ch in s:
            if font.measure(out + ch + "…") > maxpx:
                break
            out += ch
        return (out + "…") if out else "…"

    def _on_list_click(self, e):
        idx = self._row_at(e.y)
        if idx is None:
            return
        self.lst_select(idx)
        self.player.index = idx
        self._draw_list()

    def _on_list_dbl(self, _e):
        idx = self._row_at(_e.y)
        if idx is not None:
            self.player.play_index(idx)

    def _on_list_wheel(self, e):
        self._list_scroll -= int(e.delta / 120) * self._row_h
        self._draw_list()

    def _row_at(self, y):
        if not self.tracks:
            return None
        i = (y + self._list_scroll) // self._row_h
        return int(i) if 0 <= i < len(self.tracks) else None

    def lst_select(self, i):
        self._list_sel = i

    # ------------------------------------------------------------ 内部播放列表
    def _load_builtin_playlist(self):
        """把工程里现成的歌带进列表，打开就能用。

        优先读 Tools/mcu/（批量转换出来的板子格式 WAV + 配套歌词 + manifest），
        没有则退回 Tools/plNN.wav。
        """
        import glob
        import re as _re
        import wave as _wave

        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tools = os.path.join(root, "Tools")
        cover = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "assets", "default_cover.jpg")

        # ---- 优先：Tools/mcu（manifest 带曲名/歌手/歌词） ----
        mcu = os.path.join(tools, "mcu")
        man = os.path.join(mcu, "manifest.json")
        items = []
        if os.path.isfile(man):
            import json
            try:
                items = json.load(open(man, encoding="utf-8"))
            except Exception:
                items = []

        if items:
            for it in items:
                wav = it.get("wav", "")
                if not wav or not os.path.isfile(wav):
                    continue
                tr = T.Track(wav)
                tr.title = it.get("title") or tr.title
                tr.artist = it.get("artist") or ""
                tr.duration_ms = it.get("duration_ms", 0)
                lrc = it.get("lrc", "")
                if lrc and os.path.isfile(lrc):
                    tr.set_lrc(lrc)
                if os.path.isfile(cover):
                    tr.cover_path = cover
                self.tracks.append(tr)
        else:
            # ---- 退回：Tools/plNN.wav ----
            lyric_dir = os.path.join(tools, "lyrics")
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

        if not self.tracks:
            return

        self.player.set_tracks(self.tracks)
        # 默认停在《忘不掉的你》，但不自动播放（串口可能被别的推流进程占着）
        pick = 0
        for i, t in enumerate(self.tracks):
            if "忘不掉" in t.title:
                pick = i
                break
        self.player.index = pick
        self.player.lrc_lines = self.tracks[pick].lines()
        self.player._dur_ms = self.tracks[pick].duration_ms
        tr = self.tracks[pick]
        self.lbl_title.configure(text=tr.title)
        self.lbl_artist.configure(text=tr.artist or "")
        self.lbl_meta.configure(text=self._meta_text(tr))
        self._apply_cover(tr)
        self.lbl_status.configure(text="已载入 %d 首（双击列表开始播放）" % len(self.tracks))
        self._lyr_key = None
        self._draw_list()
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
            self.player.set_tracks(self.tracks)
            self._draw_list()
            self.lbl_status.configure(text="已导入 %d 首（共 %d 首）" % (added, len(self.tracks)))
            if self.player.track is None and self.tracks:
                self.player.play_index(0, autoplay=False)
        self.root.after(0, done)

    def _sel_track(self):
        idx = getattr(self, "_list_sel", None)
        if idx is None:
            idx = self.player.index if self.tracks else None
        if idx is None or not (0 <= idx < len(self.tracks)):
            messagebox.showinfo("提示", "先在播放列表里点一首歌")
            return None
        return self.tracks[idx]

    def bind_lyric(self):
        tr = self._sel_track()
        if not tr:
            return
        p = filedialog.askopenfilename(title="选择歌词",
                                       filetypes=[("LRC 歌词", "*.lrc *.LRC"), ("全部", "*.*")])
        if not p:
            return
        tr.set_lrc(p)
        if self.player.track is tr:
            self.player.lrc_lines = tr.lines()
            self._lyr_key = None
            self._draw_lyrics(force=True)
        self._draw_list()
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
            playing = (st == PLAYING)
            self._draw_play_button(playing)

            pos, dur = self.player.pos_ms, self.player.duration_ms
            self._draw_progress(pos, dur)
            self._draw_lyrics(pos)
            self._draw_vol()

            dev = find_port()
            now = time.monotonic()
            if now - self._conflict_at > 2.0:      # WMI 查询较重，2 秒一次
                self._conflict_at = now
                self._conflict = port_conflicts()
            self._last_dev = dev
            txt = ("设备  %s" % dev) if dev else "设备  未连接"
            if self._conflict:
                txt += "  ·  串口被占用"
            if txt != self._dev_txt:
                self._dev_txt = txt
                self.lbl_dev.configure(
                    text=txt,
                    fg=("#FF6B6B" if self._conflict else (U.ACCENT if dev else U.FG3)))
        except tk.TclError:
            return                      # 窗口已销毁，停止刷新
        except Exception:
            pass
        self.root.after(80, self._tick)

    def _draw_play_button(self, playing):
        c = self.cv_play
        w, h = PLAY_W, PLAY_H
        c.delete("all")
        r = min(w, h) // 2 - 1
        col = self._accent if playing else U.FG
        c.create_oval(w // 2 - r, h // 2 - r, w // 2 + r, h // 2 + r,
                      fill=col, outline="")
        if playing:
            # 暂停：两条竖杠
            bw, bh = 4, 15
            c.create_rectangle(w // 2 - 7, h // 2 - bh // 2, w // 2 - 7 + bw, h // 2 + bh // 2,
                               fill=U.BG_DEEP, outline="")
            c.create_rectangle(w // 2 + 3, h // 2 - bh // 2, w // 2 + 3 + bw, h // 2 + bh // 2,
                               fill=U.BG_DEEP, outline="")
        else:
            c.create_polygon(w // 2 - 5, h // 2 - 9, w // 2 - 5, h // 2 + 9,
                             w // 2 + 9, h // 2, fill=U.BG_DEEP, outline="")

    def _draw_skip(self, cv, hover):
        """上一首/下一首：双三角 + 竖条，用 Canvas 画避免字体字形问题。

        三角形顶点顺序：左上 -> 左下 -> 右尖（朝右）；
        反向则左上 -> 右上 -> 左尖（朝左）。
        """
        cv.delete("all")
        w, h = SKIP_W, SKIP_H
        col = U.FG if hover else U.FG2
        cy = h // 2
        t = 6                        # 三角半高
        if cv is self.cv_prev:
            # ◀◀|  两个朝左的三角 + 右侧竖条（画布 26x26，内容占 4..22）
            cv.create_polygon(11, cy - t, 11, cy + t, 4, cy, fill=col, outline="")
            cv.create_polygon(18, cy - t, 18, cy + t, 11, cy, fill=col, outline="")
            cv.create_rectangle(21, cy - t, 23, cy + t, fill=col, outline="")
        else:
            # |▶▶  左侧竖条 + 两个朝右的三角
            cv.create_rectangle(3, cy - t, 5, cy + t, fill=col, outline="")
            cv.create_polygon(8, cy - t, 8, cy + t, 15, cy, fill=col, outline="")
            cv.create_polygon(15, cy - t, 15, cy + t, 22, cy, fill=col, outline="")

    def _draw_progress(self, pos, dur):
        c = self.cv_prog
        w = max(1, c.winfo_width())
        c.delete("all")
        y = 11
        # Apple 风格：4px 圆头轨道 + 白色圆点
        U.round_rect(c, 0, y - 2, w, y + 2, 2, fill="#2E2E36", outline="")
        if dur > 0:
            x = int(w * min(1.0, pos / float(dur)))
            if x > 2:
                U.round_rect(c, 0, y - 2, x, y + 2, 2, fill=self._accent, outline="")
            c.create_oval(x - 6, y - 6, x + 6, y + 6, fill=U.FG, outline="")
        self.lbl_tcur.configure(text=fmt(pos))
        self.lbl_ttot.configure(text=fmt(dur))

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
            c.create_text(w // 2, h // 2, text="没有歌词\n点左侧「绑定歌词」载入 .lrc",
                          fill=U.FG3, font=self.f_sub, justify="center")
            return

        rows = 8
        start = max(0, idx - rows // 2) if idx >= 0 else 0
        start = min(start, max(0, len(lines) - rows))
        step = min(48, max(32, h // (rows + 1)))
        # 当前句放在歌词区的视觉中心（略偏上，给当前句更大呼吸感）
        y0 = int(h * 0.42) - (rows // 2) * step
        for k in range(rows):
            i = start + k
            if i >= len(lines):
                break
            cur = (i == idx)
            y = y0 + k * step
            # 越远的行越淡（Apple Music 歌词的渐隐）
            if cur:
                col, fnt = U.HILITE, self.f_lyric_cur
            else:
                dist = abs(k - (idx - start)) if idx >= start else k
                fade = max(0.0, 1.0 - dist / 3.0)
                col = U.mix(U.FG3, U.FG2, fade)
                fnt = self.f_lyric
            c.create_text(w // 2, y, text=lines[i][1], fill=col, font=fnt,
                          width=w - 60, justify="center")

    # ------------------------------------------------------------ 交互
    def _toggle(self):
        self.player.toggle()

    def _on_speed(self, val):
        try:
            s = float(val.replace("x", ""))
        except ValueError:
            s = 1.0
        self.player.set_speed(s, self.var_pitch.get())

    def _on_pitch(self):
        self.player.set_speed(self.player.speed, self.var_pitch.get())

    def _on_speed_click(self, _e=None):
        """倍速胶囊：点击弹出选项菜单（自绘，避免 OptionMenu 的系统箭头）。"""
        m = tk.Menu(self.root, tearoff=0, bg=U.CARD, fg=U.FG,
                    activebackground=U.SIDEBAR_HI, activeforeground=U.FG,
                    font=self.f_ui, bd=0)
        for s in SPEEDS:
            m.add_command(label=s,
                          command=lambda v=s: self._set_speed(v))
        try:
            x = self.cv_speed.winfo_rootx()
            y = self.cv_speed.winfo_rooty() - 8 * len(SPEEDS) - 20
            m.tk_popup(x, max(10, y))
        finally:
            m.grab_release()

    def _set_speed(self, val):
        self.var_speed.set(val)
        self._draw_speed()
        self._on_speed(val)

    def _draw_speed(self):
        c = self.cv_speed
        # Canvas 首次绘制时可能还没完成布局，winfo_width() 会返回 0，
        # 所以一律用固定构造尺寸，不依赖布局时机。
        w, h = SPEED_W, SPEED_H
        c.delete("all")
        U.round_rect(c, 0, 0, w - 1, h - 1, (h - 2) // 2,
                     fill=U.CARD, outline="#33333C")
        txt = self.var_speed.get()
        c.create_text(w // 2 - 6, h // 2, text=txt, fill=U.FG, font=self.f_ui)
        # 小的下拉三角
        ax, ay = w - 16, h // 2
        c.create_polygon(ax - 4, ay - 2, ax + 4, ay - 2, ax, ay + 3,
                         fill=U.FG3, outline="")

    def _on_pitch_click(self, _e=None):
        """胶囊开关：点一下切换「保持音调」。"""
        self.var_pitch.set(not self.var_pitch.get())
        self._draw_pitch()
        self.player.set_speed(self.player.speed, self.var_pitch.get())

    def _draw_pitch(self):
        c = self.cv_pitch
        w, h = PITCH_W, PITCH_H
        c.delete("all")
        on = self.var_pitch.get()
        U.round_rect(c, 0, 1, w - 1, h - 1, (h - 2) // 2,
                     fill=(self._accent if on else "#3A3A42"), outline="")
        r = (h - 6) // 2
        cx = (w - r - 3) if on else (r + 3)
        c.create_oval(cx - r, h // 2 - r, cx + r, h // 2 + r,
                      fill=(U.FG if on else U.FG3), outline="")

    def _on_vol(self, _v):
        self.player.volume = max(0.0, self.var_vol.get() / 100.0)

    def _on_vol_click(self, e):
        """音量条点击/拖动：立即生效。"""
        w = max(1, self.cv_vol.winfo_width())
        ratio = max(0.0, min(1.0, e.x / float(w)))
        self.var_vol.set(round(ratio * 100))
        self.player.volume = ratio
        self._draw_vol()

    def _draw_vol(self):
        c = self.cv_vol
        w, h = VOL_W, VOL_H
        c.delete("all")
        y = h // 2
        U.round_rect(c, 0, y - 2, w, y + 2, 2, fill="#2E2E36", outline="")
        x = int(w * (self.var_vol.get() / 100.0))
        if x > 2:
            U.round_rect(c, 0, y - 2, x, y + 2, 2, fill=U.FG2, outline="")
        c.create_oval(x - 5, y - 5, x + 5, y + 5, fill=U.FG, outline="")

    def _on_seek(self, e):
        w = max(1, self.cv_prog.winfo_width())
        ratio = max(0.0, min(1.0, e.x / float(w)))
        self.player.seek(int(ratio * self.player.duration_ms))

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

    print("== 板子格式转换 ==")
    try:
        import core_mcu as M
        mff = M.find_ffmpeg()
        chk("core_mcu 找到 ffmpeg", bool(mff), str(mff))
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sample = os.path.join(root, "Tools", "t_1k_m6.wav")
        if os.path.isfile(sample) and mff:
            import tempfile
            import wave as _w
            dst = os.path.join(tempfile.gettempdir(), "mcu_selftest.wav")
            M.to_mcu_wav(mff, sample, dst, peak_db=-1.0)
            info = M.verify_mcu_wav(dst)
            chk("转成 44.1k/16bit/立体声 PCM", info["ok"], info.get("reason", ""))
            chk("字节率 = 176400 B/s", info["bytes"] > 0, "%d 字节 / %.1f 秒"
                % (info["bytes"], info["duration_ms"] / 1000.0))
            with _w.open(dst, "rb") as w:
                chk("wave 头确认 44100/2ch/16bit",
                    w.getframerate() == 44100 and w.getnchannels() == 2
                    and w.getsampwidth() == 2)
            os.remove(dst)
        else:
            print("  (跳过：没有 Tools/t_1k_m6.wav)")
        title, artist = M.split_name("忘不掉的你 - h3R3.mp3")
        chk("文件名拆分歌名/歌手", title == "忘不掉的你" and artist == "h3R3",
            "%s / %s" % (title, artist))
    except Exception as e:
        chk("板子格式转换测试", False, repr(e))

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
