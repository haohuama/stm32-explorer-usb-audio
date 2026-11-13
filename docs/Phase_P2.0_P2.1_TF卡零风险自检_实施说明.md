# P2.0 接口契约 + P2.1 TF 卡零风险自检 · 实施说明

> 日期：2026-11-13　工程：`C:/stm32TEST`（Keil `atk_f407.uvprojx`，ARMCLANG V6.16）
> 依据：微信文档《下面按当前状态接下来要做做完初.docx》模块 2 规划
> 批复：用户 2026-11-13 16:54 批准解除 SD 白名单 / SDIO 优先 / 实体按键 / MIT 参考
> 状态：**代码已落地，本机 ARMCLANG 逐文件编译通过（0 error / 0 warning），待用户 Keil 全量 Rebuild + 烧录实测**

---

## 0. 范围声明（先说清楚这一步不做什么）

| 本步做了 | 本步【没做】 |
|---|---|
| P2.0 统一切源接口契约与状态机骨架 | 不播放任何声音 |
| TF 卡 SDIO 底层（轮询读扇区） | 不碰 I2S / DMA / WM8978 / USB |
| FatFs R0.14b 移植 + 单卷适配 | 不写 TF 卡（`FF_FS_READONLY=1`） |
| `f_mount` → 列目录 → 找 WAV → 读头 → 校验格式 | 不做 LCD / 按键 / 歌词 / 封面 |
| 全部输出只走 CH340 → USART1 | CDC 口不打印（遵守项目约定） |

**每步验收铁律**：本步完成后，**USB 模式必须仍能正常放歌**。自检代码插在 `main.c` 里
`MX_USART1_UART_Init()` 之后、`audio_i2s_init()` / `audio_stream_start()` /
`MX_USB_DEVICE_Init()` **之前**，且自检失败只打印错误、不 `while(1)`、不改变后续流程。

---

## 1. 原理说明

### 1.1 模块 2 的本质：换数据源，不重建播放器

Phase 4 已实测跑通的输出链：

```
audio_stream_push() → 32KB 环形 → DMA 双缓冲 → I2S2 → WM8978 → 喇叭
                        ↑
                  唯一需要换的是"谁往这里喂数据"
        模块1: USB CDC 中断推  →  模块2: TF 卡 f_read 拉
```

所以 P2.1 **完全不碰音频链**，只验证上游能不能读到合法的 PCM 数据。这样任何异常都
能被单一归因到「SDIO / FATFS / 卡 / 文件格式」，不会和音频问题混在一起。

### 1.2 为什么先做 P2.0（接口契约）

规划文档把「切源状态机」放在 P2.7，但模块 1 已要求补 `src_start/stop`、模块 3 也要接
同一套。若先把 TF 播放写死在 `main.c`，到 P2.7 必然返工。因此先定 `audio_source.h`
的 `src_ops_t` 契约：每个源实现 `start / stop / is_available / feed / duration_ms / path`，
状态机统一负责切换与播放进度。

**`playback_ms` 必须由 DMA 实际消费的字节数推算**（`consumed / 176400 * 1000`），不能
用 `HAL_GetTick()` 累加——欠载、暂停、切歌都会让墙钟漂移，LRC 逐行高亮会越走越偏。
本步只提供 `src_add_consumed_bytes()` 接口，P2.2 在 DMA refill 回调里接一行即可。

### 1.3 硬件与冲突核对（用户批复第 2 条）

**SDIO 引脚（F407 芯片固定复用，与 V2.7 / V3 板版本无关，不属"V3 参数"）**

| 信号 | 引脚 | 复用 |
|---|---|---|
| SDIO_D0 / D1 / D2 / D3 | PC8 / PC9 / PC10 / PC11 | AF12 |
| SDIO_SCK | PC12 | AF12 |
| SDIO_CMD | PD2 | AF12 |

两个独立来源交叉验证一致：
- MIT LibDriver `project/stm32f407/usr/src/stm32f4xx_hal_msp.c` L322–L339
- 正点原子实验43 `Drivers/BSP/SDIO/sdio_sdcard.c` 的 `HAL_SD_MspInit`

**与现有外设零冲突**

| 已有外设 | 占用 | 结论 |
|---|---|---|
| I2S2 | `DMA1_Stream4/Ch0`，PB12/PB13/PC3/PC6 | 不同 GPIO、不同 DMA 控制器 |
| USB CDC | `OTG_FS_IRQ`，PA11/PA12 | 不占 `SDIO_IRQn` |
| CH340 日志 | USART1，PA9/PA10 | 不冲突 |
| FSMC LCD（后续） | PD0/1/4/5/8/9/10/14/15、PE、PF12、PG12、PB15 | **不含 PD2**，不冲突 |

**本阶段 SDIO 完全不启用 DMA、不启用中断**：用 `HAL_SD_ReadBlocks()` 轮询读扇区，
不占 `DMA2_Stream3/6`、不占 `SDIO_IRQn`。因此与 I2S/USB 的 DMA 与中断冲突风险为 0。
时钟 `ClockDiv=4` → 48MHz/(4+2)=8MHz（1-bit ≈ 1MB/s，远高于 WAV 的 176400 B/s）。
不采用正点原子例程的 `__disable_irq()` 保护——那会干扰 USB/I2S，改用降速留余量。

**时钟无需改动**：`main.c` 的 `SystemClock_Config` 已配 `PLLQ=7` → PLL48CLK=48MHz，
SDIO 与 USB 共用，天然满足。

### 1.4 源码来源与许可证纪律

| 文件 | 来源 | 许可 |
|---|---|---|
| `ff.c` / `ff.h` / `ffunicode.c` | ChaN FatFs **R0.14b** 原版（`E:/源码备份/实验43` 中的 FatFs 中间件） | FatFs License（BSD-style），原版权头完整保留，`LICENSE.txt` 已随附 |
| `ffconf.h` / `diskio.h` / `diskio.c` | **本项目自写** | — |
| `sdio_sd.c/.h` | **本项目自写**，引脚依据上述两个来源的公开硬件事实 | — |
| `audio_source.*` / `wav_probe.*` / `p2_selftest.*` | **本项目自写** | — |

> 明确排除：实验43 是 **V3 / ES8388** 工程，其 `es8388.c` / `audioplay.c` / `wavplay.c`
> 等音频与 CODEC 代码**一律未搬**；其 `diskio.c` / `diskio.h` / `ffsystem.c` 带正点原子版权
> （不在用户批准的 MIT 范围内），**未搬**，改为本项目自写。
> MIT 的 LibDriver `sdio.c` 仅用作引脚/初始化时序的**事实参考**，未复制代码；
> 用户批复允许使用，如需在 P2.2 引入 DMA 版，须保留原 MIT 版权头。

**FatFs 关键配置**（`ffconf.h`）：`FF_FS_READONLY=1`、`FF_USE_LFN=1`（静态工作缓冲，
不引入 `malloc`）、`FF_CODE_PAGE=936`(GBK，与 LCD 字库一致)、`FF_FS_NORTC=1`
（不用 `get_fattime`）、`FF_FS_EXFAT=0`、`FF_VOLUMES=1`、`FF_FS_TINY=1`。
因此**不需要** `ffsystem.c`，也不需要动 `Heap_Size`。

---

## 2. 完整代码 / 文件清单

### 2.1 新增文件（10 个）

| 路径 | 作用 |
|---|---|
| `Middlewares/FATFS/ff.c` `ff.h` `ffunicode.c` | ChaN FatFs R0.14b 原版 |
| `Middlewares/FATFS/LICENSE.txt` | FatFs 许可证（保留） |
| `Middlewares/FATFS/ffconf.h` | 本项目配置（只读 / GBK / 静态 LFN / 单卷） |
| `Middlewares/FATFS/diskio.h` | 标准 diskio 接口声明（自写） |
| `Middlewares/FATFS/diskio.c` | 单卷 SD 适配（轮询读、4 字节对齐中转） |
| `User/Hardware/SDIO/sdio_sd.h/.c` | SDIO BSP + `HAL_SD_MspInit` 强符号 |
| `User/APP/audio_source.h/.c` | P2.0 切源接口契约与状态机 |
| `User/APP/wav_probe.h/.c` | WAV 头解析 + 44.1k/16bit/立体声校验 |
| `User/APP/p2_selftest.h/.c` | P2.1 自检入口（挂载/列目录/读头/打印） |

### 2.2 修改文件（2 个）

**① `User/main.c`**

原文：
```c
#include "i2s_audio.h"
#include "usb_device.h"

UART_HandleTypeDef huart1;
```
改后：
```c
#include "i2s_audio.h"
#include "usb_device.h"
#include "audio_source.h"      /* P2.0 统一切源接口契约 */
#include "p2_selftest.h"       /* P2.1 TF 卡零风险自检 */

UART_HandleTypeDef huart1;
```

原文：
```c
    uart_puts("44.1k/16bit/立体声 / 电脑经虚拟串口发 PCM\r\n");

    /* ---- 1. 先起 I2S（MCLK/BCLK/LRCK 立即输出）---- */
```
改后（在两者之间插入）：
```c
    uart_puts("44.1k/16bit/立体声 / 电脑经虚拟串口发 PCM\r\n");

    /* P2.0/P2.1：必须在 audio_i2s_init() / audio_stream_start() /
       MX_USB_DEVICE_Init() 之前 —— 此时 I2S DMA 与 USB 中断均未启动 */
    src_init();                                   /* 纯内存操作 */
    (void)p2_selftest_run(uart_puts, uart_put_u32);

    /* ---- 1. 先起 I2S（MCLK/BCLK/LRCK 立即输出）---- */
```
> 位置是硬约束：SDIO 轮询读扇区期间若 USB 中断或 I2S DMA 已在运行，可能相互拖慢。

**② `Projects/MDK-ARM/atk_f407.uvprojx`**

- `Drivers/STM32F4xx_HAL_Driver` 组新增：`stm32f4xx_hal_sd.c`、`stm32f4xx_ll_sdmmc.c`
  （Phase 4 同款坑：这两个 `.c` 原本在 `Drivers/Src` 里但**没加入工程**，不补必报
  `L6218E Undefined symbol SDMMC_*`）
- 新建 `Middlewares/FATFS` 组：`ff.c`、`ffunicode.c`、`diskio.c`
- 新建 `User/APP` 组：`sdio_sd.c`、`audio_source.c`、`wav_probe.c`、`p2_selftest.c`
- 两处 `IncludePath` 各追加：`../../Middlewares/FATFS`、`../../User/Hardware/SDIO`、`../../User/APP`

> `User/stm32f4xx_hal_conf.h` 里 `HAL_SD_MODULE_ENABLED` **已开**（L64），无需改动。

### 2.3 已做的静态/编译验证

- 本机 `C:/Keil_v5/ARM/ARMCLANG/Bin/armclang.exe` 以工程相同宏
  (`USE_HAL_DRIVER,STM32F407xx`) 与全部 include 路径，对 **10 个 .c 逐个真实编译**：
  **全部 0 error / 0 warning**。
- `fromelf` 确认 `HAL_SD_MspInit` 在我们文件里是**强符号 `Gb`**、在 `hal_sd.c` 里是
  **weak `Wk`**，链接器会正确选强符号（与 Phase 4 的 `HAL_PCD_MspInit` 同模式）。
- 确认 `FF_USE_LFN=1` / `FF_FS_NORTC=1` / `FF_FS_READONLY=1` 下 ff.c **不引用**
  `ff_memalloc` / `get_fattime` / `disk_write`，无需 `ffsystem.c`、无需加大堆。
- `uvprojx` 通过 XML 解析校验；所有 `.c` 路径逐一确认存在。

---

## 3. 预期现象

### 3.1 编译

Keil → `Project → Clean` → **Rebuild**：预期 **0 Error / 0 Warning**，生成 `atk_f407.axf`。

### 3.2 串口输出（CH340 的 COM 口，115200，按 RESET）

**插了 FAT32 格式的 TF 卡、根目录有 44.1k/16bit/立体声 WAV 时：**

```
==== Phase4  USB CDC -> I2S2 -> WM8978 ====
44.1k/16bit/立体声 / 电脑经虚拟串口发 PCM

==== P2.1  TF card / FATFS zero-risk self-test ====
SDIO PC8-PC12+PD2 AF12 | polling read | NO DMA, NO IRQ
[P2.1] f_mount     : OK
[P2.1] sector size : 512 B
[P2.1] sector count: 15523840
[P2.1] root dir:
  - SONG_001.WAV  30968000 B
  - 爱错(Live) - 王力宏.wav  42800000 B
[P2.1] entries     : 2
[P2.1] wav files   : 1
[P2.1] probe file  : SONG_001.WAV
[P2.1] header bytes: 512
    rate=44100 Hz  bits=16  ch=2  fmt=1
    byte_rate=176400 B/s  data=30967956 B  offset=44
    duration=175555 ms
    [OK] 适配本工程 I2S: 44100Hz/16bit/立体声 PCM
[P2.1] result      : PASS  (no audio touched)
==== P2.1 end ====

[1] I2S2 init : OK
[2] WM8978_Init: OK (I2C 全部 ACK)
[3] PlayMode  : ... SPK vol=0x3F(+6dB)
[4] audio stream: 双缓冲循环启动（静音待数据）
[5] USB CDC    : 已启动，等主机枚举 + 发 PCM
...
... USB CDC running, ring=0 bytes
```

> 中文名能否显示取决于串口助手编码（GBK）。**这只是显示问题，不影响挂载与解析**。

**没插卡 / 挂载失败时**（不影响主线，USB 照常可用）：
```
[P2.1] f_mount FAIL code=3
  check: TF card inserted? FAT/FAT32 formatted? 3.3V?
  sd_last_error=1
[1] I2S2 init : OK
...
[5] USB CDC    : 已启动 ...
```

### 3.3 回归验收（必做）

自检跑完后，**不改动任何东西**，插 USB_SLAVE 跑：
```
py Tools/host_cdc_sender.py -p COMx -f Tools/song.wav --gain 1.0
```
喇叭应照常放歌。若 USB 模式被破坏，说明本步引入了副作用，回滚 `main.c` 的插入段即可
（新增文件与工程分组可保留，不参与编译也无影响）。

---

## 4. 排查清单

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 编译报 `L6218E: Undefined symbol SDMMC_*` | `stm32f4xx_ll_sdmmc.c` 没进工程 | 确认 uvprojx 的 HAL 组里有该文件 |
| 编译报 `Undefined symbol HAL_SD_*` | `stm32f4xx_hal_sd.c` 没进工程 / `HAL_SD_MODULE_ENABLED` 未开 | 同上；宏在 `User/stm32f4xx_hal_conf.h:64` |
| 编译报 `Undefined symbol ff_uni2oem` | `ffunicode.c` 没进工程（936 代码页需要） | 加入 `Middlewares/FATFS` 组 |
| 编译报 `FF_DEFINED != FFCONF_DEF` | `ffconf.h` 与 `ff.h` 版本不匹配 | 两者应同为 R0.14b / `86631` |
| `f_mount code=3` (`FR_NOT_READY`) | 卡没插 / 卡未初始化 / 接触不良 / 供电不足 | 重新插卡；确认 3.3V；换一张 ≤32GB 的卡 |
| `f_mount code=13` (`FR_NO_FILESYSTEM`) | 卡是 exFAT 或 NTFS | 在 PC 上格式化为 **FAT32**（`FF_FS_EXFAT=0`） |
| `f_mount` 成功但目录为空 | 文件放在子目录 / 卡上没文件 | 把 WAV 放根目录 |
| `sd_last_error=1` (`HAL_ERROR`) | SDIO 初始化/识别失败 | 检查 PC8–PC12 / PD2；确认 AF12；把 `ClockDiv` 从 4 调到 8 再试 |
| 挂载成功但读头 `f_read FAIL` | 卡读取超时 / 时钟偏快 | `ClockDiv` 调到 8（4MHz）；或换卡 |
| 中文歌名乱码 | 串口助手不是 GBK / 文件名为 UTF-8 | 只影响显示，不影响功能；LCD 侧同样用 GBK 字库 |
| `[WARN] 格式不符 flags=...` | WAV 不是 44.1k/16bit/2ch | 用 ffmpeg 转：`ffmpeg -i in.mp3 -ac 2 -ar 44100 -c:a pcm_s16le out.wav` |
| 自检后 USB 放歌有杂音/中断 | 自检不应影响后续；若出现，检查自检是否有 `while(1)` 或残留中断 | 先注释掉 `p2_selftest_run(...)` 一行验证归因 |
| RAM 不够 / 链接溢出 | `FILINFO.fname[256]` + `LfnBuf[512]` + 32KB 环形 | 128KB RAM 足够；若紧张把 `FF_LFN_BUF` 降到 64 |

### 4.1 关键约束备忘（P2.2 之前别踩）

1. **`f_read` 只能在主循环按环形低水位调用，禁止进 DMA 中断**。
2. **切歌流程**：静音 → 停 DMA → 清环形 → 换文件 → 启 → 取消静音。
3. **`playback_ms` 用 `src_add_consumed_bytes()`**，不用 `HAL_GetTick()`。
4. 若 P2.2 轮询吞吐不足，再评估 SDIO DMA（`DMA2_Stream3/6`，与 `DMA1_Stream4` 不同控制器，
   仍不冲突）或 4-bit 总线；届时须重新核对与 USB 中断的响应延迟。
5. 本步**未引入** `lcd.c/font.c`、按键、LRC、封面——那些是 P2.3~P2.6，逐步加。

---

## 5. 下一步（本步验收通过后）

- **P2.2**：把 TF 卡 `f_read` 接进 `audio_stream_push()`，实现 `src_ops_t` 的 TF 源，
  在 DMA refill 里接 `src_add_consumed_bytes()`，打通 TF 模式出声。
- **P2.3**：实体按键 KEY0/1/2/WK_UP + LCD 列表/播放页 + 统一切歌流程。
- 每一步都回归「USB 模式仍能放歌」。
