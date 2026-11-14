---
name: stm32f407-explorer-audio
description: 正点原子「探索者 STM32F407（老版 V2.7）」开发板的通用工程经验：Keil+HAL 工程搭建踩坑（循环包含/缺源文件/32KB 授权）、STM32 USB CDC 虚拟串口集成与 Windows 枚举修复、WM8978 + I2S2 音频输出、电脑经 USB 流式播放到喇叭（环形缓冲/双缓冲/DMA）、4.3" FSMC 屏播放器界面（封面/歌曲信息 + 中英文双语滚动歌词 + 精简 GBK 点阵 + 与歌声同步 + 上位机选曲）、SDIO+FatFs 读 TF 卡 WAV。当在此板（或相近 F407 + WM8978 板）上做音频/USB/LCD/Keil 工程时参考。
agent_created: true
---

# STM32F407 探索者 · 音频 / USB CDC / LCD 歌词 开发经验

一套从实战中沉淀的可复用经验，针对 **正点原子 探索者 STM32F407ZGT6（老版 V2.7）** + **WM8978** + **Keil MDK(ARMCLANG)**。

典型场景：电脑经 USB 把 PCM 音频流式发到 MCU → I2S → WM8978 → 喇叭，
同时板上 4.3" 屏滚动显示与歌声同步的歌词；以及后续从 TF 卡离线播放。

> 详细内容见 `references/`，可直接复用的脚本见 `scripts/`。

## 何时用这个 skill

- 在这块探索者 F407 上从零建 Keil+HAL 工程、接 USB CDC、驱动 WM8978、放音频。
- 遇到 `undefined symbol HAL_PCD_* / USB_* / FSMC_* / SDMMC_*`、`conflicting types`、
  `unknown type uint8_t`、`L6050U/L6047U 超过 32768`、Windows 设备管理器 Code 10/28 等典型坑。
- 想在 LCD 上显示中文（没有外部字库文件）、做歌词滚动、让歌词跟歌声对齐、多曲目切换。
- 想从 TF 卡读 WAV 而不破坏已跑通的 USB 播放路径。

## 板子关键事实（老版 V2.7，不是 V3/ES8388）

| 项 | 值 |
|---|---|
| MCU | STM32F407ZGT6（LQFP144），HSE 8MHz → PLL 168MHz，1MB Flash / 128KB RAM |
| CODEC | **WM8978**（I2C 地址 0x34，只写；写帧 `(reg<<1)|(val>>8)` + `val&0xFF`） |
| I2C（CODEC） | **PB8=SCL / PB9=SDA**（软件 I2C 即可） |
| I2S2 | **PB12=WS / PB13=CK / PC3=SD / PC6=MCK**（全 AF5），DMA1_Stream4/Ch0，CIRCULAR |
| USB | **USB_OTG_FS**（PA11=DM / PA12=DP，AF10），全速 12Mbps，VID 0x0483 / PID 0x5722 |
| LCD | FSMC 16 位 8080：**CS=PG12 / RS=PF12 / WR=PD5 / RD=PD4 / BL=PB15**，4.3" 800×480 |
| TF 卡 | SDIO：**PC8–PC12 + PD2**（AF12） |
| 调试串口 | CH340 → USART1（PA9/PA10），115200 |
| 硬件跳线 | **USB/CAN 跳线帽必须置 USB 侧**；音频数据从板载 **USB_SLAVE** 口进（不是 USB_232/CH340，也不是 USB-HOST 的 A 口） |
| 时钟 | PLLI2SN=271 / PLLI2SR=2 → MCLK 11.2917MHz（44.1k 误差 +0.019%） |

## 五大任务速查

| 要做的事 | 看这里 |
|---|---|
| Keil 编译/链接报错、超 32KB、想不开 IDE 验证体积 | `references/keil_build_pitfalls.md` |
| USB CDC 不枚举 / Code 10·28 / 断断续续·刺耳 | `references/usb_cdc_audio.md` |
| LCD 点亮 + 中文歌词 + 同步 + 选曲 + **上半屏封面/双语歌词版式** | `references/lcd_lyrics.md` |
| TF 卡读 WAV（不破坏 USB 路径） | `references/sdio_fatfs.md` |
| 上位机脚本、歌词/字库/封面生成与预览 | `references/tools.md` |

## 最高频的 10 个坑（一句话版）

1. `usbd_conf.h` **禁止** `#include "usbd_core.h"`（循环包含 → 全工程 unknown type）；应由 `usbd_conf.c` include 它。
2. 工程要**显式加入** `hal_pcd.c` + `hal_pcd_ex.c` + `ll_usb.c`（USB）、`hal_sram.c` + `ll_fsmc.c`（FSMC 屏）、
   `hal_sd.c` + `ll_sdmmc.c`（TF 卡）—— **`hal_conf.h` 开了宏 ≠ 源文件在工程里**，缺了只在链接期报 `L6218E`。
3. CDC 设备描述符 `bDeviceClass` 必须是 **`0x02`**，否则 Windows 拆成复合设备 → Code 10/28（装驱动没用）。
4. `USBD_malloc/USBD_free` 要定义成 `malloc/free` 宏，且 startup 的 **`Heap_Size` 不能为 0**。
5. 流式缓冲 DMA 的 `Size` 单位是**半字数（16bit 样本）**，缓冲要按 `uint16_t[]` 声明、
   大小 = 2×半区样本数，否则越界读相邻内存 → 刺耳噪声。
6. `L6050U/L6047U 32768` 是**未授权 Keil MDK-Lite 的限制**，激活免费的 MDK-Community 即可解除（F407 有 1MB）。
7. 歌词时间轴**必须**用"真实 PCM 已播字节数 / 176400"，不能用 `HAL_GetTick()`，
   也不能用"开机以来的 DMA 消费量"（空闲播静音也计消费）。
8. LCD 驱动里的 `printf("LCD ID")` 必须删（无 stdio 重定向 → 半主机 HardFault）。
9. 汉字点阵是**行优先**、`asc2_1608` 是**逐列式**，两套绘制函数不能混（抄错就是一屏乱码）。
10. 体积/构建的权威数据来自 `UV4.exe -r proj.uvprojx -j0 -o log`，不是自制脚本
    （同一份代码脚本报 274476，Keil 报 274936）。

## 目录

```
references/
  board_hardware.md      板级引脚/时钟/CODEC 事实
  keil_build_pitfalls.md 编译/链接坑、缺源文件、32KB 限制与可逆裁剪、体积测量校准
  usb_cdc_audio.md       USB CDC 集成（含 Windows 枚举修复）+ 流式音频播放架构
  lcd_lyrics.md          FSMC 屏移植、精简 GBK 点阵、32px 放大、歌词同步、选曲协议
  sdio_fatfs.md          SDIO 轮询读 + ChaN FatFs + WAV 校验 + 数据源契约
  tools.md               上位机与生成脚本说明
scripts/
  host_cdc_sender.py     电脑经 CDC 匀速发 WAV（增益/限幅/自动找口/断线重连/选曲）
  lrc_playlist.py        多个 .lrc → lrc_data.h（自动剔制作人员行）
  gen_cn_font.py         只渲染用到的汉字 → cn_font.h
  check_lrc.py           用与 C 相同规则模拟解析歌词
  check_font.py          校验歌词用字是否都在字库里
  build_check.py         按 uvprojx 清单全量编译+链接+报体积
  gen_test_wav.py        生成 44.1k 测试音
  loud_master.py         音频转 WAV + 响度处理
```
