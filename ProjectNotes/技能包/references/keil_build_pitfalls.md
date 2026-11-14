# Keil + HAL + STM32 USB 工程：编译/链接坑与修法

在把 ST 官方 USB Device Library 接进一个原本没有 USB 的 Keil 工程时，几乎必踩下面这些坑。按出现顺序记录。

## 1. 循环包含 → 全工程 `unknown type name 'uint8_t'/'USBD_StatusTypeDef'` + `conflicting types USBD_LL_*`

**现象**：几十上百个 error，集中在 `usbd_def.h / usbd_core.h / usbd_conf.h`。

**根因**：`usbd_conf.h` 里写了 `#include "usbd_core.h"`，而 `usbd_core.h`/`usbd_def.h` 又反向 include `usbd_conf.h` → 循环，使 `usbd_def.h` 在 `uint8_t`/`USBD_StatusTypeDef` 尚不可见时被解析。

**修法**：
- `usbd_conf.h` **禁止** include `usbd_core.h`；只 `#include "stm32f4xx_hal.h"` + 宏 + `extern PCD_HandleTypeDef hpcd_USB_OTG_FS;`。
- `usbd_conf.c` 改为 `#include "usbd_core.h"`（由它连带 usbd_def.h、usbd_conf.h）。

## 2. `conflicting types for 'USBD_LL_Transmit'/'USBD_LL_PrepareReceive'`

**根因**：库声明是 `uint32_t size`，自己写成了 `uint16_t size`。
**修法**：严格照 `usbd_core.h` 的签名写：`uint32_t size`。
（同类：HAL 新版成员名是 `Sof_enable` 不是 `SOF_enable`；速度枚举是 `USBD_SPEED_FULL` 不是 `USBD_SPEED_FS`。）

## 3. 12 个 `USBD_LL_*` 重复定义 / 断流

`SetupStage/DataOutStage/DataInStage/Reset/SetSpeed/SOF/Suspend/Resume/IsoINIncomplete/IsoOUTIncomplete/DevConnected/DevDisconnected` 这 12 个已在 `usbd_core.c` 实现。**不要**在 `usbd_conf.c` 里再写空 stub（会 multiple definition + CDC 收不到数据）。
只实现绑定层 15 个：`Init/DeInit/Start/Stop/OpenEP/CloseEP/FlushEP/StallEP/ClearStallEP/IsStallEP/SetUSBAddress/Transmit/PrepareReceive/GetRxDataSize/Delay`，HAL_PCD_* 回调转调 core 版 `USBD_LL_*`。

## 4. `L6218E Undefined symbol HAL_PCD_*`

**根因**：`stm32f4xx_hal_pcd.c` 没加进工程（以及 `stm32f4xx_hal_pcd_ex.c`）。
**修法**：把两者加入 uvprojx 的 HAL 驱动组；确认 `stm32f4xx_hal_conf.h` 里 `HAL_PCD_MODULE_ENABLED` 已开。

## 5. `L6218E Undefined symbol USB_CoreInit / USB_EPStartXfer / USB_ActivateEndpoint ...`

**根因**：缺 **LL USB 底层驱动** `stm32f4xx_ll_usb.c`（被 hal_pcd.c 调用）。
**修法**：把 `stm32f4xx_ll_usb.c` 加进工程。USB 三件套齐全 = `stm32f4xx_hal_pcd.c` + `stm32f4xx_hal_pcd_ex.c` + `stm32f4xx_ll_usb.c`。
（该文件被 `#if defined(HAL_PCD_MODULE_ENABLED)` + `#if defined(USB_OTG_FS)` 包裹，F407 满足，不会编空。）

## 6. `implicit declaration of USBD_malloc / USBD_free`

**根因**：`usbd_cdc.c` 用 `USBD_malloc` 分配 CDC 句柄，但没有声明（会隐式函数 → 链接 L6218E）。
**修法**：在 `usbd_conf.h` 加
```c
#include <stdlib.h>
#define USBD_malloc malloc
#define USBD_free   free
```

## 7. 运行期 malloc 返回 NULL / CDC 初始化失败

**根因**：startup 的 `Heap_Size` 是 0（模板默认"不用 malloc"）。
**修法**：`startup_stm32f407xx.s` 里 `Heap_Size EQU 0x00000400`（≥1KB 足够）。

## 8. 其它实践
- 不要定义 `HAL_UART_MspInit`（工程 `usart.c` 已有强符号，重复会 L6200E）。
- 工程 uvprojx 的 `IncludePath` 要含：HAL Inc、CMSIS Device/Inc、CMSIS/Include、各中间件 Inc、`User`、`User/Hardware/*`。
- 新增源文件后记得 `Rebuild`（不是 Build），并确认新文件已在 Group 里。

## 9. 用了 FSMC(屏) / SDIO(TF 卡) 后链接报一堆 undefined

`stm32f4xx_hal_conf.h` 里**开了模块宏 ≠ 源文件已进工程**。这几个文件常年躺在
`Drivers/STM32F4xx_HAL_Driver/Src/` 但没被加进 uvprojx：

| 用了什么 | 必须加入工程的 .c |
|---|---|
| USB 设备（OTG_FS） | `stm32f4xx_hal_pcd.c` + `stm32f4xx_hal_pcd_ex.c` + `stm32f4xx_ll_usb.c` |
| FSMC 并口屏 | `stm32f4xx_hal_sram.c` + `stm32f4xx_ll_fsmc.c` |
| SDIO / TF 卡 | `stm32f4xx_hal_sd.c` + `stm32f4xx_ll_sdmmc.c` |

判断方法：把 Rebuild 日志里 "compiling ..." 的列表和你以为的清单对一遍。
**缺失的文件不会报编译错，只在链接阶段变成 `L6218E Undefined symbol XXX`**，
而 XXX 往往是底层名（`USB_*` / `FSMC_NORSRAM_*` / `SDMMC_*`，没有 `HAL_` 前缀），容易误判成"库没装"。

`HAL_xxx_MspInit` 是 **weak**，自己写一份强符号覆盖即可，不会重复定义
（`fromelf -s obj` 看符号是 `Wk` 还是 `Gb` 就能确认）。

## 10. 🔴 `L6050U` / `L6047U`: image 超过 32768 字节

**这不是代码写错，是未授权 Keil MDK-Lite 的 32KB 限制。** F407 本身有 1MB Flash。

```
error: L6050U: The code size of this image (48858 bytes) exceeds the maximum allowed
error: L6047U: The size of this image (38072 bytes) exceeds the maximum allowed
```

### 正解：激活免费的 MDK-Community（无代码大小限制）

`File → License Management → User-Based License → Activate…
→ License Server 填 https://mdk-preview.keil.arm.com → Query → 选 "Keil MDK Community"`

验证是否真的生效（两条硬证据）：
1. `C:/Keil_v5/TOOLS.INI` 里 `TOOL_VARIANT=mdk_std`（不再是 `mdk_lite`）+ `LIC0=<PSN>`
2. 用本机 `armlink` 链接一个 >32KB 的镜像**不再报 L6047U**

### 实在要压进 32KB 的可逆裁剪（均在本板实测过收益）

| 措施 | 收益 | 开关 |
|---|---|---|
| 关 FatFs 长文件名（会拖进 GBK936 转换表 175KB！） | 巨大 | `ffconf.h: FF_USE_LFN 0`，同时把 `ffunicode.c` 移出工程 |
| 只留实际用到的 LCD 控制器寄存器表 | ~3.7 KB | `lcd.h: LCD_KEEP_ALL_IC 0` |
| 只留 16px ASCII 字模（12/24/32px 回落到 16） | ~7.2 KB | 删 `asc2_1206/2412/3216`，`lcd.c` 的 `case` 改指 1608 |
| 干脆关掉 ASCII 字模（屏上只画中文） | ~2.4 KB | `lcd.h: LCD_KEEP_ASCII_FONT 0` |
| 开 microLIB | ~1.2 KB | uvprojx `<useUlib>1` |
| 优化等级 `-Oz` | ~3 KB | uvprojx `<Optim>7` |
| 字库只保留屏上实际用字 | 按字数（32B/字） | `gen_cn_font.py` 的用字表 |
| 整组移出某个模块（代码留在磁盘） | 按模块，如 TF 卡自检 5 文件 ≈7KB | uvprojx 删 Group + `#define XXX_ENABLE 0` |

### ⚠️ 体积必须用"和 Keil 一致"的方式量

踩过的坑：自制脚本没编 `startup.s`、没加 `-std=c99`、链接用 `--no_startup --entry=main`，
结果**比真实值少 6.5KB** → 以为改好了，Rebuild 仍然超限。

正确姿势（`scripts/build_check.py` 就是这么做的）：
- 按 uvprojx 的 `<FilePath>` 清单取源文件（不要手写列表）
- 用工程同一份 `.sct` 散列文件
- `armclang -Oz -ffunction-sections -std=c99`
- startup 用 **`armasm`** 汇编（`--pd "__MICROLIB SETA 1"`），不要拿 armclang 当 C 编
- `armlink --scatter ... --info=sizes` 真实链接，从 "Total ROM Size" 取数

校准基准：同一份代码，脚本报 **37880**、Keil 报 **38072**（偏差 +0.5%），
所以**脚本结果 +200 字节 ≈ Keil 结果**。

### 另一个编译差异
`usart.c` 里的 `FILE __stdout;` 只在 `__STRICT_ANSI__`（即 `-std=c99`）下可见
（`stdio.h` 里 `struct __FILE` 是条件定义），否则报 `storage size of '__stdout' isn't known`。
### ✅ 最靠谱的构建/体积验证：直接用 UV4 命令行跑真工程

自制脚本再怎么对齐也有几百字节偏差，而且**编不到 uvprojx 里没登记的源文件**。
Keil 自带命令行接口，可以不开 IDE 跑真工程、拿真日志：

```
"C:\Keil_v5\UV4\UV4.exe" -r "C:\path\atk_f407.uvprojx" -j0 -o "C:\path\Output\rebuild_all.txt"
```

- `-b` 增量 Build，`-r` 全量 Rebuild
- `-o` 日志文件（**不给就看不到任何编译输出**，容易误判成"秒过"）
- `-j0` 单线程：并行编译 700KB 的 const 数组头文件容易内存暴涨
- 退出码：0 无错无警 / 1 有警告 / 2 有错误 / 3 致命 / 11 打不开工程
- 日志尾部就是权威数据：`Program Size: Code=... RO-data=... RW-data=... ZI-data=...`
  与 `- 0 Error(s), 0 Warning(s).`

封装成 `Tools/keil_rebuild.bat` 最省事（双击跑并保留窗口；`--nopause` 给脚本/CI 用）。
实测：**UV4 命令行结果与 GUI Rebuild 完全一致**，且比自建脚本可信
（同一份代码：自制脚本报 274476，Keil 报 274936）。
