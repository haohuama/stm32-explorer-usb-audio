# 上位机工具

`scripts/` 下的脚本都是可直接复用的，路径假设工程根目录下运行（`python Tools/xxx.py`）。

## host_cdc_sender.py —— 电脑经 USB CDC 匀速发 WAV

把 44.1kHz / 16bit / 立体声 WAV 实时发给虚拟串口（设备端的 CDC 音频口）。

```
python host_cdc_sender.py -p COMx -f song.wav [--rate 1.0] [--gain 1.0]
python host_cdc_sender.py --auto --wait -f pl01.wav pl02.wav
```
- `-p` 目标串口；**推荐 `--auto`**：按 VID/PID（如 0x0483/0x5722）自动找口，COM 号变了也不怕，
  且能排除 DFU 的 `PID_DF11`
- `--wait` 端口没出现时持续等待；播放中掉线/按 RESET 会**自动重连并从当前曲目续播**
- `-f` 一个或多个 WAV（必须 44.1k/16bit/立体声）；多个 = 按顺序循环
- `--rate` 发送速率倍数（默认 1.0；断音调大、爆音调小）
- `--gain` 发送前数字增益（`1.0` = 不处理；满量程源再放大只会有削波失真，想要更响应改固件模拟音量）
- `--no-loop` 只播一遍

**关键实现点（都是踩过的坑）**
- **绝对时间调度**（`time.monotonic()` 算下一批时刻），不用 `sleep(时长)` —— Windows 下 sleep 会过冲且误差逐批累积，导致缓冲被慢慢抽干 → 周期性断音
- `write_timeout=None`（阻塞写）—— 默认超时会把一次 USB 瞬时卡顿当致命错误直接退出
- **就绪探针**：打开串口后先写 4 字节静音并 flush，写不通说明是 Windows 残留的"幽灵 COM 口"（设备已重枚举但节点还在），关掉重等，避免误报"开始发送"
- **选曲通知**：每首歌开始前 `ser.baudrate = 100000 + idx`（触发 `CDC_SET_LINE_CODING`，0 字节音频开销）+ DTR/RTS 兼容位
- 启动时打印源峰值；`gain*peak > 32767` 才提示削波（注意 `peak=32768` 只是 `-32768` 的绝对值，等于 1.0 倍不算削波）

## lrc_playlist.py —— 多个 .lrc → `lrc_data.h`

```
python lrc_playlist.py "a.lrc" "b.lrc" "c.lrc" "d.lrc"
```
- 同时支持标准 `[mm:ss.xx]` 与网易云那种 `{"t":..,"c":[{"tx":..}]}` 混排行
- 自动剔除**带冒号的制作人员行**（`作词: xxx` / `吉他: xxx` / `OP: xxx`）和 `VERSE1/CHORUS` 段落标记
  —— 不该上屏，而且白吃字库空间
- 生成 `s_titleN` / `s_lrcN`（中文一律 `\xNN` GBK 转义，避免源文件编码歧义），
  并同步 `gen_cn_font.py` 的用字表
- 首数上限 `MAX_SONGS` 必须与固件的 `SONG_COUNT` 一致

## gen_cn_font.py —— 渲染精简 GBK 点阵 → `cn_font.h`

只渲染"屏上真正会出现"的汉字，每字 32 字节（16×16）。100 字≈3.2KB，500 字≈16KB。
依赖 `Pillow` + 系统字体（如 `C:/Windows/Fonts/simsun.ttc`）。

## check_lrc.py —— 用与 C 相同规则校验歌词

把固件里的 `parse_lrc()` 规则用 Python 复刻一遍，直接对 `lrc_data.h` 里的转义数组做解析，
输出每首的行数与"空正文"数量。**编译前就能发现"烧完才发现屏上空白"**。

## check_font.py —— 校验缺字

把 `lrc_data.h` 里所有 GBK 字节解出来，与 `cn_font.h` 的码表比对，
输出"需要 N 个字，缺字: xxx"。缺一个字 = 屏上一个空白洞。

## build_check.py —— 全量编译 + 链接 + 报体积（不依赖 Keil 界面）

```
python build_check.py            # 已授权 MDK：只报体积
python build_check.py --microlib  # 与工程 <useUlib>1 一致
python build_check.py --lite      # 按未授权 32768 上限判定 PASS/OVER
```
按 uvprojx 的 `<FilePath>` 清单取源文件、用工程同一份 `.sct`、`armclang -Oz`、
`armasm` 汇编 startup、`armlink --scatter` 真实链接，从 "Total ROM Size" 取数。
**校准：同代码脚本 37880 vs Keil 38072（+0.5%），脚本值 +200 ≈ Keil 值。**

## gen_test_wav.py —— 生成测试音

44.1k/16bit/立体声的"小星星第一句"，用于第一次验证链路是否出声。
```
python gen_test_wav.py [输出文件名，默认 music.wav]
```

## loud_master.py —— 音频转 WAV + 响度处理

把任意音频（mp3/wav）转成 44.1k/16bit/立体声 WAV；可选 loudnorm 响度标准化。
```
python loud_master.py 输入.mp3 输出.wav [-8]   # 最后一个是目标 LUFS
```
> 实测教训：源已 0dBFS 满量程时，"数字放大 N 倍"必然削波，不存在"更响且干净"。
> 想要更大声应该提**固件里 WM8978 的模拟音量**（`WM8978_SPKvol_Set(0x30~0x3F)`），
> 而不是在 PC 端乘增益。不同 ffmpeg 构建里 loudnorm/alimiter 行为差异也很大。

## 依赖

- `pip install pyserial`（发串口）
- `pip install Pillow`（生成点阵）
- 转码/响度处理需要 ffmpeg；没装可用 `pip install imageio-ffmpeg` 自带的静态 ffmpeg

## 常见音频格式转换（命令行 ffmpeg）

```
ffmpeg -y -i in.mp3 -ac 2 -ar 44100 -c:a pcm_s16le out.wav
```

> Windows 下若 ffmpeg 路径含反斜杠，在 Git Bash 里要先转成 `/c/...` 形式再执行。
> 文件名含中文/特殊符号时，先 `cp` 成 ASCII 临时名再转，避免编码问题。
## 生成类工具（歌词 / 字库 / 封面 / 预览）

| 脚本 | 作用 | 关键点 |
|---|---|---|
| `lrc_playlist.py` | 多个 `.lrc` → `lrc_data.h` | 同时间戳两行**自动配对**成 `原文\x01译文`（英文歌+中文翻译）；`[ti:]/[ar:]` 优先于文件名；`s_durN` 由 `Tools/plNN.wav` 字节数算；GBK 字节安全截断 |
| `gen_cn_font.py` | 只渲染用到的汉字 → `cn_font.h` | 16×16 行优先点阵；`DEMO_LYRICS` 由 lrc_playlist 自动同步 |
| `gen_cover.py` | jpg → `cover_img.h` | 240×240 封面 + 400×120 模糊底（压暗 + 向右渐隐）；带 ±2LSB 抖动防色带 |
| `preview_ui.py` | 版式预览 PNG | 读固件真实点阵/像素，复刻 `lcd_ui.c` 的版式常量；烧前先看这张图 |
| `lrc_extract.py` | `lrc_data.h` → `.lrc` 源文件 | 歌词源文件丢了也能救回来 |
| `check_lrc.py` / `check_font.py` | 解析校验 / 缺字校验 | 必须「0 空正文」「缺字:无」 |
| `build_check.py` | 按 uvprojx 清单自建编译 | 只做体积预检；权威数据以 UV4 命令行日志为准 |
| `keil_rebuild.bat` | 一键全量 Rebuild | `UV4 -r -j0 -o`，日志 `Output/rebuild_all.txt`，退出码可信 |
