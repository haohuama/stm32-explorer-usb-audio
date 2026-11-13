# Phase 1 · 资源搜索与评估 / 选型结论 / 移植路径

> 依据提示词「资源获取优先级（GitHub 优先策略）」与「GitHub 搜索与评估纪律」。
> 生成时间：2026-11-12　状态：**评估完成，等待用户 `SOURCE_OK`**
> 核心原则：**能移植就不从零写**。USB 协议栈、WM8978 寄存器序列、I2S DMA 时序一律优先复用成熟实现。

---

## 1. 搜索纪律执行记录

提示词要求关键词至少覆盖三组，实际执行（GitHub REST API + 网页检索，2026-11-12）：

| # | 要求关键词组 | 实际检索式 | 结果 |
|---|---|---|---|
| 1 | `STM32F407 WM8978 audio` | `q=wm8978 stm32`、`q=wm8978`、`q=stm32f407 audio i2s` | 22 + 14 个仓库 |
| 2 | `STM32F407 USB CDC I2S PCM` | `q=stm32f407 usb cdc pcm`、`q=stm32 usb audio device`、`q=tinyusb stm32f4 audio` | 1 + 14 + 1 个仓库 |
| 3 | `正点原子 探索者 WM8978 USB 声卡` | 中英文网页检索 + `q=explorer stm32f407 alientek` | 老版例程帖 + 2 个仓库 |
| 补 | ST 官方 USB Device 库 / UAC | `STM32CubeF4` 目录核实、`X-CUBE-USB-AUDIO` 镜像 | 见下表 |

共去重得到 **48 个候选仓库**，逐项按排除规则筛后，进入评估表 12 项。

---

## 2. 候选评估表

> 字段严格按提示词：仓库 | 芯片匹配 | 库类型 | 涉及外设 | 最后提交 | 适配改动预估 | 风险

| 仓库 / 资源 | 芯片匹配 | 库类型 | 涉及外设 | 最后提交 | 适配改动预估 | 风险 |
|---|---|---|---|---|---|---|
| **P1** 正点原子老版 `实验43 音乐播放器实验` | ✅ F407ZGT6 + WM8978，同板 | **StdPeriph（库函数版）** | I2S2、WM8978(IIC)、WAV、KEY、LCD | 2014-12-09 | **低**：抽 `wm8978.c/h`、`i2s.c/h`，IIC/GPIO 改 HAL；播放状态机重写 | 老资料，需确认拿到的是老版而非 V3 版；库类型与 HAL 不同 |
| **P1** 正点原子老版 `实验52 USB声卡(Slave)实验` | ✅ 同板，官方验证 UAC1.0 | **StdPeriph + ST USB Host/Device Lib v2.x** | OTG_FS Device、Audio 类、WM8978、I2S | 2014-12-09 | **中**：UAC 备选路径，USB 栈整体换 CubeMX HAL 版 | UAC 为可选项，不阻塞 CDC 主线；文档明确「稳定的官方路径」 |
| **P2** `STMicroelectronics/STM32CubeF4`（★1366） | ✅ F4 系列 / `STM324xG_EVAL` 同代 | **HAL + LL（官方）** | `USB_Device/AUDIO_Standalone`、`CDC_Standalone`、I2S、DMA | 2026-10-05 | **低**：CDC 例程结构直接参考；AUDIO 例程作 UAC 备选 | 评估板 CODEC 是 CS43L22，需替换底层；固件包版本需与 CubeMX 匹配 |
| **P2** `ada-sound/X-CUBE-USB-AUDIO`（★21） | ✅ 官方 STM32Cube 扩展包 | **HAL / Cube 扩展** | USB Audio Streaming、反馈端点、环形缓冲 | 2019-05-12 | **中**：仅作 UAC 升级时的参考实现 | 7 年未更新；附带 3 份官方 PDF 指南可作设计依据 |
| **P3** `libdriver/wm8978`（★53, MIT） | ✅ 含 `project/stm32f407`（MDK/EW 工程） | **平台无关 C + 模板接口** | WM8978 全功能、IIC/IIS 模板、WAV 播放例程 | 2026-10-21 | **低**：`src/` 直接复制；只需实现 `interface/` 的 IIC/IIS 回调 | 平台层要自己接 HAL；`interface` 是模板不是现成 STM32 驱动 |
| **P3** `lovelyterry/SmartSpeaker`（★313, MIT） | ⚠️ F407**VE**T6 + WM8978 | **StdPeriph + FreeRTOS** | WM8978、SD/FATFS、ESP8266、I2S、DSP | 2026-09-28 | **中高**：只抽 `Audio/` 下 WM8978 驱动，剥离网络/文件系统 | 芯片封装不同；SD 卡 / 以太网 / Wi-Fi 属白名单**禁止**外设，必须剥净 |
| **P3** `mythmyh/stm32lwipsendvoice` | ✅ **F407ZGT6** + WM8978（完全一致） | 待下载核实 | WM8978、I2S、lwIP TCP | 2025-03-11 | **中**：抽 WM8978/I2S 驱动，去掉 lwIP | 以太网属白名单禁止项；0★、无 README 细节，需结构校验 |
| **P3** `wujique/STM32F407_tech_doc`（含 `stm32f407`） | ✅ F407 + WM8978 | **自研底层驱动（非 HAL）** | WM8978、I2S_ext 全双工、WAV | 2019-01 | **只读参考**：寄存器配置章节可交叉验证 | 无 README 构建说明、超 3 年、库强绑定 → 按排除规则降级 |
| **P3** `bangkr/Audio_wm8978_ELink407`（★10） | ⚠️ F407**VG**T6 + WM8978 | **StdPeriph（MDK 5.10）** | WM8978、I2S、WAV | 3 commits，2015 前后 | **只读参考** | 命中「最后提交超 3 年且无人维护」，降级 |
| **P3** `zzwang859/STM32F407_USB_Audio_48Khz_8ch_screen`（Apache-2.0） | ✅ F407（自制核心板） | **`USE_STDPERIPH_DRIVER`（StdPeriph）** | UAC1.0、OTG_FS、双 I2S 全双工、DMA、环形缓冲、反馈速率 | 2026-09-01 | **只读参考**：环形缓冲 + USB 反馈速率算法 | CODEC 是自制底板（非 WM8978）、8ch/48k、StdPeriph 与 HAL 冲突 → 排除主线 |
| **P3** `HB4LO/TINYUSB_STM32F411_CDC_AND_AUDIO`（MIT） | ❌ **F411** | TinyUSB 0.x | CDC + Audio 复合设备 | 2026-03-18 | 结构参考：复合设备描述符组织方式 | 芯片不匹配，需移植 dcd 驱动，代价高 |
| **P3** `dragon99617/ATK-MD0280-PIO`（★2） | ✅ 探索者 F407 | **PlatformIO / 独立库** | 2.8″ TFTLCD 驱动 | 2026-04-17 | Phase 5 备选，非主线 | 构建体系与 MDK 不同，仅借鉴初始化序列 |

**按排除规则执行结果**：
- 芯片非 F407 → `HB4LO`(F411)、`bluedrgn/usb-audio`(F411)、`JhnW/...F411E_Disco`(F411)、`woshinamoda/STM32F466-Audio-WM8978`(F466) 全部降级。
- CODEC 非 WM8978 且驱动层深度耦合 → `schroffl/stm32f407-audio`(CS43L22)、`zzwang859`(自制底板) 排除主线。
- StdPeriph 与当前 HAL 工程冲突且核心逻辑强绑定 → `zzwang859`、`SmartSpeaker`、`bangkr` 降级为「抽取驱动片段」而非整体移植。
- 无 README / 无构建说明 / 超 3 年且无人处理 → `bangkr`、`wujique` 降级为文档参考。

---

## 3. 选型结论（待 `SOURCE_OK` 确认）

### 推荐方案 A：P1 补齐 + P2 官方 HAL + P3 交叉验证

| 子系统 | 选型 | 理由 |
|---|---|---|
| WM8978 寄存器序列 | **P1 老版 `wm8978.c`**（主）+ `libdriver/wm8978`（交叉验证） | 同板同 CODEC，引脚/时钟天然匹配；libdriver 提供完整寄存器定义与 MISRA 风格实现，且持续维护 |
| I2S + DMA 时序 | **P1 老版 `i2s.c`** + CubeMX HAL `HAL_I2S_Transmit_DMA` | 不为时序「发明」新代码；老版例程已验证过 44.1k/16bit 立体声 |
| USB CDC 设备栈 | **CubeMX 直接生成 CDC** + `CDC_Standalone/usbd_cdc_if.c` 骨架 | 官方 HAL，同系列，零移植成本 |
| UAC 标准声卡（可选） | **P1 老版 `实验52 USB声卡(Slave)`** 或 `X-CUBE-USB-AUDIO` | 官方已验证 UAC1.0；CDC 主线稳定后再评估，不阻塞 |
| LCD / 按键 | **P1 老版 `lcd.c` / `key.c`** | 与板载硬件直接匹配 |
| 调试打印 | **USART1（PA9/PA10）→ CH340** | 提示词硬性纪律：CDC 只承载 PCM |

### 备选方案 B：不放行 FETCH 时

`libdriver/wm8978`（`src/` + `interface/` 模板）+ `STM32CubeF4` HAL（`CDC_Standalone`）组合。
代价：WM8978 的 IIC 控制接口、I2S 引脚、时钟树**全部需要老版原理图确认**，而当前资料包是 V3 → **B 方案在 A8（补充老版原理图）完成前无法落地**。

### 「为什么不用现成的」——自研范围声明（硬性规则 11）

> 结论：**USB 协议栈、WM8978 寄存器初始化序列、I2S DMA 时序三块全部移植，不自研。** 仅保留两处最小自研子集，理由如下：

| 拟自研部分 | 为什么不用现成的 | 范围上限 |
|---|---|---|
| PCM 环形缓冲（CDC 生产者 ↔ I2S DMA 消费者） | 唯一找到的现成实现在 `zzwang859`，但它绑定 StdPeriph + UAC + 8ch/48k + 自制 CODEC，剥离与重验证成本高于写约 100 行无锁 SPSC 环形缓冲；CubeF4 CDC 例程只有回显，无音频缓冲 | 单文件 `audio_ringbuf.c/h`：读写指针、水位、欠载/溢出计数、`volatile` 与临界区说明，不含协议栈 |
| CDC 上的 PCM 流控与状态机 | 现成 CDC 例程不处理 44.1kHz 恒定速率、欠载补静音、播放/暂停/音量事件；这部分与本项目业务强绑定 | `audio_ctrl.c`：把 CDC 接收回调、环形缓冲、I2S DMA 半/全传输回调、按键事件接起来 |

除此之外若出现第三处自研，必须先回到本表补充「为什么不用现成的」理由并重新等 `SOURCE_OK`。

---

## 4. 移植路径（不是「直接拿来用」）

### 4.1 可直接复制

- `libdriver/wm8978/src/`：`driver_wm8978.c/.h`、寄存器定义；`example/driver_wm8978_basic.c/.h`（97 KB，含播放 / 录音完整例程）。
- `STM32CubeF4/.../CDC_Standalone/`：`usbd_cdc_if.c` 的接收回调骨架、`usbd_desc.c`、`usbd_conf.c` 结构。
- P1 老版 `lcd.c` / `key.c` 的初始化时序（GPIO 部分需按 HAL 改写）。

### 4.2 需要替换的接口

| 接口 | 来源 | 替换为 |
|---|---|---|
| `wm8978_interface_iic_init/read/write/...` | `interface/driver_wm8978_interface_template.c` | 老版 WM8978 控制总线的 HAL 实现。**I2C 地址与引脚一律待老版原理图/例程核对，本阶段不指定** |
| `wm8978_interface_iis_init/write/set_freq/...` | 同上 | `HAL_I2S_Init` / `HAL_I2S_Transmit_DMA` / I2S 时钟分频配置 |
| `wm8978_interface_debug_print` | 同上 | **重定向到 CH340 USART1**，禁止接到 CDC |
| `wm8978_interface_delay_ms` | 同上 | `HAL_Delay` |
| LCD / KEY 的 `GPIOx->` 寄存器写法 | P1 老版例程 | `HAL_GPIO_ReadPin` / `HAL_GPIO_WritePin` |

### 4.3 需要按当前工程状态机重写

1. `CDC_Receive_FS()` → 写环形缓冲（不打印、不阻塞、不做浮点运算）。
2. I2S TX DMA 的半传输 / 全传输回调 → 从环形缓冲取 16bit 立体声样本填充；欠载补静音并计数。
3. 播放 / 暂停 / 切歌 / 音量加减的事件分发 → 音量走 WM8978 寄存器，歌曲名与状态走 LCD 局部刷新。
4. 所有改动写入 CubeMX `USER CODE BEGIN/END` 区间，输出「原文片段 → 改后片段 + 文件 + 函数 + 插入位置」。

### 4.4 一个必须纠正的文档细节

提示词写「适配点集中在 `stm324xg_usb_audio_codec.c`，把官方默认 CS43L22 换成 WM8978」。核实结果：

- 该文件属于**旧 ST `STM32_USB-Host-Device_Lib` v2.x（StdPeriph）**的 AUDIO 例程；
- 当前 `STM32CubeF4` HAL 版 `Projects/STM324xG_EVAL/Applications/USB_Device/AUDIO_Standalone/Src/` 里**没有**这个文件，实际内容是 `main.c`、`usbd_audio_if.c`、`usbd_conf.c`、`usbd_desc.c`、`stm32f4xx_it.c`、`system_stm32f4xx.c`；
- 因此本项目（CubeMX + HAL）若走 UAC 路线，适配点是 **`usbd_audio_if.c` 的 `AUDIO_Init / AUDIO_DeInit / AUDIO_PlaybackCmd / AUDIO_VolumeCtl / AUDIO_PeriodicTC` 回调**，不是 `stm324xg_usb_audio_codec.c`。

这正是「选型结论必须给出移植路径，而不是直接拿来用」的实际体现。

### 4.5 时钟 / 引脚检查清单（S1 技能降级：逐项确认，不臆造数值）

- [ ] `SYS → Debug = Serial Wire`（否则 PA13/PA14 被释放，ST-LINK 再也连不上）
- [ ] USB OTG_FS Device 时钟 = **48 MHz**（提示词 S1 明确要求）
- [ ] I2S PLL / 主时钟满足 44.1 kHz × 16 bit × 2 声道，并记录实际误差
- [ ] I2S 实例与引脚（**待老版原理图核对**）
- [ ] WM8978 控制总线（**待老版原理图核对**）
- [ ] USART1 → CH340 调试打印，115200 8N1
- [ ] DMA：I2S TX（+ CDC 收发需要的部分）、对应 NVIC 中断优先级
- [ ] 白名单复核：不得出现 SD 卡 / 以太网 / RTC / ADC / DMA2D / 触摸 / USB Host / CAN / 串口屏

---

## 5. 调试打印纪律（贯穿 Phase 3~7）

| 通道 | 用途 |
|---|---|
| CH340 → USART1 (PA9/PA10) | 全部日志：WM8978 寄存器读写结果、I2S 启动状态、环形缓冲水位、CDC 事件计数 |
| USB CDC | **只承载 PCM 数据**，禁止打印 |

原因：CDC 一旦用于打印会和 PCM 争抢带宽与缓冲，导致爆音 / 断流，且污染故障域。

---

## 6. 四件套（本阶段适用形式）

**① 原理说明**
先音频后 USB 是为了切分故障域：Phase 3 让 I2S + WM8978 独立出声，Phase 4 再灌 USB 数据。先评估后编码是为了满足硬性规则 11：在没有确认「为什么不用现成的」之前，不允许动手写 USB 栈 / WM8978 寄存器 / I2S DMA 代码，避免闭门造车。

**② 完整代码**
**本阶段无代码产出，这是遵守规则 11 的结果。** 在 `SOURCE_OK` 之前写驱动代码会直接违反提示词。
`SOURCE_OK` 后按阶段交付，全部附「原文片段 → 改后片段」对照：
- Phase 2：`*.ioc` 配置说明 + `main.c` 的 USER CODE 区段占位
- Phase 3：`wm8978_port.c`（接口实现）、`i2s_audio.c`（正弦波测试）、`audio_sine_tbl.h`
- Phase 4：`audio_ringbuf.c/h`、`usbd_cdc_if.c` 改动、`pcm_sender.py`（PC 端 WAV→PCM 分包工具）
- Phase 5 / 6：`ui.c`、`key_evt.c`

**③ 预期现象（本轮结束后应看到）**
- 工作区新增：`README.md` 与 `docs/` 下 3 份阶段文档；`资料/原理图/` 内有 10 个解压文件。
- 状态为「等待人工确认」；**不会**出现出声、枚举、烧录、上传等任何硬件现象。
- 下一步由用户回传 `SILKSCREEN` / `SOURCE_OK` / `FETCH_OK` 后推进。

**④ 故障排查清单（选型阶段）**

| 现象 | 排查方向 |
|---|---|
| 拿到的例程是 ES8388 | 检查教程是否含「55.1 WAV & ES8388 & I2S」；老版应是 WM8978 + 第48/57章 |
| 例程是 StdPeriph，工程是 HAL | 只抽算法与寄存器序列，外设操作全部换 HAL；不要整包编译 |
| 官方 AUDIO 例程找不到 `stm324xg_usb_audio_codec.c` | 见 4.4：HAL 版适配点是 `usbd_audio_if.c` |
| USB 48 MHz / I2S 时钟报错 | 回 S1 检查清单逐项核；不要照抄 V3 资料包的时钟配置 |
| 引脚无从确认 | 当前资料包是 V3，**不得**据其指定引脚；等待 A8 补充老版原理图 |
| CDC 带来爆音 / 断流 | 先查日志是否误走 CDC；再查环形缓冲水位与欠载计数 |
| 同一失败重复出现 | 按规则 6 立即 `STEP_FAILED` 停止，不循环重试 |

---

## 7. 等待确认（请回复）

```
SOURCE_OK: A（P1 老版例程优先，推荐） | B（libdriver + CubeF4 HAL） | 指定其他
FETCH_OK:  允许下载 F1/F2/F3 | 我手动放到 资料/例程/ | 暂不下载
A8:        老版原理图已补 | 暂无法提供
```

在 `SOURCE_OK` 与 `SILKSCREEN: WM8978` 同时满足前，不进入 Phase 1.5 / Phase 2，不生成任何工程代码。

---

## 8. 用户回传与 Phase 1.5 结构校验后的修正（2026-11-12 13:25 起）

> 本节**覆盖**第 2 节评估表中被实测推翻的字段。`SOURCE_OK` / `FETCH_OK` 已放行，但用户同时要求**暂停代码适配**，因此以下仅为选型结论更新，未做任何移植。

### 8.1 硬件前提更新

- 板子确认为 **Explorer STM32F4 V2.7**（老版），原厂默认 WM8978，丝印待拍。
- **禁止直接套用 V3 的 ES8388 驱动**；已下载资源经全量扫描，ES8388 文件名 / 源码命中均为 0。
- 板上有 USB/CAN 二选一跳线，CDC 音频时**跳线帽置 USB 侧**（人工）；USB-HOST A 口仅 U 盘，不做音频通信。
- **V2.7 整板原理图仍未取得**，因此第 4.5 节时钟 / 引脚检查清单所有条目继续维持「待核对」，不指定、不猜测。

### 8.2 评估表字段修正

| 仓库 | 原填写 | 实测修正 | 结论变化 |
|---|---|---|---|
| `libdriver/wm8978` | 「平台无关 C + 模板接口」 | 核心 `src/` 平台无关，但 `project/stm32f407/` 是**完整 HAL + MDK 工程**（149 个 `stm32f4xx_hal*` 文件、`stm32f407.uvprojx`、`interface/src/iic.c` / `iis.c`、`usr/src/stm32f4xx_hal_msp.c`） | ✅ 与 CubeMX + HAL + Keil 直接对齐，适配成本**低于**原预估，维持方案 A 首选 |
| `mythmyh/stm32lwipsendvoice` | 「待下载核实」/「中：抽 WM8978/I2S 驱动」 | **CubeMX + HAL 完整工程**：2 个 `.ioc`、`Core/Src/i2s.c`、`audio_player.c`、`stm32f4xx_hal_msp.c`、241 个 HAL 文件；芯片 F407ZGT6 + WM8978 完全一致 | ✅ **升级为 I2S / WM8978 HAL 时序首选参考**（替换第 3 节中「老版 `i2s.c` 为唯一时序依据」的表述，形成 HAL 双来源交叉验证）；音频源 lwIP 属白名单禁止项，只抽 I2S/WM8978 层，网络层不引入 |
| `wujique/stm32f407` | 「只读参考」 | 实测含旧 ST `STM32_USB_Device_Library/Class/audio/src/usbd_audio_core.c` + `usbd_audio_out_if.c`，同仓有 `dev_wm8978.c` / `mcu_i2s.c` | ✅ UAC 备选路径（Phase 4 之后）有了现成组合可对照；仍不整体移植 |
| 老版 P1 例程 | 「StdPeriph，需改 HAL」 | 老版资料盘 A 盘**本身含 HAL 库版本**标准例程与《STM32F4开发指南-HAL库版本V1.2》 | ✅ 若从 A 盘取 HAL 版本，StdPeriph→HAL 的转换成本可基本消除；F1 获取时**优先选 HAL 版本** |

### 8.3 自研范围不变

第 3 节「为什么不用现成的」结论继续有效：USB 协议栈、WM8978 寄存器序列、I2S DMA 时序**全部移植**，自研仍只保留 PCM 环形缓冲与 CDC 流控两处最小子集。新增的 HAL 参考只让移植更省力，不扩大自研范围。

### 8.4 许可证风险（Phase 8 前必须处理）

已下载 5 仓中仅 `libdriver/wm8978`（MIT）与 `lovelyterry/SmartSpeaker`（MIT）有明确授权；`mythmyh`、`bangkr`、`wujique` **无 LICENSE**。在确认授权前，这 3 个仓库只作**只读参考**，不得并入项目源码或随仓库发布。

### 8.5 当前状态

🔴 阻塞在音频芯片丝印照片与 V2.7 整板原理图；🔴 用户指令「代码适配暂停」未解除。Phase 2 及其后所有编码工作不启动。

