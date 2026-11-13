# HAL 库版 实验52 / 实验43 · 编译烧录调试与兼容清单

> 依据（**只读解析，未修改、未复制、未编译、未烧录、未上传**）：
> `D:\4，程序源码\4，程序源码\2，标准例程-HAL库版本\实验52 USB声卡(Slave)实验`
> `D:\4，程序源码\4，程序源码\2，标准例程-HAL库版本\实验43 音乐播放器实验`
> 时间：2026-11-12 15:30　状态：**已停止联网；代码适配仍暂停**

---

## 0. 结论先行

换成 HAL 版后，**工具链对齐了，但 CODEC 仍然是 ES8388**。

| 核对项 | 结果 |
|---|---|
| 是否真 HAL 工程 | ✅ `Define = USE_HAL_DRIVER,STM32F407xx,USE_USB_FS`；全套 `stm32f4xx_hal_*.c`；`HAL_Init()`；`HSE_VALUE 8000000U`；HAL 版 GPIO / PCD / I2S API |
| 主控 | ✅ `STM32F407ZGTx` |
| USB 声卡 | ✅ Target `USBD_AUDIO`，UAC 1.0 / USB FS，ISOC OUT EP `0x01`，VID `0x0483` / PID `0x5730` |
| CODEC | ❌ **ES8388**（`ES8388_ADDR 0x10`），仍不是 WM8978 |
| CubeMX | ❌ **没有 `.ioc`**，`User\main.c` 中 `USER CODE` 出现 **0 次** → 手写 HAL 工程，不是 CubeMX 生成 |
| 采样率 | ❌ `USBD_AUDIO_FREQ 48000`，项目主线要 44.1 kHz CDC |
| 较寄存器版的进步 | BSP 全用 HAL 常量/API、`HSE_VALUE` 明确 8 MHz（寄存器版 CMSIS 模板默认是 25 MHz，容易踩坑）、USB 用标准 `HAL_PCD_MspInit` + `GPIO_AF10_OTG_FS` |

证据：`实验52\readme.txt` 硬件资源第 8 条「ES8388音频CODEC芯片」；`实验43\readme.txt`「学习ES8388和STM32 IIS」；`.uvprojx` 源文件含 `es8388.c`、**无 `wm8978.c`**；`main.c:61` `es8388_init()`；源码版权 `2020-2032`、`@date 2022-01-20`（V3 时代）。

> 所以「换成 HAL 版」解决的是**工具链**，没有解决**硬件 CODEC**。这份工程仍只能当 USB Audio 流控 / HAL 驱动写法 / 枚举调试的参考，不能直接作为 V2.7 主线固件。
> 按提示词「本项目按 WM8978 设计，ES8388 需另开分支」「禁止套用 V3 ES8388 驱动」，在你给出丝印照片 + `ADAPT_OK` 前不动任何工程文件。

---

## 1. 实测配置清单（从源码读出）

| 项 | 值 | 出处 |
|---|---|---|
| 工程 | `Projects\MDK-ARM\atk_f407.uvprojx`，Target `USBD_AUDIO`，TargetName `MUSIC`（实验43） | `.uvprojx` |
| 编译宏 | `USE_HAL_DRIVER,STM32F407xx,USE_USB_FS` | `.uvprojx` |
| 编译器 | `<uAC6>0</uAC6>` → **ARM Compiler 5 (armcc)** | `.uvprojx` |
| 时钟 | `HAL_Init(); sys_stm32_clock_init(336,8,2,7)` → 168 MHz，`pllq=7` ⇒ USB 48 MHz；`HSE_VALUE 8000000U` | `main.c:48-49`、`User\stm32f4xx_hal_conf.h:84` |
| 调试串口 | `usart_init(115200)` → USART1；readme 要求 **P10 跳线** PA9/PA10 ↔ RXD/TXD | `main.c:51` |
| USB 引脚 | `GPIOA PIN11|PIN12`，`GPIO_MODE_AF_PP`、`GPIO_NOPULL`、`GPIO_SPEED_FREQ_VERY_HIGH`、`GPIO_AF10_OTG_FS`；`__HAL_RCC_USB_OTG_FS_CLK_ENABLE()`；`OTG_FS_IRQn` 抢占 0 / 子 3 | `usbd_conf.c:47-64` `HAL_PCD_MspInit` |
| 描述符 | VID `0x0483` / PID `0x5730` | `usbd_desc.c:26-27` |
| 采样率 / 缓冲 | `USBD_AUDIO_FREQ 48000`（注释「ST USB库目前只支持这一个采样率」）；`AUDIO_OUT_PACKET=192`；`AUDIO_OUT_PACKET_NUM=80` ⇒ 15 360 B；`wr_ptr/rd_ptr` + ±4 B 速率补偿 | `usbd_conf.h:43`、`usbd_audio.h:46,106-113` |
| 默认音量 | `AUDIO_DEFAULT_VOLUME 70`；初始化 `hpvol 25 / spkvol 30`；按键 `g_volume*0.3` | `usbd_audio.h:107`、`main.c:64-65,104-105` |
| I2S | `i2s_init(I2S_STANDARD_PHILIPS, I2S_MODE_MASTER_TX, I2S_CPOL_LOW, I2S_DATAFORMAT_16B_EXTENDED)`；`i2s_samplerate_set(AudioFreq)` 用 PLLI2S 查表 | `stm32f407_audio.c:57-59` |
| I2S 引脚 | PB12=LRCK、PB13=SCLK、PC2=SDOUT(`GPIO_AF6_I2S2ext`)、PC3=SDIN、PC6=MCLK，`GPIO_AF5_SPI2`，`SPI2`，`DMA1_Stream4` | `Drivers\BSP\I2S\i2s.h:31-61` |
| CODEC 控制 | 软件 IIC：PB8=SCL / PB9=SDA，用 `HAL_GPIO_WritePin` / `HAL_GPIO_ReadPin`；`ES8388_ADDR 0x10` | `myiic.h:34-55`、`es8388.h:30` |
| USB 适配链 | `USBD_AUDIO_fops` → `Audio_Init` → `BSP_AUDIO_OUT_Init` → `es8388_i2s_cfg` + `i2s_init` + DMA | `usbd_audio_if.c`、`stm32f407_audio.c` |
| 已编译产物 | `Output\atk_f407.hex`：实验52 **153 972 B**，实验43 **216 743 B** | 目录实测 |
| Flash 算法 | `STM32F4xx_1024.FLM`，`CreateHexFile=1`，输出 `..\..\Output\` | `.uvprojx` |

**实验43 作为音频驱动参考可提取**：`Drivers\BSP\I2S\i2s.c/h`（HAL 版 I2S 初始化、PLLI2S 采样率查表、DMA 双缓冲回调）、`Drivers\BSP\IIC\myiic.c/h`（软件 IIC 的 HAL 写法）、`Middlewares\AUDIOCODEC\wav\wavplay.c/h`（WAV 解析、16/24 bit 低字节在前）。
**不可直接取**：`es8388.c/h`（CODEC 不同）、SDIO / FATFS / NORFLASH / 字库 / USMART（白名单外，且实验43 必须插 SD 卡并在根目录建 `MUSIC` 文件夹才能播放）。
⚠️ 实验43 **同样没有 WM8978 驱动**，所以它不能解决 CODEC 不匹配，只能提供 I2S/DMA/WAV 的 HAL 写法。

---

## 2. 编译 / 烧录 / 电脑识别调试步骤（人工执行）

### 2.1 编译（Keil uVision5）

1. 打开 `实验52 USB声卡(Slave)实验\Projects\MDK-ARM\atk_f407.uvprojx`。
2. 装 `Keil.STM32F4xx_DFP`（本机 `E:\Keil.STM32F4xx_DFP.3.1.1` 有痕迹）；确认 Device = `STM32F407ZGTx`。
3. ⚠️ **编译器兼容性**：工程 `<uAC6>0</uAC6>` 表示用 **AC5 (armcc)**。MDK 5.37 以后默认不带 AC5，若报 `armcc` 缺失 / `Target not created`，先安装 legacy ARM Compiler 5；**不要**自行切到 AC6 后盲改语法（可能引入大量告警/错误）。若必须切 AC6，逐个修编译错误并单独验证。
4. 选 Target **`USBD_AUDIO`**；宏 `USE_HAL_DRIVER,STM32F407xx,USE_USB_FS` 与优化等级保持原样；IncludePath 已含 `User / Drivers / CMSIS / HAL_Driver\Inc / Middlewares / USB Core\Inc / Class\AUDIO\Inc / USB_APP`，无需手加。
5. `Project → Rebuild all target files`（F7）。若报 `HAL_xxx` 未定义，检查 `User\stm32f4xx_hal_conf.h` 里对应模块使能宏。
6. 产物 `Output\atk_f407.hex`（`CreateHexFile=1` 已开）。目录里已有编好的 hex，可先直接用于验证流程。
7. 预期 0 Error。**编译通过只说明 HAL 工程完整，不代表能在 V2.7 / WM8978 板上出声。**

> 本工程**不是 CubeMX 生成**：没有 `.ioc`，`main.c` 里没有 `USER CODE BEGIN/END`。若将来并入 CubeMX 工程，必须新建 `.ioc` 并把所有改动写进 USER CODE 区间（提示词规则 9）。

### 2.2 烧录（人工）

**方式 A — SWD 调试器（推荐）**
1. ST-Link / J-Link 接 `SWDIO=PA13`、`SWCLK=PA14`、`GND`；板子独立供电时**不要**接 3.3V。
2. Keil `Options for Target → Debug` 选对应调试器；`Utilities → Use Target Driver for Flash Programming`，Flash 算法 `STM32F4xx_1024.FLM`。
3. `Download`（F8）烧 `Output\atk_f407.hex`，复位运行。
4. 连不上时按上电五步法查供电 / 复位 / 晶振 / BOOT0 / SWD 连线；HAL 工程若 `SYS→Debug` 被设成 No Debug，PA13/PA14 会被释放。

**方式 B — 串口 ISP（一键下载）**
1. USB 线接 **USB_UART**（CH340），`P10` 跳线帽把 PA9/PA10 接到 RXD/TXD。
2. BOOT0 置 1 → 复位进 system bootloader；FlyMcu / mcuisp 选 hex，勾 DTR/RTS 一键下载。
3. 下载完 BOOT0 回 0，复位运行。

> **边界声明**：以上是给你执行的步骤。智能体不烧录、不调 OpenOCD、不插拔线缆、不改跳线；不声称「已烧录 / 已枚举 / 已出声」。

### 2.3 电脑端识别与调试

| 步骤 | 操作 | 预期现象（需你实测确认） |
|---|---|---|
| 1 | USB 数据线插 **USB_SLAVE**（PA11/PA12, AF10）；不要插 USB_232；USB_HOST 不接任何外设 | — |
| 2 | 按 V2.7 实板要求，把 **USB/CAN 二选一跳线帽置于 USB 侧**（人工） | — |
| 3 | 调试串口：USB_UART → 设备管理器找 COM 口，XCOM/SSCOM **115200 8N1**；P10 跳线；避免会乱拉 DTR/RTS 的串口助手 | 串口打印 `EVAL_AUDIO_Init:%d,%d`（第二个数应为 `48000`） |
| 4 | 上电 | LCD：`STM32` / `USB Sound Card TEST` / `ATOM@ALIENTEK` / `KEY2:Vol- KEY0:vol+` / `VOLUME:70` / `USB Connecting...` |
| 5 | Windows 设备管理器 | 声音、视频和游戏控制器出现 **`STM32 AUDIO Streaming in FS Mode`**；硬件 ID `USB\VID_0483&PID_5730`；UAC 1.0 免驱 |
| 6 | 枚举成功 | LCD `USB Connected`；**LED1 常亮**（断开则灭）；**LED0 闪烁**表示程序在跑 |
| 7 | 声音设置 → 输出设备选该声卡 → 播放测试音 | 支持格式 **48 kHz / 16 bit / 2 声道** |
| 8 | 耳机插 `PHONE` 或喇叭接 `P1(SPK)` | 听音由你确认（智能体不听） |
| 9 | KEY0 / KEY2 | LCD 音量数值增减，范围 0~100 |

**故障域切分**：USB 枚举只依赖 `HAL_PCD` + USB 栈，不依赖 CODEC；但 `Audio_Init → BSP_AUDIO_OUT_Init → es8388_i2s_cfg` 会通过软件 IIC 向 `0x10` 写寄存器。若 V2.7 板上是 WM8978（`0x1A`），可能：
- **枚举成功但完全无声**（CODEC 未配置）；
- 或软件 IIC 等 ACK 阻塞，导致 **USB 配置阶段就卡住、连枚举都失败**。

两种都不能据此判断「WM8978 坏了」。先用串口/LCD 定位卡在哪一步，再按第 3 节换 CODEC 层。

---

## 3. 兼容问题清单（写清楚，只列未改任何文件）

> 全部为「原文片段 → 建议改后方向」对照，标注文件 + 函数 / 宏 + 位置。**这些是建议，未写入 D 盘或工作区任何文件**；代码适配仍暂停，需丝印确认 + `ADAPT_OK`。

| # | 位置 | 现状（原文片段） | 建议改后方向 | 影响 |
|---|---|---|---|---|
| C1 | `User\main.c:29,61-65,104-105` | `#include "./BSP/ES8388/es8388.h"`；`es8388_init(); es8388_adda_cfg(1,0); es8388_output_cfg(1,1); es8388_hpvol_set(25); es8388_spkvol_set(30);` | 换 `wm8978.h` + `WM8978_Init() / ADDA_Cfg(1,0) / Input_Cfg(0,0,0) / Output_Cfg(1,0) / HPvol_Set / SPKvol_Set` | 🔴 阻断 |
| C2 | `Drivers\BSP\ES8388\es8388.h:30` | `#define ES8388_ADDR 0x10` | WM8978 控制接口 `0X1A`、MODE=0 两线、**只写不读**、7 位寄存器 + 9 位数据 | 🔴 地址 + 时序都不同 |
| C3 | `Drivers\BSP\IIC\myiic.c`、`es8388.c` 的 `es8388_read_reg` | 支持 IIC 读回 | WM8978 只写；删读路径或加软件寄存器镜像，否则读-改-写类配置失效 | 🔴 阻断 |
| C4 | `Middlewares\USB\USB_APP\stm32f407_audio.c:55-63` `BSP_AUDIO_OUT_Init` | `es8388_i2s_cfg(0, 3); i2s_init(I2S_STANDARD_PHILIPS, I2S_MODE_MASTER_TX, I2S_CPOL_LOW, I2S_DATAFORMAT_16B_EXTENDED);` | 保留 HAL 版 `i2s_init(...)` 写法 ✅；把 `es8388_i2s_cfg(0,3)` 换成 WM8978 R4 配置 `WL=00 (16bit) / FMT=10 (I2S)` | 🔴 阻断，但 **I2S 层可直接复用** |
| C5 | `stm32f407_audio.c` 音量、`main.c:104-105` | `es8388_hpvol_set(g_volume*0.3)` | 老版 WM8978 UAC 教程用 `volume*0.63`；静音用对应寄存器 | 🟠 量纲不同 |
| C6 | `Middlewares\USB\USB_APP\usbd_conf.h:43`、`Class\AUDIO\Inc\usbd_audio.h:46` | `#define USBD_AUDIO_FREQ 48000`（注释：ST 库只支持这一个采样率） | 主线 CDC 是 **44.1 kHz**；走 UAC 需同步改描述符 `AUDIO_SAMPLE_FREQ`、`AUDIO_PACKET_SZE`、`AUDIO_OUT_PACKET`、±4 B 反馈补偿、PLLI2S 查表（老版 `{271,2,6,0}` → 44.108073 kHz，+0.0183%）；**走 CDC 则本文件不动** | 🔴 主线是 CDC |
| C7 | 工程体系 | 手写 HAL 工程，**无 `.ioc`、无 `USER CODE` 区段**（`main.c` count=0） | 目标 CubeMX + HAL：需新建 `.ioc`，改动全部放 `USER CODE BEGIN/END` | 🟠 规则 9 |
| C8 | 编译器 | `<uAC6>0</uAC6>` = AC5 | 装 legacy AC5；或谨慎切 AC6 并逐个修错误 | 🟠 编译阶段最容易卡住 |
| C9 | `.uvprojx` 源文件列表 | `sram.c`、`stm32f4xx_hal_sram.c`、`stm32f4xx_ll_fsmc.c`、`malloc.c`；实验43 另有 `sdio_sdcard.c` / `norflash.c` / FATFS / `fonts.c` / USMART | 按白名单剥离外扩 SRAM、SD 卡、SPI FLASH、字库、USMART；**LCD、KEY、LED、USART1、I2S、USB 可保留** | 🔴 白名单 |
| C10 | `readme.txt` 注意事项 4/5/8 | 只要求 P10（串口跳线）与 USB_SLAVE | V2.7 实板另有 **USB/CAN 二选一跳线**，CDC 音频必须置 USB 侧；V3 的 P5 参数不得照抄 | 🔴 人工操作 |
| C11 | `User\stm32f4xx_hal_conf.h:84` / `sys.c` | `HSE_VALUE 8000000U`，`sys_stm32_clock_init(336,8,2,7)` → 168 MHz / USB 48 MHz | ✅ 与老版教程纸面一致；但仍须 V2.7 原理图核对晶振与时钟树 | 🟠 H5 待确认 |
| C12 | `i2s.h:31-61`、`myiic.h:34-55`、`usbd_conf.c:54-59`、`key.h`、`led.h` | I2S2 PB12/PB13/PC2(AF6)/PC3/PC6；IIC PB8/PB9；USB PA11/PA12 AF10；KEY PE4/PE3/PE2/PA0；LED PF9/PF10 | 与老版教程纸面一致，**仍须 V2.7 整板原理图核对**；不自行指定 | 🟠 H3/H4/H6 |
| C13 | USB 数据通路 | ISOC OUT EP0x01 + 15 360 B 环形缓冲 + ±4 B 补偿 | CDC 主线改 bulk 接收 + 自建环形缓冲；UAC 路线可保留此机制作参考 | 🟠 两路线互斥，先 CDC |
| C14 | 授权 / 上传 | 正点原子 `Copyright (c) 2020-2032`；USB 栈 ST `SLA0044` | Phase 8 上传 GitHub 前需人工 `PUSH_OK` + 授权确认；当前不上传 | 🟠 合规 |
| C15 | 芯片丝印 | 资料包是 ES8388 驱动 | 板子原厂默认 WM8978，**丝印仍未拍到**；若实物为 ES8388，按提示词停主线、另开分支 | 🔴 主阻断 |

### 3.1 与「寄存器版」相比，HAL 版实际带来的变化

| 项 | 寄存器版（上一轮） | HAL 版（本轮） |
|---|---|---|
| 编译宏 | `STM32F407xx,USE_USB_FS` | `USE_HAL_DRIVER,STM32F407xx,USE_USB_FS` |
| BSP GPIO | `sys_gpio_set(GPIOA, SYS_GPIO_PIN11, ...)` 自研寄存器封装 | `HAL_GPIO_Init(GPIOA, &gpio_init_struct)` + `GPIO_AF10_OTG_FS` |
| I2S | `i2s_init(0,2,0,0)` 数字枚举 | `i2s_init(I2S_STANDARD_PHILIPS, I2S_MODE_MASTER_TX, ...)` HAL 常量 |
| 时钟 HSE | CMSIS 模板 `HSE_VALUE 25000000`（默认值，易踩坑） | `User\stm32f4xx_hal_conf.h` 明确 `HSE_VALUE 8000000U` ✅ |
| 软件 IIC | `sys_gpio_pin_set/get` | `HAL_GPIO_WritePin/ReadPin` ✅ |
| CODEC | ES8388 | **ES8388（没变）** |
| 采样率 | 48 kHz | **48 kHz（没变）** |
| `.ioc` / USER CODE | 无 | **仍无** |

结论：**HAL 版把「库」这一层对齐了，移植到 CubeMX 时 I2S / GPIO / PCD 的写法几乎能照搬；但 CODEC 驱动、采样率路线、CubeMX 工程结构这三项仍要改。**

---

## 4. 四件套

**① 原理说明**
UAC 声卡链：电脑（48 kHz/16 bit/立体声等时 OUT 包）→ `USB_OTG_FS` ISOC EP1 → `usbd_audio.c` 15 360 B 环形缓冲（`wr_ptr/rd_ptr` + ±4 B 补偿）→ `USBD_AUDIO_fops` → `usbd_audio_if.c` → `BSP_AUDIO_OUT_Init/Play` → `stm32f407_audio.c` → HAL `I2S2` + DMA1 Stream4 → ES8388 → SPK/PHONE。USB 枚举与 I2S 出声是两段独立链路：前者只依赖 HAL PCD + USB 栈，后者依赖 CODEC 配置。这正是「能枚举但无声」能单独出现的原因，也是提示词要求 Phase 3 先让 I2S+CODEC 独立出声、Phase 4 再灌 USB 数据的理由。

**② 完整代码**
**本轮零代码产出、零文件修改**：按你的指令只给步骤与兼容清单，且项目仍处于「暂停代码适配、待丝印确认」。第 3 节是原文 → 改后方向的对照，不是已应用补丁。真正动手需 `SILKSCREEN: WM8978` + `ADAPT_OK`，届时按规则 8 给完整「原文片段 → 改后片段」并注明文件 / 函数 / 插入位置，且遵守 CubeMX `USER CODE BEGIN/END`。

**③ 预期现象**
- 你现在得到：本清单文档；D 盘两个 HAL 工程**原封不动**；项目状态仍为「资源就绪、代码适配暂停」。
- 在**对应硬件**上按第 2 节执行：编译 0 Error（注意 AC5）；烧录成功；设备管理器出现 `VID_0483 / PID_5730` 的 `STM32 AUDIO Streaming in FS Mode`；LCD `USB Connected`；LED1 常亮、LED0 闪烁；串口 `EVAL_AUDIO_Init:70,48000`。
- ⚠️ 在 **V2.7 + WM8978** 板上直接烧这份 ES8388 固件：**不预期出声**；枚举是否成功需实测，不能由文档断言。
- 本轮**没有**联网、没有编译、没有烧录、没有枚举、没有上传。

**④ 故障排查清单**

| 现象 | 排查方向 |
|---|---|
| 报 `armcc` 缺失 / Target not created | `<uAC6>0</uAC6>` 要 AC5；装 legacy ARM Compiler 5，别盲切 AC6 |
| 报 `HAL_xxx` 未定义 | 查 `User\stm32f4xx_hal_conf.h` 模块使能宏 |
| 报缺 Device / Pack | 装 `Keil.STM32F4xx_DFP`，Device 保持 `STM32F407ZGTx` |
| 编译通过但烧不进 | SWD PA13/PA14/GND；独立供电不接 3.3V；Flash 算法 `STM32F4xx_1024.FLM` |
| 串口无打印 | P10 跳线 PA9/PA10↔RXD/TXD；115200 8N1；用 XCOM/SSCOM |
| 电脑完全不识别 USB | USB 线插 **USB_SLAVE**；V2.7 的 USB/CAN 跳线是否在 **USB 侧**；USB_HOST 不插设备；PA11/PA12 是否 AF10 |
| 识别了但无声 | CODEC 不匹配：本固件向 IIC `0x10` 写 ES8388，WM8978 在 `0x1A` → 按 C1~C5 换驱动层 |
| 枚举阶段卡住 | 软件 IIC 等 ACK 可能阻塞；用串口/LCD 定位是否卡在 `Audio_Init → BSP_AUDIO_OUT_Init` |
| 声音断续 / 爆音 | 48 kHz 等时 + ±4 B 反馈；改 44.1 kHz 需同步描述符与 PLLI2S 分频表，注意 +0.0183% 频偏 |
| 想用实验43 直接出声 | 它依赖 SD 卡 + FATFS + 字库，且同样是 ES8388；只能抽 I2S/DMA/WAV 的 HAL 写法 |
| 想上传 GitHub | Phase 8 需人工 `PUSH_OK`；先处理正点原子 / ST 授权 |

---

## 5. 仍待人工

1. 🔴 音频芯片丝印照片 → 确认 WM8978 还是 ES8388；若为 ES8388，按提示词「本项目按 WM8978 设计，ES8388 需另开分支」停止主线。
2. 🔴 V2.7 整板原理图（A 盘 `3ALIENTEK探索者STM32F4开发板原理图`）→ 解除 C10/C11/C12 的引脚与时钟待确认。
3. ⏸ 老版（2014）WM8978 版实验43/52 源码（MDK5.1 + 固件库 V1.4.0）→ 当前两份都是 V3/ES8388 版。
4. ⏸ 明确 `ADAPT_OK` 后才按第 3 节改代码。
5. ⏸ 接线前人工把 USB/CAN 跳线帽置于 USB 侧。
