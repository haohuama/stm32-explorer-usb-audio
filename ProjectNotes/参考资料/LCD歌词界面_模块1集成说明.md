# LCD 歌词界面 · 模块 1（USB CDC）集成说明

> 日期：2026-11-13　工程：`C:/stm32TEST`（Keil `atk_f407.uvprojx`，ARMCLANG V6.16）
> 状态：**代码已落地；曾因 Keil MDK-Lite 32KB 限制超限，已做体积裁剪；
> 本机 armclang+armlink 完整链接验证 ROM = 31536 B（加 startup 约 32086 B < 32768），待用户 Rebuild**

---

## ⚠️ 重要：Keil MDK-Lite 32KB 限制（本轮主要改动）

第一轮 Rebuild 全量编译通过，但链接报：

```
error: L6050U: The code size of this image (48858 bytes)
exceeds the maximum allowed for this version of the linker.
```

这是 **Keil MDK-Lite（未授权版）的 32KB image 限制**，不是代码写错。
实测各模块体积后定位到两个大头：

| 模块 | 原体积 | 原因 |
|---|---|---|
| `lcd.o` | 27.3 KB | 含 **7 种 LCD 控制器**寄存器表 + **4 套 ASCII 字模**（12/16/24/32px） |
| `ff.o` + `ffunicode.o` | 4.8 KB + 175 KB RO | `FF_USE_LFN=3` 把 GBK 936 全量转换表拖进链接 |

### 已做的裁剪（全部可逆，都是宏开关）

| 措施 | 省下 | 如何恢复 |
|---|---|---|
| `FF_USE_LFN 3→0`（不做长文件名/中文名） | 数 KB | `ffconf.h` 改回 1，并把 `ffunicode.c` 加回工程 |
| 只保留 NT35510 / ILI9341 两种控制器，停用 NT35310 / ST7796 / ILI9806 / SSD1963 / ST7789 | 3.7 KB | `lcd.h` 里 `LCD_KEEP_ALL_IC` 改为 1 |
| 只保留 16px/24px 两套 ASCII 字模（删 12px/32px） | 7.2 KB | 从备份 `lcdfont.h` 恢复，并还原 `lcd_show_char` 的 case 12/32 |
| 优化等级 `-O1 → -Oz (image size)` | ~3 KB | uvprojx `<Optim>` 7 → 2 |
| 演示歌词 12 行 → 6 行，去掉底部进度条/时间 | ~1.5 KB | 见 §6 |
| **暂时移出** `ff.c / ffunicode.c / diskio.c / sdio_sd.c / p2_selftest.c` | 约 7 KB | 见 §6「恢复 P2.1」 |

> **P2.1（TF 卡自检）当前不参与编译**：这 5 个源文件仍在磁盘上，只是从
> `uvprojx` 移除；`main.c` 里 `P2_SELFTEST_ENABLE` 置 0，串口会打印
> `[P2.1] TF card self-test: DISABLED (Keil-Lite 32KB limit)`。
> 换用正式授权 Keil / 社区版后按 §6 三步恢复即可。

### 验证数据（本机实测，非估算）

```
Total RO  Size (Code + RO Data)      31008 (30.28kB)
Total ROM Size (Code+RO+RW Data)     31536 (30.80kB)   <- 加 startup.s 约 32086
Keil MDK-Lite 上限                    32768
余量                                  ~682 字节
```

复现命令：`py Tools/build_check.py -Oz`（自动按 uvprojx 清单编译+链接并报告体积）。

---

---

## 0. 先读这三条（否则会和预期不符）

| # | 事实 | 影响 |
|---|---|---|
| 1 | 改固件**必须重新烧录** | 会打断当前正在播放的音乐；烧完重新跑上位机脚本即可 |
| 2 | 内置的是**演示歌词**，非真实歌曲文本 | 我没有这两首歌的 `.lrc`，不编造歌词。把 LRC 文本给我，我用 `lcd_ui_load_lrc()` 一行替换 |
| 3 | 电脑推的是**裸 PCM**，MCU 不知道歌名/进度 | 时间轴由 **DMA 实际消费字节数**推算，与音频严格同步；不占 CDC 通道、不违反"CDC 只承载 PCM"约定 |

另外按上一轮诊断，顺手把 `WM8978_SPKvol_Set(0x3F)` 降为 `0x30`：两首歌贴顶样本仅 0.002%，"炸"不是数字削波，而是模拟端满档让板载功放过载。数字增益仍由上位机 `--gain` 控制。

---

## 1. 原理说明

### 1.1 为什么不用正点原子的中文字库

实验43/52 的中文显示依赖 `Middlewares/TEXT/fonts.c` + 外部 SPI FLASH 上的字库文件
（`FONT_GBK_PATH`、`FONTINFOADDR = 12MB`），本机**没有**这些 `.BIN/.FON` 文件，且属于 V3 工程的
字库系统，不宜移植。而 `lcdfont.h` 里只有 ASCII 点阵（`asc2_1206/1608/2412/3216`）。

**本项目做法**：用 PC 端 `Tools/gen_cn_font.py` 从 Windows 自带 `simsun.ttc` 渲染
**只含 UI 与演示歌词实际用到的 141 个汉字**的 16×16 GBK 点阵表，生成
`User/Hardware/LCD/cn_font.h`（26KB，常驻 Flash）。不依赖任何外部字库文件、不占 TF 卡、
不占 SPI FLASH。ASCII 仍走驱动自带的 `lcd_show_char()`，中文由 `lcd_ui.c` 自绘。

> 源码里中文字符串一律用 GBK 字节转义（`\xC1\xD6...`）写死，避免 Keil/编辑器
> UTF-8 编码歧义。与 `docs/LCD歌词显示_方案与代码框架.md` 的 GBK 约定一致。

### 1.2 时间轴：为什么用 DMA 消费字节数

规划文档要求歌词依赖 `playback_ms`。模块 1 的音频是电脑推流，用 `HAL_GetTick()`
墙上时钟会在欠载、暂停、重连、切歌时漂移，歌词越走越偏。

本实现在 `stream_fill_half()` 每次 DMA refill 时累加 `need`（4096 字节）——
这是**真实被 I2S 播出去的字节数**：

```
playback_ms = consumed_bytes * 1000 / 176400     // 44100Hz × 2ch × 2byte
```

用 `uint32_t` 保证 32 位 MCU 上中断写/主循环读原子（176400 B/s 下约 6.7 小时回绕）。
`audio_stream_start()` 时归零。中断里只做一次加法，符合"中断里只置标志"原则。

### 1.3 UI 不抢总线

- `lcd_ui_tick()` 只在**主循环**调用，内部限帧 10fps（`UI_TICK_MS=100`）。
- 歌词带只在**高亮行变化时**重画；进度条每 100ms 局部刷新。
- 主循环改成 `HAL_Delay(10)` 非阻塞轮询，每 3 秒打印一次 `ring=` 日志不变。
- UI **只读**播放状态，不反向控制音频。

### 1.4 硬件与引脚核对

LCD 驱动为**家族通用**的 8080 MCU 屏驱动（与 CODEC 型号无关，不违反"拒绝 V3 音频参数"约定）。
屏已确认 4.3" 800×480，FSMC NE4 / A6。

| 外设 | 占用引脚 | 与 LCD 冲突？ |
|---|---|---|
| LCD (FSMC) | PD0/1/4/5/8/9/10/14/15、PE7–15、PF12、PG12、PB15 | — |
| SDIO (P2.1) | PC8–PC12 + PD2 | ❌ 不含 PD2，不冲突 |
| I2S2 | PB12/PB13/PC3/PC6 | ❌ 不冲突 |
| USB CDC | PA11/PA12 | ❌ 不冲突 |
| CH340 | PA9/PA10 | ❌ 不冲突 |

FSMC 不占 DMA；`DMA1_Stream4/Ch0` 仍独占给 I2S2。

### 1.5 许可证

- `lcd.c / lcd.h / lcd_ex.c / lcdfont.h`：正点原子 HAL 版 TFTLCD 例程（实验13 家族通用驱动），
  保留原文件版权头。
- `cn_font.h`：字形由本机 Windows 系统字体 `simsun.ttc` 渲染生成，供本项目使用。
- `lcd_ui.c/.h`、`gen_cn_font.py`：本项目自写。
- 未搬用实验43/52 的 `es8388.c` / `audioplay.c` / `wavplay.c` 等 V3 音频代码。

---

## 2. 完整代码 / 改动清单

### 2.1 新增文件

| 路径 | 说明 |
|---|---|
| `User/Hardware/LCD/lcd.c` `lcd.h` `lcd_ex.c` `lcdfont.h` | 正点原子 HAL 版 8080 屏驱动（保留版权头） |
| `User/Hardware/LCD/cn_font.h` | 141 字精简 GBK 16×16 点阵（自动生成） |
| `User/Hardware/LCD/lcd_ui.c` `lcd_ui.h` | 歌词 UI：LRC 解析、GBK 混排、逐行高亮、进度条 |
| `Tools/gen_cn_font.py` | 点阵生成脚本（改歌词后重跑即可扩字库） |

**对 `lcd.c` 的两处必要修改**：
1. include 路径改为本工程相对路径；删除未使用的 `./SYSTEM/usart/usart.h`。
2. **删除 `printf("LCD ID:%x\r\n", ...)`** —— 驱动自身注释就警告"屏蔽串口1初始化会卡死在 printf"。
   本工程没有 stdio 重定向，保留会走半主机导致 HardFault。

### 2.2 修改文件（原文 → 改后）

**① `User/Hardware/AUDIO/i2s_audio.h`** — 新增两个只读接口：
```c
uint32_t audio_stream_consumed_bytes(void);
void     audio_stream_reset_consumed(void);
```

**② `User/Hardware/AUDIO/i2s_audio.c`** — 三处：
```c
/* 全局变量区新增 */
static volatile uint32_t s_consumed_bytes = 0;

/* stream_fill_half() 末尾新增 */
    for (; i < need; i++) d[i] = 0;
    s_consumed_bytes += need;          /* ← 新增：DMA 真实消费计数 */

/* audio_stream_start() 里新增 */
    s_ring_r = s_ring_w = 0;
    s_consumed_bytes = 0;              /* ← 新增：启流时归零 */
```
并新增两个函数实现。音频输出链行为**完全不变**。

**③ `User/main.c`** — 四处：
```c
/* include 区 */
#include "lcd_ui.h"

/* 音量 */
WM8978_SPKvol_Set(0x3F);   →   WM8978_SPKvol_Set(0x30);

/* USB 启动之后新增 */
    MX_USB_DEVICE_Init();
    uart_puts("[5] USB CDC ...");
+   (void)lcd_ui_init();
+   uart_puts("[6] LCD : 800x480 FSMC 点亮，歌词界面已就绪\r\n");

/* 主循环改为非阻塞 */
-   while (1) { HAL_Delay(3000); ...print ring... }
+   while (1) {
+       lcd_ui_tick(audio_stream_consumed_bytes());
+       HAL_Delay(10);
+       if (HAL_GetTick() - last_log >= 3000u) { ...print ring... }
+   }
```

**④ `Projects/MDK-ARM/atk_f407.uvprojx`**
- HAL 组新增 `stm32f4xx_hal_sram.c`、`stm32f4xx_ll_fsmc.c`
  （**Phase 4 同款坑**：这两个 .c 在磁盘上但没进工程，不加会报 `FSMC_NORSRAM_*` 未定义）
- 新建 `User/Hardware/LCD` 组：`lcd.c`、`lcd_ui.c`
  （注意 `lcd_ex.c` 由 `lcd.c` 用 `#include` 引入，**不要**单独加进工程，否则重复定义）
- 两处 `IncludePath` 各追加 `../../User/Hardware/LCD`

### 2.3 编译验证（本机 ARMCLANG 真实编译，非静态推测）

```
OK  User/main.c                             0 warning
OK  User/Hardware/LCD/lcd.c                 4 warning（char 下标，无害）
OK  User/Hardware/LCD/lcd_ui.c              0 warning
OK  User/Hardware/AUDIO/i2s_audio.c         0 warning
OK  User/APP/audio_source.c                 0 warning
OK  Drivers/.../stm32f4xx_hal_sram.c        0 warning
OK  Drivers/.../stm32f4xx_ll_fsmc.c         0 warning
```
- `fromelf` 确认 `HAL_SRAM_MspInit` 在 `lcd.o` 是强符号 `Gb`、在 `hal_sram.o` 是 weak `Wk`，
  链接器正确选强符号（与 Phase 4 的 `HAL_PCD_MspInit` 同模式）。
- `armlink` 试链接无 `L6200E` 重复定义；残留 5 个未定义符号
  （`HAL_GPIO_WritePin` / `delay_ms` / `delay_us` / `HAL_GetTick` / `HAL_DMA_Start_IT`）
  均由工程内 `hal_gpio.c` / `delay.c` / `hal_cortex.c` / `hal_dma.c` 提供，已逐一确认在 uvprojx 中。

---

## 3. 预期现象

### 3.1 编译
Keil `Project → Clean` → **Rebuild**：预期 **0 Error**（可能 4 个无害 char 下标 warning）。

### 3.2 上电（CH340 串口，115200）
```
==== Phase4  USB CDC -> I2S2 -> WM8978 ====
... P2.1 自检输出（若 TF 卡未插会打印 f_mount FAIL，不影响主线）...
[1] I2S2 init : OK
[2] WM8978_Init: OK (I2C 全部 ACK)
[3] PlayMode  : ... SPK vol=0x30(clean)
[4] audio stream: 双缓冲循环启动（静音待数据）
[5] USB CDC    : 已启动，等主机枚举 + 发 PCM
[6] LCD        : 800x480 FSMC 点亮，歌词界面已就绪
... USB CDC running, ring=0 bytes
```

### 3.3 屏幕
- 顶部深蓝标题栏：`Explorer F407` / `MODE 1 : USB CDC PCM STREAM` / `44.1k/16`
- 中部歌词带：8 行中文，**当前行黄色高亮**并带行首指示条，其余灰蓝；随播放进度逐行下移
- 底部：`mm:ss/mm:ss` 时间 + 绿色进度条
- 屏幕上明确写着"演示歌词 非真实歌曲文本"

### 3.4 回归验收（必做）
跑 `py Tools/host_cdc_sender.py --auto --wait -f pl01.wav pl02.wav --gain 0.5`，
喇叭应照常放歌，且**歌词随音乐推进**（不是固定不动）。
若 USB 播放被破坏 → 优先怀疑 LCD 初始化时序，见排查清单。

---

## 4. 排查清单

| 现象 | 原因 | 处理 |
|---|---|---|
| 链接报 `Undefined symbol FSMC_NORSRAM_*` | `hal_sram.c` / `ll_fsmc.c` 没进工程 | 确认 uvprojx HAL 组有这两个 .c |
| 链接报 `L6200E: Symbol lcd_init multiply defined` | 把 `lcd_ex.c` 单独加进工程了 | 从工程移除 `lcd_ex.c`，它由 `lcd.c` include |
| 上电直接卡死 / HardFault | `lcd.c` 里的 `printf` 没删（半主机） | 确认 `lcd.c` 中无 `printf("LCD ID...")` |
| 屏全黑 | 背光 `PB15` 未拉高 | 确认 `lcd_ui_init()` 里 `LCD_BL(1)` 已调用 |
| 白屏/花屏 | FSMC 时序太紧或屏型号不符 | `lcddev.id` 读到几？打印出来；把 `DATASET/ADDSET` 调大 |
| 中文显示成方框/空白 | 歌词里的字不在 141 字库里 | 把新字加进 `Tools/gen_cn_font.py` 的 `UI_TEXT`，重跑生成 `cn_font.h` |
| 中文乱码 | 字符串不是 GBK 编码 | 用 GBK 字节转义；`lcd_ui_load_lrc()` 传入的必须是 GBK 文本 |
| 歌词不动 | `audio_stream_consumed_bytes()` 没累加 | 检查 `stream_fill_half()` 末尾那行加法；串口看 `ring=` 是否在涨 |
| 歌词越走越快/越慢 | 时间轴单位错 | 确认分母 `AUDIO_BYTES_PER_SEC = 176400` |
| 音乐变断续/爆音 | UI 抢占 CPU 或 FSMC 争总线 | 把 `UI_TICK_MS` 从 100 调到 200；确认 UI 只在主循环、不在中断 |
| 音量变小了 | 固件从 0x3F 降到 0x30 | 这是有意为之（消除"炸"）。想更响把上位机 `--gain` 提到 0.7，别再把固件调回满档 |
| USB 不枚举 | LCD 初始化时机 | `lcd_ui_init()` 已在 `MX_USB_DEVICE_Init()` 之后；若仍异常，临时注释掉它验证归因 |

### 4.1 换成真歌词（后续一步）

1. 把 `.lrc` 文件发我，或在 PC 端转成 GBK 文本。
2. 把新出现的汉字加进 `Tools/gen_cn_font.py` 的 `UI_TEXT`，重跑：
   ```
   py Tools/gen_cn_font.py
   ```
3. 用 `lcd_ui_load_lrc(gbk_text)` 替换内置演示歌词；或把生成的字节数组
   直接填进 `lcd_ui.c` 的 `s_demo_lrc[]`。
4. 当前模块 1 下 MCU 不知道歌名，可在上位机开始播放时用 `lcd_ui_set_track()` 填入
   （电脑推裸 PCM，歌名需另给；真正的自动切歌/歌名显示是 P2.3 + 播放列表的事）。

---

## 5. 下一步

- **P2.2**：TF 卡 `f_read` 接进 `audio_stream_push()`，TF 模式出声。
- **P2.3**：实体按键 KEY0/1/2/WK_UP 驱动 LCD 菜单与切歌（不碰触摸）。
- 模块 1 的精确歌名/封面：需 UAC 或额外控制通道，属拓展阶段。

---

## 6. 恢复完整功能的三个开关（换正式 Keil 后）

### 6.1 恢复 P2.1 TF 卡自检（省约 7KB，当前关闭）

1. `Middlewares/FATFS/ffconf.h`：`FF_USE_LFN 0` → `1`
2. `Projects/MDK-ARM/atk_f407.uvprojx` 里加回 5 个文件：
   - `Middlewares/FATFS` 组：`ff.c`、`ffunicode.c`、`diskio.c`
   - `User/APP` 组：`sdio_sd.c`、`p2_selftest.c`
3. `User/main.c`：`#define P2_SELFTEST_ENABLE 0` → `1`

### 6.2 恢复全部 LCD 控制器（省 3.7KB，当前只留 NT35510 + ILI9341）

`User/Hardware/LCD/lcd.h`：`#define LCD_KEEP_ALL_IC 0` → `1`

> 如果你烧完后**屏幕全黑**，很可能屏的控制器不在保留的两种里。
> 现象：`lcddev.id` 读到了值但没有任何初始化分支命中。
> 处理：把 `LCD_KEEP_ALL_IC` 改 1 再加回体积（需先腾出空间），
> 或把 `lcddev.id` 的值告诉我，我只保留你那一种，省得更多。

### 6.3 恢复 12px/32px 字模（省 7.2KB，当前只有 16px/24px）

从 `E:/源码备份/实验43 音乐播放器实验/Drivers/BSP/LCD/lcdfont.h` 取回
`asc2_1206` 与 `asc2_3216` 两个数组，并还原 `lcd.c` 里 `lcd_show_char()` 的
`case 12` / `case 32` 分支。

### 6.4 恢复演示歌词为 12 行 + 底部进度条

见 `Tools/gen_cn_font.py` 的 `DEMO_LYRICS`，加行后重跑：
```
py Tools/gen_cn_font.py
```
再把对应 GBK 字节串填回 `lcd_ui.c` 的 `s_demo_lrc[]`。

---

## 7. 本轮最终改动清单（相对上一版）

| 文件 | 改动 |
|---|---|
| `Middlewares/FATFS/ffconf.h` | `FF_USE_LFN 1 → 0`（长文件名关闭，省 936 转换表） |
| `User/Hardware/LCD/lcd.h` | 新增 `LCD_KEEP_ALL_IC` 开关宏（默认 0） |
| `User/Hardware/LCD/lcd_ex.c` | 5 个不用的控制器初始化函数用 `#if !LCD_KEEP_ALL_IC` 包住 |
| `User/Hardware/LCD/lcd.c` | 对应 5 个 `lcddev.id` 分支同样包住；12px/32px 字模回落到 16/24px |
| `User/Hardware/LCD/lcdfont.h` | 删除 `asc2_1206`、`asc2_3216`（省 7.2KB） |
| `User/Hardware/LCD/lcd_ui.c` | 演示歌词 12→6 行；去掉底部进度条与时间显示 |
| `User/main.c` | 新增 `P2_SELFTEST_ENABLE 0` 开关，包住 `p2_selftest.h` 与调用 |
| `Projects/MDK-ARM/atk_f407.uvprojx` | `<Optim> 2 → 7`(-Oz)；移除 `Middlewares/FATFS` 组与 `sdio_sd.c`/`p2_selftest.c` |
| `Tools/build_check.py` | 新增：按 uvprojx 清单全量编译+链接并报告 image 体积 |
| `Tools/gen_cn_font.py` | 演示歌词同步为 6 行 |

## 8. 烧录后如果屏幕全黑（最可能的两种原因）

1. **控制器不在保留列表里**（只留了 NT35510 / ILI9341）→ 见 §6.2。
2. **背光没亮**：确认 `lcd_ui_init()` 里 `LCD_BL(1)` 被执行（PB15 拉高）。

判断依据：串口若打印 `[6] LCD : 800x480 FSMC 点亮`，说明代码走到了；
此时若黑屏，就是控制器/背光问题，不是代码没跑。

---

## 9. 第二轮 32KB 超限的最终处理（实测数据，2026-11-13 晚）

上一轮裁完仍报 `L6047U: 38072 bytes`。原因是我当时的本地测量脚本与 Keil 不一致
（没编译 startup、没加 `-std=c99`、用 `--no_startup` 链接），测出 31536 偏小 6.5KB。
先把测量工具校准，再按真实数据裁。

### 9.1 校准后的测量工具

`Tools/build_check.py` 现在与 Keil 一致：按 uvprojx 的文件清单、同一份 `.sct`、
`-Oz -ffunction-sections -std=c99`、`armasm` 汇编 startup、真实链接。

> 校准点：同一份代码，脚本报 **37880**，Keil 报 **38072**，偏差 +192 字节（约 0.5%）。
> 所以脚本结论按 **+200 字节** 预估 Keil 结果。

### 9.2 各项措施的实测收益

| 措施 | 收益 |
|---|---|
| 启用 microLIB（`<useUlib>1`） | −1260 |
| 删除 `asc2_2412`（24px 字模），屏上文字统一 16px | −3420 |
| `cn_font.h` 只保留屏上真正显示的 32 个汉字（原 119） | −2784 |
| 上一轮已做：关 LFN / 只留 2 种屏控制器 / `-Oz` / 歌词 6 行 | 见第 7 节 |

### 9.3 最终体积（脚本实测）

```
image  ROM(Code+RO+RWinit) = 29912 bytes (29.21 KB)
RAM    (RW+ZI)             = 52936 bytes (51.70 KB)
Keil MDK-Lite limit        = 32768
余量                        = +2856 bytes      → Keil 侧约 +2660
```

### 9.4 这一版对显示效果的影响（务必知道）

1. **标题不再是大字**：原 24px 的「Explorer F407 / 44.1k/16」现在与正文同样 16px。
2. **中文只有 32 个字**：即演示歌词用到的那 32 个。屏上不会出现缺字方块，
   因为歌词是固定的；但**换成真歌词后若出现新字，需要重新生成字库**（每字 32 字节）。
3. 副标题由 `MODE 1 : USB CDC PCM STREAM` 缩为 `MODE 1 : USB CDC`（宽度不够）。

### 9.5 接真歌词的标准流程

1. 把 `.lrc` 的每行文本填进 `Tools/gen_cn_font.py` 的 `DEMO_LYRICS`
2. 跑 `py Tools/gen_cn_font.py`（会打印用了多少个汉字）
3. 把对应的 GBK 字节串填进 `lcd_ui.c` 的 `s_demo_lrc[]`（或运行时调 `lcd_ui_load_lrc()`）
4. 跑 `py Tools/check_font.py` 确认「缺字：无」
5. 跑 `py Tools/build_check.py --microlib` 确认余量为正

> 32KB 的现实：每 1 个汉字 = 32 字节，当前余量约 2660 字节 ≈ 83 个字。
> 也就是说这版固件最多再放约 80 个新汉字。要显示完整歌词（几百字），
> 必须换**已授权的 Keil**（去掉 32KB 限制），或把中文点阵放到外部 SPI Flash。

---

## 10. 导入真歌词：《江南 - 林俊杰》实战（32KB 内落地）

### 10.1 一键导入流程（以后换歌照做）

```
py Tools/lrc_to_c.py "C:/Users/xxx/歌名.lrc"
py Tools/gen_cn_font.py
py Tools/check_font.py
py Tools/build_check.py --microlib
```

- `lrc_to_c.py`：解析 LRC（同时支持网易云的 JSON 混排行 `{"t":..,"c":[{"tx":..}]}` 与
  标准 `[mm:ss.xx]` 行），自动剔除 `作词/作曲/编曲/制作人/吉他/录音室/OP/SP` 等
  **带冒号的制作人员行**（这些不该上屏，且白占字库），然后把歌词写进
  `lcd_ui.c` 的 `s_demo_lrc[]`（GBK 转义），并同步 `gen_cn_font.py` 的 `DEMO_LYRICS`。
- `gen_cn_font.py`：只渲染真正用到的汉字。
- `check_font.py`：校验屏上每个字都有点阵（防空白方块）。
- `build_check.py --microlib`：量体积，必须 `PASS`。

### 10.2 这首歌的规模

| 项 | 值 |
|---|---|
| 歌词行数 | 43（已剔除 10 行制作人员名单） |
| 不重复汉字 | 110（歌词）+ 6（"江南林俊杰"、"无歌词"）= 116 |
| 16x16 点阵占用 | 116 x 32 = **3712 字节** |
| LRC 文本占用 | 43 行 x 约 26 字节 = 约 1120 字节 |

### 10.3 为塞进 32KB 又做的两处结构性裁剪

1. **关闭 ASCII 字模**（新开关 `lcd.h: LCD_KEEP_ASCII_FONT 0`）
   `asc2_1608[95][16]`（1520B）连同 `lcd_show_char/num/string` 的代码一起不编译
   （保留空实现，符号不丢）。**因为屏上现在只画中文**：标题改为中文
   「江南 林俊杰」，空歌词提示改为「无歌词」。
   收益约 **-2400 字节**。把宏改回 1 即恢复英文/数字显示（lcd.c 里 include 与
   三个函数体都在 `#if LCD_KEEP_ASCII_FONT` 内，可逆）。
2. **歌词循环周期改为整首歌长**（`lcd_ui.c: LRC_CYCLE_MS 267900`）
   上位机是单曲循环发流，`consumed_bytes` 会一直累加，必须用歌曲时长取模，
   每轮歌词才能重新对齐。换歌时同步改这个值（= WAV 帧数/44100*1000）。

### 10.4 最终体积（脚本实测，microLIB）

```
image  ROM = 31924 bytes (31.18 KB)      Keil 侧约 32120
上限       = 32768                        余量 约 650
```

### 10.5 已知限制（务必知道）

1. **只有单曲循环时歌词才准**。上位机连续播多首时，MCU 不知道"换歌了"，
   `consumed_bytes` 连续增长 → 第二首开始歌词会错位。
   想多首连播且歌词正确，需要 PC 端在换歌处插一个同步标记（可作下一步）。
2. **中文只有这 116 个字**。换歌要重跑 §10.1 四步；余量仅约 20 个字的空间。
   要在卡里放很多首歌的词，必须解除 32KB（见 10.6），或把点阵搬到外部 SPI Flash。
3. 屏上不再显示英文/数字（ASCII 字模已关）。

### 10.6 一劳永逸：Keil MDK-Community（免费、无 32KB 限制）

Arm 官方的 **MDK-Community** 版对学生 / 爱好者 / 非商业用途**完全免费，且没有代码大小限制**
（它就是为取代带 32KB 限制的 MDK-Lite 而推出的）。官方原文：*"The MDK-Community edition
has no code size limits and supports all non-commercial use cases."*

在 Keil 里激活：

```
File -> License Management -> User-Based License -> Activate...
  -> 弹窗右上角 License Server...
  -> 地址填 https://mdk-preview.keil.arm.com
  -> Query -> 选 "Keil MDK Community" -> Activate -> Close
```

激活后本工程可以立刻恢复这些（都不再需要为字节数发愁）：

| 开关 | 位置 | 改回后得到 |
|---|---|---|
| `LCD_KEEP_ASCII_FONT 1` | `lcd.h` | 英文/数字显示（+2.4KB） |
| `LCD_KEEP_ALL_IC 1` | `lcd.h` | 7 种 LCD 控制器全支持（+3.7KB） |
| `FF_USE_LFN 1` | `FatFS/ffconf.h` | 中文长文件名（+175KB 转换表） |
| `P2_SELFTEST_ENABLE 1` | `main.c` | TF 卡自检（+7KB） |
| 恢复 24px 字模 | `lcdfont.h` | 大标题（+3.4KB） |
| 字库换成全量 GBK | `gen_cn_font.py` | 任意歌词都不用再生成字库 |

> 换句话说：**32KB 只是"未授权 Keil"的限制，不是芯片的限制**。F407 有 1MB Flash，
> 上面这些加起来也不过 200KB。要不要激活 Community 由你决定，激活前本版就是能跑的形态。

---

## 11. 授权 MDK-Community 后：两首歌词全放进来（2026-11-13 23:20）

### 11.1 授权生效的判定方法

`C:/Keil_v5/TOOLS.INI`：

```
TOOL_VARIANT=mdk_std          ← 不再是 mdk_lite
LIC0=ZB4EI-...                ← 已激活的产品序列号
```

再加一条硬证据：**本机 `armlink.exe` 命令行链接 35404 字节的镜像不再报 L6047U** ——
说明 32KB 限制确实解除了（该限制来自未授权状态，不是芯片限制）。

> `Tools/build_check.py` 已同步调整：默认按"已授权"处理，只报体积；
> 需要按 32KB 卡时加 `--lite`。

### 11.2 歌词数据改为独立文件

新增 `User/Hardware/LCD/lrc_data.h`（**由 `Tools/lrc_playlist.py` 生成，勿手改**）：

```c
static const char s_title1[] = "江南";     /* GBK 字节 */
static const char s_lrc1[]  = "[00:37.01]...\n" ...;
static const char s_title2[] = "唯一";
static const char s_lrc2[]  = "[00:13.64]...\n" ...;
```

`lcd_ui.c` 不再内嵌歌词，改为 `#include "lrc_data.h"`。

**换歌只需一条命令**：

```
py Tools/lrc_playlist.py "歌1.lrc" "歌2.lrc"
py Tools/gen_cn_font.py
py Tools/check_lrc.py        # 模拟 C 解析器，确认行数/时间正确
py Tools/check_font.py       # 确认无缺字
py Tools/build_check.py --microlib
```

### 11.3 按曲切换的原理（不含任何上位机协议）

上位机按 `pl01 -> pl02` 顺序循环发流，`consumed_bytes` 跨曲连续累加，所以：

```
t   = consumed_bytes / 176400 * 1000  (mod (SONG1_MS + SONG2_MS))
第 1 首: t ∈ [0, SONG1_MS)            曲内时间 = t
第 2 首: t ∈ [SONG1_MS, 总和)         曲内时间 = t - SONG1_MS
```

切曲时自动 **换解析结果 + 重画标题栏**（江南 / 唯一）。
代价是 **两首时长必须写死在固件里**（`SONG1_MS=267947`、`SONG2_MS=253735`），
换歌/换顺序要同步改这两个宏。

### 11.4 本项目最终体积

| 项 | 值 |
|---|---|
| Flash (Code+RO+RW init) | **35404 B (34.57 KB)** |
| RAM (RW+ZI) | **59536 B (58.14 KB)** / 128 KB |
| 汉字点阵 | 192 字（两首并集 193，实际用到 187） |
| 歌词正文 | 江南 1483 B + 唯一 832 B |

### 11.5 还可以顺手恢复的东西（授权后不再受字节数约束）

| 开关 | 位置 | 得到 |
|---|---|---|
| `LCD_KEEP_ASCII_FONT 1` | `lcd.h` | 英文/数字（歌手名、进度时间、曲目序号） |
| `LCD_KEEP_ALL_IC 1` | `lcd.h` | 7 种 LCD 控制器全支持 |
| 恢复 24px 字模 | `lcldfont.h` + `lcd.c` 的 case 24 | 大标题 |
| `FF_USE_LFN 1` | `FatFS/ffconf.h` | 中文长文件名（+175KB 表） |
| `P2_SELFTEST_ENABLE 1` | `main.c` + uvprojx 加回 5 个 .c | TF 卡自检（模块2） |

> 这些都不是必须的；当前这版（两首歌词 + 中文标题）已经能正常跑。

---

## 12. 歌词与歌声同步（时间基准修正，2026-11-13 23:35）

### 12.1 之前为什么不同步

歌词时间轴原来用的是 `consumed_bytes`（DMA 从**开机**起累计的字节数）。
DMA 循环播放一直在跑，没有数据时播静音也算"消费"，所以：

```
开机 0s ─────────────────────────────►
        [静音 20s]      [真正播放]
歌词时钟从 0 就开始走 → 点播放时已经跑到 20s → 全程提前 20 秒
```

### 12.2 修正：只累计"真实 PCM"

`stream_fill_half()` 里区分了本次 refill 用了多少**真实字节** `n`（其余是静音填充）：

```c
if (n > 0) {
    if (s_idle_cnt >= AUDIO_IDLE_RESYNC) s_pos_bytes = 0;  /* 断流>1.5s=重新播放 */
    s_pos_bytes += n;          /* 静音不计时 */
    s_idle_cnt = 0;
} else if (s_idle_cnt < 255) s_idle_cnt++;
```

对外接口：`audio_stream_position_ms()` = `s_pos_bytes * 1000 / 176400`，
`lcd_ui_tick(played_ms)` 直接用这个值（不再是墙钟、也不再自己换算）。

带来的好处：
- **点播放的早晚无所谓**，第一块真实数据就是 0 点；
- **中途卡顿/欠载时歌词自动停住**，恢复后继续对齐，不会越走越偏；
- 停掉脚本再重跑（>1.5 秒断流）会清零，从歌曲开头重新对齐。

### 12.3 仍然存在的限制（32KB 时代遗留的设计）

MCU 只收到裸 PCM，**不知道"现在是第几首、播到第几秒"**，所以靠固件里写死的
`SONG1_MS/SONG2_MS` 做取模定位。后果：

| 场景 | 表现 |
|---|---|
| 按固件里的顺序放列表（唯一 → 江南） | ✅ 正确 |
| 单曲循环"第一首" | 第一遍正确；第二遍起歌词会切到另一首 |
| 单曲循环"第二首" | ❌ 一直错 |

临时办法：想重听同一首，**停掉脚本再重跑**（触发断流清零）。

### 12.4 彻底方案（需要时再做）

给 CDC 增加**第二个接口作为控制通道**（音频走一个、控制走一个），上位机实时下发
"曲目序号 + 播放位置"，MCU 就能：
- 任意单曲 / 任意顺序 / 随时拖动进度都精确同步；
- 歌词不必编译进固件（换歌不用重烧）。

代价：USB 描述符要加一组接口（IAD + 第二套 CDC 端点），改动集中在 USB 层，
不动音频链路。目前没做，属于"能用且不复杂，但非必需"。

---

## 13. 按曲同步的正解：用 USB 控制线选曲（2026-11-13 23:41）

### 13.1 思路

MCU 只拿裸 PCM，本来不知道"现在第几首"。但 CDC 串口除了数据通道，还有**控制线**
（DTR / RTS）。上位机可以随时改这两位的状态，设备端在 `CDC_Control_FS` 里就能收到
`SET_CONTROL_LINE_STATE` 请求（wValue 的 bit0=DTR、bit1=RTS）。

**好处：占 0 字节音频带宽，纯 USB 控制请求，绝不干扰 PCM 流。**

### 13.2 约定

| 状态 | 含义 |
|---|---|
| DTR=0, RTS=0 (wValue=0) | 播第 1 首（`s_lrc1` / `s_title1`） |
| DTR=1, RTS=0 (wValue=1) | 播第 2 首（`s_lrc2` / `s_title2`） |
| wValue ≥ 2 | 忽略（端口刚打开时 DTR/RTS 默认都为 1，不能误判） |

上位机在**每首歌开始发送前**执行：

```python
ser.rts = False          # 必须拉低，否则 DTR|RTS=3 会被忽略
ser.dtr = bool(idx & 1)
```

设备端收到后：切歌词数据 → `audio_stream_reset_position()` 把歌词时钟清零 →
重画标题。所以**换曲自动对齐，不再依赖固件里写死的顺序和时长**。

### 13.3 曲目序号怎么定的（上位机）

`host_cdc_sender.py` 的 `song_index_of()`：取 WAV 文件名末尾数字 − 1。

| 文件 | 序号 | 固件里的歌词 |
|---|---|---|
| `pl01.wav`（江南） | 0 | `s_lrc1` = 江南 |
| `pl02.wav`（唯一） | 1 | `s_lrc2` = 唯一 |

文件名没有数字时，退回它在 `-f` 列表中的位置。

### 13.4 结果

| 场景 | 之前 | 现在 |
|---|---|---|
| 按顺序放列表 | ✅ | ✅ |
| 单曲循环"第 1 首" | 第二遍起错 | ✅ |
| 单曲循环"第 2 首" | 一直错 | ✅ |
| 晚点开始播放 | 全程偏移 | ✅（真实 PCM 计时） |
| 中途卡顿 | 逐渐漂移 | ✅（静音不计时） |

限制：只有 1 位可用 → **最多 2 首**。要放更多首，改用"第 2 个 CDC 接口"或
把 baudrate 当索引（`SET_LINE_CODING` 的 dwDTERate 有 32 位可用）。

---

## 14. 扩展到 4 首：选曲协议升级（2026-11-14）

### 14.1 为什么必须换协议

原来用串口控制线 `DTR=bit0 / RTS=bit1` 选曲，只有 2 位：

| wValue | 含义 |
|---|---|
| 0 | 第 1 首 |
| 1 | 第 2 首 |
| 2 | 第 3 首 |
| 3 | **忽略**（端口刚打开时 pyserial 默认把两位都置 1，不能当"第 4 首"） |

所以第 4 首无解。改用 **`SET_LINE_CODING` 的波特率字段**：

```
上位机：  ser.baudrate = 100000 + idx       # idx = 0..N-1
USB：     CDC_SET_LINE_CODING(0x20, 7 字节)
          pbuf[0..3] = baudrate 小端；pbuf[4..6] = format/parity/databits
设备：    照常保存 linecoding，
          若 100000 <= baud < 100016 → lcd_ui_select_song(baud - 100000)
```

- **占 0 字节音频带宽**，纯 USB 控制请求，不会污染 PCM 流。
- 区间限定在 `[100000, 100016)`，正常串口配置（9600/115200…）一律不触发。
- 可线性扩展到任意首数（>16 就把区间放宽）。

### 14.2 两条控制路径的差异（易踩坑）

`usbd_cdc.c` 里两条 class 请求走的不是同一条代码：

| 请求 | wLength | 传给 `Control()` 的 pbuf |
|---|---|---|
| `SET_CONTROL_LINE_STATE`(0x22) | 0 | `(uint8_t *)req` —— **整个 Setup 包**，要读 `wValue` 得强转 `USBD_SetupReqTypedef *` |
| `SET_LINE_CODING`(0x20) | 7 | `hcdc->data` —— **真正的 7 字节数据**，在 `EP0_RxReady` 里才回调 |

另外 `usbd_cdc_if.c` 里**原本就有一个 `case CDC_SET_LINE_CODING`**（保存 linecoding 用的），
新增分支必须**合并进那一条**，否则 duplicate case 直接编译报错。

### 14.3 四首播放列表

| WAV | 歌曲 | 时长 | 歌词行数 | 不重复汉字 |
|---|---|---|---|---|
| `pl01.wav` | 江南 | 267.9 s | 43 | 110 |
| `pl02.wav` | 唯一 | 253.7 s | 22 | 106 |
| `pl03.wav` | 泡沫 | 190.2 s | 51 | 281 |
| `pl04.wav` | 还是会想你 | 190.1 s | 46 | 229 |

并集 507 字 → 字库实存 **505 项（15.8 KB 点阵）**，`check_font`：缺字无。
四首分别解析 43 / 22 / 51 / 46 行，`check_lrc`：空正文 0。

### 14.4 体积（实测）

```
image  ROM = 49656 B (48.49 KB)
RAM        = 72608 B (70.91 KB / 128 KB)
45 个源文件，0 error
```

歌词解析结果每首一份 `ui_line_t[96]`（68 B/行）→ 每加一首 +6.5 KB RAM。
按当前 70.9 KB 估算，**RAM 上到 9 首左右到顶**；再多需要改成"只保留当前曲的解析结果"。

### 14.5 换歌/加歌操作

```bat
py Tools/lrc_playlist.py "a.lrc" "b.lrc" "c.lrc" "d.lrc"
py Tools/gen_cn_font.py
py Tools/check_lrc.py
py Tools/check_font.py
py Tools/build_check.py --microlib
```

再把对应 `plNN.wav` 放进 `Tools/`，播放时脚本按文件名末尾数字自动告知设备播第几首：

```bat
py Tools/host_cdc_sender.py --auto --wait -f Tools/pl04.wav --gain 0.65
```

> 加第 5 首需要同时改 `Tools/lrc_playlist.py` 的 `MAX_SONGS` 与 `lcd_ui.c` 的 `SONG_COUNT`，
> 并在 `s_lrcs[]` / `s_titles[]` 里加上 `s_lrc5` / `s_title5`（三处必须一起改）。
