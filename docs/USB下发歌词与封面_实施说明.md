# USB 下发歌词 / 封面（不重烧固件就能换）

> 没有 TF 卡的情况下，让「改歌词 / 换封面」只改电脑端文件。
> 思路：**音频本来就要电脑经 USB CDC 送 PCM，歌词和封面跟着同一条线下来**。

## 1. 时序（关键：不与 PCM 抢通道）

```
电脑                                      设备
ser.baudrate = 200000      ──────────►  CDC_SET_LINE_CODING → 进控制模式
发帧 SONG / LRC×N / LRC_END / COVER_ROW×240
ser.baudrate = 115200      ──────────►  退出控制模式
发 PCM（原来的路，一行没改）──────────►  环形 → I2S → WM8978
```

播放期间设备**不解析任何帧**，所以这条通道对现有音频链路零影响。
选曲仍用 `100000+idx` 的老通道，互不冲突（`200000` 落在选曲区间之外）。

## 2. 帧格式

```
'A' 'T' 'K' | type | len_lo len_hi | payload[len]      （小端）
```

| type | 名称 | payload |
|---|---|---|
| 0x01 | SONG | `idx, tlen, title[GBK], alen, artist[GBK]` |
| 0x02 | LRC | 歌词文本块（GBK，≤480 字节，可多帧累加） |
| 0x03 | LRC_END | 空 → 解析并生效 |
| 0x04 | COVER_ROW | `row_lo, row_hi, 240×RGB565(小端)` = 482 字节 |

封面**逐行下发、逐行画**：240×240 RGB565 = 115KB，RAM 装不下，
所以设备收到一行就写一行到 GRAM（`lcd_set_cursor` + `LCD->LCD_RAM`）。

## 3. 固件实现

| 文件 | 作用 |
|---|---|
| `User/APP/cdc_ctrl.c/.h` | 组帧（USB 中断）+ 执行（主循环） |
| `Middlewares/USB/USB_APP/usbd_cdc_if.c` | `CDC_Control_FS` 里按波特率切控制模式；`CDC_Receive_FS` 分流到 `cdc_ctrl_feed()`；导出 `CDC_CTRL_Rearm()` |
| `User/Hardware/LCD/lcd_ui.c` | 新增 `lcd_ui_set_meta()`（歌名/歌手覆盖）、`lcd_ui_set_volume()`、`lcd_ui_set_duration()` |

**流控**：一帧收齐而主循环还没取走时，**不再 arm OUT 端点** → 主机的 `write` 阻塞，
天然不丢帧；主循环一次最多消化 8 帧，不会卡住界面。

**中断里只做 memcpy**，画屏/解析歌词全在主循环（遵守「UI 不进中断」）。

## 4. 上位机用法

```bat
:: 只换歌词+封面（连 WAV 一起发也行）
py Tools\host_cdc_sender.py --auto --wait -f Tools\pl05.wav ^
   --lrc "C:\Users\mhh20\Downloads\Scared 2 Be Lonely - Lil Tjay.lrc" ^
   --cover "C:\...\8e63184e7a80a6758dfdcd933ca03465.jpg" ^
   --title "Scared 2 Be Lonely" --artist "Lil Tjay"
```

- `.lrc` 的编码随你（UTF-8/GBK 都行，脚本会转成 GBK 下发）
- 图片任意尺寸（居中裁方 → 缩到 240×240）；需要 `Pillow`
- `--meta-for N` 指定这些内容属于第几首（0 基）；默认=第一个 WAV 的序号
- 打包顺序：先切控制模式 → SONG → LRC → COVER → 切回 115200 → 才开始发 PCM

## 5. 已验证 / 未验证

- ✅ Keil 全量 Rebuild：**0 Error 0 Warning**，Flash 508940B(497KB) / RAM 68352B
- ✅ 帧格式离线自测：COVER_ROW 帧 488 字节，头 `41 54 4b 04 e2 01`（type=4, len=482）
- ❌ **没有上板实测**：控制模式切换、封面行显示速度、LRC 替换是否即时生效，
  都需要烧录后看真机（串口可观察到换歌打印）。
