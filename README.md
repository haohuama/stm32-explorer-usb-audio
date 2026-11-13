# STM32F407 探索者 · USB 电脑音频播放器 + LCD 歌词

把电脑通过 USB 发来的 PCM 音频，经 STM32 的 I2S 送给 WM8978 解码，从喇叭播放；
同时在板载 4.3" 屏上显示**与歌声同步的滚动歌词**。

```
电脑 ──(USB CDC, PCM 16bit/44.1kHz/立体声)──> STM32F407 ──(I2S2)──> WM8978 ──> 喇叭
                                                    └──(FSMC 8080)──> 4.3" 800x480 LCD（歌词）
```

> 音频只走这一条数字链路；绿色端子仅输出模拟音频，CH340 只做下载/调试打印。
> 歌词时间轴用「真实 PCM 已播字节数」推算，不占用 CDC 带宽、不受墙上时钟影响。

## 硬件

| 项 | 说明 |
|---|---|
| 开发板 | 正点原子 探索者 STM32F407ZGT6（老版 V2.7，**不是 V3/ES8388**） |
| CODEC | **WM8978**（I2C：PB8=SCL / PB9=SDA，地址 0x34，只写） |
| I2S2 | PB12=WS / PB13=CK / PC3=SD / PC6=MCK（AF5），DMA1_Stream4 循环模式 |
| USB | USB_OTG_FS（PA11/PA12），全速 12Mbps，CDC 虚拟串口（VID 0x0483 / PID 0x5722） |
| LCD | FSMC 16 位 8080：CS=PG12 / RS=PF12 / WR=PD5 / RD=PD4 / BL=PB15，800×480 |
| TF 卡 | SDIO（PC8–PC12 + PD2，AF12），**P2.1 自检用轮询读，不启用 DMA/中断** |
| 跳线 | USB/CAN 跳线帽须置于 **USB 侧** |

## 特性

**音频链路**

- USB 设备描述符为标准 **CDC ACM**（`bDeviceClass=0x02`），Windows 即插即用，无需装驱动
- 设备端 **32KB 字节环形缓冲 + 8KB 双缓冲（2×4KB 半区）**，DMA 半传输/全传输中断里 refill
- 环形写入/溢出按 **4 字节立体声帧对齐**，避免字节错位噪声
- 欠载时"有多少填多少 + 补零"，避免整段静音跳变
- 上位机脚本：绝对时间匀速发送（消除 sleep 累积误差）、数字增益、写超时自愈重连

**LCD 歌词（本仓库新增）**

- 上电点亮 4.3" 屏，**全屏 32px 大字**（16×16 点阵按 2×2 像素块放大，不额外占 Flash）
- 8 行滚动、当前行黄色高亮 + 左侧指示条，**只在换行时重画**，不进任何中断、不抢音频总线
- 中文走内置 GBK 点阵（`cn_font.h`，由 PC 端脚本按"实际用到的字"生成，零外部字库依赖）
- **歌词与歌声同一基准**：时间 = 真实 PCM 已播字节数 ÷ 176400 B/s，静音不计时，卡顿自动停住
- **播放列表 4 首**，歌词数据在 `User/Hardware/LCD/lrc_data.h`（脚本生成）
- **曲目切换由上位机告知**：`ser.baudrate = 100000 + idx` → CDC `SET_LINE_CODING`，
  占 **0 字节音频带宽**，任意顺序 / 单曲循环 / 晚点开播都不会错位

**TF 卡离线播放（P2.0 / P2.1 已落地，暂未编入工程）**

- `Audio_Source` 统一切源接口契约（`src_start/stop/is_available`）+ 播放位置 API
- ChaN FatFs R0.14b + 自写 `diskio` 胶水层 + 轮询式 SDIO BSP + WAV 头解析
- 零风险自检：挂载 → 列目录 → 读 WAV 头 → 打印采样率/位深/声道，只走 CH340，不碰 I2S/USB
- 入口 `main.c` 的 `P2_SELFTEST_ENABLE` 开关（默认 0，打开即参与编译）

## 构建

- 工具链：Keil MDK（ARMCLANG V6.16），工程文件 `Projects/MDK-ARM/atk_f407.uvprojx`
- 依赖：STM32F4 HAL（`HAL_PCD` / `stm32f4xx_ll_usb` / `HAL_SD` / `ll_sdmmc` / `HAL_SRAM` / `ll_fsmc`）、
  ST USB Device Library（Core + CDC class）、ChaN FatFs R0.14b
- 步骤：Keil 打开工程 → **Clean → Rebuild** → ST-Link 烧录

> **关于 32KB 限制**：未授权的 Keil MDK-Lite 会把 image 卡在 32768 字节。
> 本工程当前 ROM ≈ 49.7KB，**需要 Keil MDK-Community（学生/非商业免费，无代码大小限制）**：
> `File → License Management → User-Based Activation → License Server: https://mdk-preview.keil.arm.com`。
> 相关踩坑与可逆裁剪开关见 `docs/`。

## 使用

1. 烧录固件
2. 用**能传数据**的 USB 线把电脑连到板载 **USB_SLAVE** 口（跳线置 USB 侧）
3. 设备管理器「端口」出现 **`USB 串行设备 (COMx)`**（首次可能需拔插一次）
4. 装依赖：`pip install pyserial`
5. 把 **44.1kHz / 16bit / 立体声** WAV 放进 `Tools/`（MP3 需先转 WAV，可用 `Tools/loud_master.py`）
6. 播放（脚本按 VID/PID 自动找口，掉线/复位自动重连续播）：
   ```
   py Tools/host_cdc_sender.py --auto --wait -f Tools/pl01.wav --gain 0.65
   ```
   - `--gain N`：发送前数字增益（`1.0` = 不处理；源已满量程时别超 1.0，会削波）
   - `--rate R`：发送速率倍数（偶发断音调大、偶发爆音调小）
   - `-f a.wav b.wav`：按顺序循环播放列表；`plNN.wav` 的尾部数字决定设备播第几首的歌词

> 只有一根 USB 线时：插 USB_SLAVE 即可（CH340 调试口可留空，不影响放音）。

## 换歌词 / 换歌（不用改 C 代码）

```bat
py Tools/lrc_playlist.py "歌1.lrc" "歌2.lrc" "歌3.lrc" "歌4.lrc"   :: 生成 lrc_data.h
py Tools/gen_cn_font.py                                          :: 只渲染用到的汉字
py Tools/check_lrc.py                                            :: 用与 C 相同规则模拟解析，须 0 空行
py Tools/check_font.py                                           :: 须"缺字:无"
py Tools/build_check.py --microlib                               :: 编译+链接+报体积
```

然后把同名 MP3 转成 `plNN.wav`（序号与 lrc 顺序一致），重新 Rebuild 烧录即可。
详见 `docs/LCD歌词界面_模块1集成说明.md` 的 §10 / §13 / §14。

## 目录结构

```
User/               应用层
  main.c            启动流程（I2S → WM8978 → 流播放 → USB CDC → LCD）
  Hardware/AUDIO/   i2s_audio.c/.h：环形缓冲 + DMA 双缓冲 + 播放位置 API
  Hardware/WM8978/  CODEC 驱动（I2C 软件模拟）
  Hardware/LCD/     lcd.c/h(正点原子 HAL 版) + lcd_ui.c(歌词界面) + cn_font.h/lrc_data.h(生成)
  Hardware/SDIO/    轮询式 SD 卡 BSP（P2.1）
  APP/              audio_source(切源契约) / wav_probe(WAV 头解析) / p2_selftest(TF 卡自检)
Middlewares/USB/    ST USB 设备库(Core+CDC) + USB_APP 适配层
Middlewares/FATFS/  ChaN FatFs R0.14b + 自写 diskio
Drivers/            STM32F4 HAL + CMSIS
Projects/MDK-ARM/   Keil 工程
Tools/              上位机与生成脚本
  host_cdc_sender.py  匀速发 PCM（增益/限幅/自动找口/断线重连/选曲）
  lrc_playlist.py     多个 .lrc → lrc_data.h
  gen_cn_font.py      渲染精简 GBK 点阵 → cn_font.h
  check_lrc.py        模拟 C 解析器校验歌词
  check_font.py       校验歌词用字是否都在字库里
  build_check.py      按 uvprojx 清单全量编译 + 链接 + 报体积
  gen_test_wav.py     生成测试音；loud_master.py 转 WAV + 响度处理
  _onetime/           历史一次性补丁脚本（保留作过程记录）
docs/               开发过程与技术文档（硬件核对、I2S/WM8978、CDC、LCD 歌词、TF 卡自检等）
REPRODUCE.md        陌生人复现指南
NOTICE.md           第三方组件许可证
```

## 许可证与第三方

本项目包含 STM32 HAL / CMSIS、ST USB Device Library、ChaN FatFs、WM8978 驱动、
正点原子 LCD 驱动等第三方组件，详见 [NOTICE.md](NOTICE.md)。
原始第三方手册、字库文件与版权音乐**不包含**在本仓库内。

---

## 配套开发技能

本项目的板级踩坑经验已整理成可复用技能包（独立私有仓库）：
**`stm32f407-explorer-audio`** —— 板级事实表、Keil 循环包含/缺源文件/32KB 授权、
CDC 枚举与描述符修复、流式音频缓冲设计、LCD 中文歌词流水线。
