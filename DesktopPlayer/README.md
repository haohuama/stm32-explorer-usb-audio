# STM32 音乐播放器 · 桌面控制台

电脑端软件：导入音乐/歌词 → 电脑把 PCM 经 USB 实时送给板子 → 喇叭出声，
同时桌面显示歌名、封面、滚动歌词。板子小屏也会同步（歌名/歌手/歌词/封面）。

界面参考 macOS「音乐」App（Apple Music）：深色侧栏、大封面、歌词居中渐隐、
底部细线播放控件，播放键颜色取自**封面主色**。

## 启动

**桌面上已经有快捷方式：`STM32 音乐播放器`** —— 直接双击即可（用 `pythonw.exe` 启动，没有黑色控制台窗口，蓝色音符图标）。

也可以：

```bat
py DesktopPlayer\app.py
:: 或双击 DesktopPlayer\启动播放器.bat（带控制台，排错时用）
```

打开后会自动载入 `Tools/mcu/` 里现成的 **11 首**（批量转换好的板子格式 WAV + 配套歌词），
默认停在《忘不掉的你》，**双击列表里任意一首开始播放**。

> ⚠️ 串口是独占的：桌面软件、`host_cdc_sender.py`、`play.bat` 三者**不能同时运行**。
> 如果状态栏提示"串口被占用"（`PermissionError(13, 拒绝访问)`），点侧栏的 **释放串口**
> 按钮：软件会找出残留的 `host_cdc_sender.py` 进程、结束它并自动重连（1~2 秒），
> 不用重启播放器。设备标签会变红显示"串口被占用"。
> 常见残留：`host_cdc_sender.py --auto --wait -f Tools/plNN.wav --keys` 这个常驻推流窗口。

依赖：Python 3（带 tkinter）+ `pyserial` + `Pillow` + `pywin32`(仅生成快捷方式用) + `ffmpeg`。
ffmpeg 会自动在这些位置找：环境变量 `FFMPEG`、`C:\Program Files\File Converter\ffmpeg.exe`、
`C:\ffmpeg\bin\ffmpeg.exe`、PATH。

## mp3 怎么变成板子能吃的格式

板子端 I2S 时钟固定，永远按 **176400 B/s** 消费 PCM，也就是 **44.1kHz / 16bit / 立体声**。
mp3 是压缩格式，MCU 上没有解码器，**直接推 mp3 只会是噪音**。

所以用批量转换工具：

```bat
:: 扫描下载目录，转换所有 mp3 -> Tools\mcu\plNN.wav（+ 配对歌词 + manifest.json）
py Tools\convert_mp3.py

:: 只看会做什么
py Tools\convert_mp3.py --dry-run
```

转换做三件事：重采样到 44.1k、混成立体声、加 **-1 dBFS 峰值限制器**
（mp3 源常已削顶，限制器能避免推流后爆音）。转换完重启播放器就能在列表里看到。

底层逻辑在 `DesktopPlayer/core_mcu.py`，也可以直接在代码里调用：

```python
from core_mcu import to_mcu_wav, verify_mcu_wav
to_mcu_wav(ffmpeg, "a.mp3", "out.wav")     # 返回 (路径, 时长ms)
print(verify_mcu_wav("out.wav"))           # 校验格式
```

## 怎么用

1. 板子 USB 线插 **USB_SLAVE** 口（不是 CH340 那个 USB_232）
2. 点侧栏 **导入音乐**（mp3 / wav / flac / m4a / ogg 都行，会自动转码）
3. 双击列表里的歌开始播放；侧栏底部 `设备 COMx` 变粉红表示已连上板子
4. **绑定歌词**：给选中的歌指定 `.lrc`；如果 `.lrc` 与音频同名同目录，会自动绑定
5. **选择封面**：同名图片也会自动绑定
6. 侧栏 **倍速** 0.5x~2.0x（点胶囊弹菜单），**保持音调** 开关打开就是不变调（atempo），
   关闭是变调（asetrate）
7. 底部：⏮ ▶/⏭、音量 0~100（点/拖细线）、状态提示
8. 快捷键：`空格` 播放/暂停，`←` 上一首，`→` 下一首

## 几个关键设计（踩过的坑）

| 现象 | 原因 | 这里怎么处理 |
|---|---|---|
| 改发送速率做倍速 → 音乐断续/咔哒 | 板子 I2S 时钟固定，永远 176400 B/s 消费；发慢了每次 DMA 补静音，发快了环形溢出丢样本 | 倍速在 ffmpeg 里做，**出口仍是 44.1k**，发送速率恒定 |
| Windows 上偶发爆音 | `time.sleep` 默认 15.6ms 粒度，把 23ms 的节拍打成 31ms | `timeBeginPeriod(1)` + 绝对时刻调度 + 2.5ms 自旋收尾 |
| 暂停怎么做 | 板子不存音频，声音全靠电脑送 | 暂停 = 停止发送；环形排空后自动静音 |
| 板子小屏歌词 | 设备按「收到多少字节」计时 | 非 1.0 倍速时，下发的 LRC 时间戳会先除以倍速（`scale_lrc`） |
| 播着播着 COM 口消失 | 已知固件侧隐患 | 写失败自动重连，并从当前位置续播 |

## 文件

```
DesktopPlayer/
  app.py               界面（Tkinter）+ 预置播放列表 + --selftest
  core_track.py        ffmpeg 解码/变速、LRC 解析与时间缩放
  core_device.py       板子 USB CDC 通道（选曲 / 控制帧 / PCM）
  core_player.py       播放引擎（后台线程、节拍、重连）
  make_icon.py         生成 app.ico
  make_shortcut.py     在桌面创建/重建快捷方式
  verify_shortcut.py   模拟双击，验证 GUI 能起来并截图
  app.ico              快捷方式图标
  assets/default_cover.jpg
  启动播放器.bat       带控制台的启动方式（排错用）
```

快捷方式丢了就跑一次：`py DesktopPlayer\make_shortcut.py`（幂等，覆盖同名不会堆积）。

## 自检

```bat
py DesktopPlayer\app.py --selftest
```

会检查：ffmpeg、LRC 解析/缩放、三种转码出口是否都是 44.1k/立体声/16bit、
控制帧格式（假串口，不动真设备）、设备是否在线。
