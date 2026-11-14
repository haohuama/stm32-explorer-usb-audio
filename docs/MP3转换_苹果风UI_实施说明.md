# MP3 转换 + 桌面端苹果风 UI 改造 —— 实施说明

日期：2026-11-14
范围：`DesktopPlayer/`（新增 `core_mcu.py`、`ui_theme.py`，重写 `app.py` 界面层）
新增：`Tools/convert_mp3.py`

---

## 一、MP3 → 单片机可识别格式

### 1.1 为什么必须转

板子端 I2S 时钟固定，**永远以 176400 B/s 消费 PCM**，也就是：

```
44100 Hz × 2 声道 × 16 bit = 176400 B/s
```

| 格式 | 板子能吃吗 | 原因 |
|---|---|---|
| mp3 / flac / m4a / opus | ❌ | MCU 上没有解码器，只有裸 PCM 通道 |
| wav 48kHz | ❌ | 采样率不对，播放速度会错 9% |
| wav 44.1k 单声道 | ❌ | 设备按 2 声道取样，会变速+错位 |
| **wav 44.1k/16bit/立体声** | ✅ | 唯一正确格式 |

`host_cdc_sender.py` 也明确只接受这一种（`check_wav()` 会校验并直接报错）。

### 1.2 新增 `DesktopPlayer/core_mcu.py`

转换核心 + 校验：

| 函数 | 作用 |
|---|---|
| `to_mcu_wav(ffmpeg, src, dst, peak_db=-1.0, normalize=False)` | 转码 + 峰值限制 + 格式校验 |
| `verify_mcu_wav(path)` | 返回 `{ok, channels, sampwidth, framerate, frames, duration_ms, bytes}` |
| `split_name(path)` | `"歌名 - 歌手.mp3"` → `(歌名, 歌手)` |
| `gbk_safe(s)` | 裁掉 GBK 编不了的字符（板子屏上是 GBK 字节） |
| `find_lrc(folder, stem)` | 同目录找同名 `.lrc`（大小写不敏感） |
| `scan_audio(folder)` | 列出目录里的音频文件 |

**默认带 -1 dBFS 峰值限制器**（`alimiter`）。原因：之前实测过数字端贴顶样本只占 0.002%，
但"炸"的不是数字削波，而是**模拟端满档过载**。mp3 源文件常常已经削顶，
限制器能把这类片段拉回来一点。

### 1.3 新增 `Tools/convert_mp3.py`（批量命令行）

```bat
:: 扫描默认下载目录，转换所有 mp3
py Tools/convert_mp3.py

:: 指定目录
py Tools/convert_mp3.py --src "C:/Users/mhh20/Downloads"

:: 只看会做什么，不写文件
py Tools/convert_mp3.py --dry-run

:: 强制重转 / 不配歌词
py Tools/convert_mp3.py --force
py Tools/convert_mp3.py --no-lrc

:: 峰值限制与响度归一
py Tools/convert_mp3.py --peak -1.0        :: 默认
py Tools/convert_mp3.py --peak 0 --normalize
```

产物：

```
Tools/mcu/plNN.wav       44.1k/16bit/立体声 PCM
Tools/mcu/plNN.lrc       配套歌词（清洗过：丢 JSON 头/版权行）
Tools/mcu/manifest.json  清单（曲名/歌手/时长/源文件路径）
```

歌词清洗规则与 `Tools/clean_lrc.py` 一致：丢 `{"t":...}` JSON 头、丢「制作人/编曲/统筹」等
版权行、丢含「：」的行、时间统一成 `mm:ss.xx`。

### 1.4 实测结果（11 首，全成功）

| # | 源文件 | 时长 | 体积 | 歌词 |
|---|---|---|---|---|
| 1 | Scared 2 Be Lonely - Lil Tjay.mp3 | 182.2s | 30.7 MB | 131 行 |
| 2 | 唯一 - G.E.M.邓紫棋.mp3 | 253.7s | 42.7 MB | 22 行 |
| 3 | 坠落 - The Oddity.mp3 | 276.0s | 46.4 MB | — |
| 4 | 坠落 - 蔡健雅.mp3 | 250.1s | 42.1 MB | — |
| 5 | 多想在平庸的生活拥抱你 - 隔壁老樊.mp3 | 269.9s | 45.4 MB | — |
| 6 | 忘不掉的你 - h3R3.mp3 | 172.2s | 29.0 MB | 52 行 |
| 7 | 拉过勾的 - 陆虎.mp3 | 218.7s | 36.8 MB | — |
| 8 | 江南 - 林俊杰.mp3 | 267.9s | 45.1 MB | 43 行 |
| 9 | 泡沫 - Swang多雷.mp3 | 190.2s | 32.0 MB | 53 行 |
| 10 | 爱错(Live) - 王力宏.mp3 | 243.5s | 41.0 MB | — |
| 11 | 还是会想你 - 林达浪、h3R3.mp3 | 190.1s | 32.0 MB | — |

全部 11 个 wav 用 `wave` 模块复验：**44100 / 2ch / 16bit** ✓，合计 423 MB。

---

## 二、桌面端 UI 苹果风改造

参考 macOS Sonoma「音乐」App（Apple Music）的视觉语言。

### 2.1 新增 `DesktopPlayer/ui_theme.py`

| 内容 | 说明 |
|---|---|
| 配色 | `BG_DEEP #0A0A0C` / `BG #121215` / `SIDEBAR #1B1B20` / 卡片 / 强调色 `ACCENT #FA2D48` |
| 字体 | 英文 `Segoe UI Variable Display`（最接近 SF Pro），中文 `Microsoft YaHei UI` |
| `round_rect()` | Canvas 手绘圆角矩形（4 角弧 + 2 矩形） |
| `round_rect_shadow()` | 多层递减的深色矩形近似柔和投影 |
| `make_cover_image()` | 封面居中裁正方形 + 圆角遮罩 |
| `make_blur_background()` | 封面高斯模糊 + 纵向压暗，做氛围背景 |
| `dominant_color()` | 量化封面取主色 → 强调色（Apple Music 的"专辑色"） |
| `mix()` | 两个 #RRGGBB 线性插值（歌词渐隐用） |

### 2.2 `app.py` 界面层重写（业务逻辑未动）

**布局**（对照 Apple Music）：

```
┌──────────┬──────────────────────────────────────────────┐
│ 侧栏      │   ┌──────────┐   歌名（24pt bold）            │
│ 品牌      │   │ 340×340  │   歌手                        │
│ 操作按钮  │   │ 封面      │   歌手 · 时长 · PCM 44.1kHz     │
│ 倍速胶囊  │   └──────────┘                                │
│ 音调开关  │                        歌词（8 行，当前句高亮）  │
│ 播放列表  │                        当前句用封面主色加粗        │
│ 设备状态  │                                               │
├──────────┴──────────────────────────────────────────────┤
│ ⏮ ▶ ⏭    ───────●──────────  00:00      02:52   🔊 ──●──│
└──────────────────────────────────────────────────────────┘
```

**与旧版的关键差别**：

| 项 | 旧版 | 新版 |
|---|---|---|
| 侧栏 | 无，只有列表 | 毛玻璃深色侧栏：品牌 + 操作 + 播放列表 + 设备状态 |
| 封面 | 124px 小方块 | 340px 大图 + 圆角 + 投影 |
| 播放列表 | tk.Listbox（系统样式） | Canvas 自绘：圆角选中块、♪/♫ 标记、歌手副行、像素级截断 |
| 歌词 | 7 行，当前句黄色 | 8 行，当前句用**封面主色**高亮加粗，其余按距离渐隐 |
| 播放键 | tk.Label 文字 "▶" | Canvas 圆形按钮 + 三角/暂停图形，**颜色取自封面主色** |
| 前后曲 | "⏮"/"⏭" 字符 | Canvas 画双三角 + 竖条（`⏮` 在 Segoe UI Symbol 下会拆成两个分离三角） |
| 倍速 | tk.OptionMenu（系统箭头很突兀） | Canvas 胶囊 + 点击弹出自绘菜单 |
| 保持音调 | tk.Checkbutton（Windows 原生方框） | Canvas 胶囊开关（开=强调色） |
| 音量 | tk.Scale（无法设滑块色） | Canvas 细线 + 圆点，可点可拖 |
| 进度条 | 2px 矩形 | 4px 圆头轨道 + 白色圆点 |

### 2.3 踩过的坑

1. **`OptionMenu` 不支持 `arrowcolor`** → `TclError: unknown option "-arrowcolor"`
   （那是 ttk 的选项）→ 改成自绘胶囊 + `tk.Menu` 弹菜单。
2. **`Scale` 不支持 `slidercolor`** → 同上，ttk 专有 → 改 Canvas 自绘。
3. **`Canvas` 首次绘制时 `winfo_width()` 返回 0** → 画出来全是 0 尺寸的碎图形。
   这是本轮最难查的一个：控件树正常、坐标正常，但 `create_polygon` 的坐标全是 0。
   解法：所有自绘控件用**固定构造尺寸常量**（`SPEED_W/SPEED_H` 等），不依赖布局时机。
4. **`bar` 没设 `columnconfigure`** → 三列 bbox 全是 `(0,0,1180,72)`，
   子控件叠在同一列，右侧控件被挤出窗口（`cv_pitch` 在 x=1334 > 窗口宽 1180）。
   解法：`bar.columnconfigure(0/1/2, weight=...)` + 右侧区域改用 grid 而非 pack。
5. **底栏塞不下**：音量 + 倍速 + 音调开关同挤在底栏会溢出。
   解法：倍速和音调开关移到**侧栏**（Apple Music 的播放设置也在侧边），底栏只留进度 + 音量。
6. **`win32gui.PrintWindow` 不存在** → 在 `ctypes.windll.user32` 里。
7. **150% DPI 下截图坐标对不上**：tkinter 的逻辑坐标与 `ImageGrab` 的物理坐标差 1.5 倍。
   解法：用 `ctypes.windll.user32.PrintWindow(hwnd, hdc, 2)` 直接抓窗口内容，不做坐标换算。
8. **窗口销毁后 `_tick` 回调报 `invalid command name`** → 在 `_tick` 里捕获 `tk.TclError` 直接返回。

### 2.4 播放列表自动加载新格式

`_load_builtin_playlist()` 优先读 `Tools/mcu/manifest.json`（带曲名/歌手/歌词路径），
没有则退回旧的 `Tools/plNN.wav`。所以转换完 mp3 后**直接重启播放器就能看到 11 首**。

### 2.5 实测

- 自检 `py DesktopPlayer/app.py --selftest` **全部通过**（新增"板子格式转换"测试组）
- 真实播放《忘不掉的你》：状态 `playing`，33.0s / 172.2s，
  当前句「可笑的是我没法像你一样随意着」——**歌词时间轴正确跟随**
- 设备 COM6 在线，无旧推流进程占用

---

## 三、使用方法

```bat
:: 1) 批量转换 mp3（下载目录 -> Tools/mcu/）
py Tools\convert_mp3.py

:: 2) 启动桌面播放器（自动加载 Tools/mcu 的 11 首）
py DesktopPlayer\app.py
:: 或双击桌面上的「STM32 音乐播放器」快捷方式

:: 3) 推流给板子（用转换好的板子格式 WAV）
py Tools\host_cdc_sender.py --auto --wait -f Tools\mcu\pl06.wav --keys

:: 4) 自检
py DesktopPlayer\app.py --selftest
```

⚠️ **串口独占**：桌面播放器与 `host_cdc_sender.py` / `play.bat` 不能同时运行。
播放器状态栏会提示「串口被占用」，点侧栏「释放串口」一键踢掉旧进程。

---

## 四、文件清单

| 文件 | 状态 | 说明 |
|---|---|---|
| `DesktopPlayer/core_mcu.py` | 新增 | 板子格式转换核心 + 校验 |
| `DesktopPlayer/ui_theme.py` | 新增 | 苹果风视觉规范 + Canvas 绘制工具 |
| `DesktopPlayer/app.py` | 重写界面层 | 业务逻辑保留，界面换成 Apple Music 风格 |
| `Tools/convert_mp3.py` | 新增 | mp3 批量转换命令行 |
| `Tools/mcu/` | 新增产物 | 11 首 wav + 5 份 lrc + manifest.json |
| `docs/img/desktop_apple.png` | 新增 | 界面截图 |
| `docs/img/desktop_playing.png` | 新增 | 播放中截图（歌词高亮 + 封面主色播放键） |
