# Phase 1.5 · 资源获取与结构校验

> 触发：用户 2026-11-12 13:25 回传 `SOURCE_OK`（允许下载 GitHub 匹配开源工程优先复用）与 `FETCH_OK`（允许下载）。
> 同时收到指令：**暂停代码适配，待拍到音频芯片丝印确认型号后再继续 Phase 0**。
> 完成时间：2026-11-12　状态：**获取与结构校验已完成；代码适配未启动**

---

## 0. 本轮遵守的边界

- 只做「下载 → 只读结构校验 → 按文件名摘录」，**未修改任何第三方文件的一个字节**。
- 未创建 / 修改任何工程源码（`.c/.h/.ioc`）、未编译、未烧录、未生成 CubeMX 工程、未做移植适配。
- 未触碰硬件、未改跳线、未看丝印、未听音；不声称任何硬件现象。
- 用户要求「禁止直接套用 V3 的 ES8388 驱动」→ 已对所有下载包做 ES8388 扫描，见第 4 节。

---

## 1. 获取清单

原始仓库快照（GitHub tarball）存于 `资料/开源参考/*.tar.gz`，均为只读归档、**不纳入 Git**：

| 仓库 | 归档大小 | 解压后 | 文件数 | 许可证 | 最后提交 | 与本项目匹配度 |
|---|---:|---:|---:|---|---|---|
| `libdriver/wm8978` | 67.5 MB | 94.0 MB | 573 | **MIT** | 2026-10-21 | ✅ 含 `project/stm32f407` MDK 工程 |
| `mythmyh/stm32lwipsendvoice` | 91.9 MB | 306.3 MB | 1512 | ⚠️ 无 | 2025-03-11 | ✅ **F407ZGT6 + WM8978 + HAL + 2 个 .ioc** |
| `lovelyterry/SmartSpeaker` | 8.9 MB | 24.6 MB | 249 | **MIT** | 2026-09-28 | ⚠️ F407VET6 + WM8978，StdPeriph |
| `bangkr/Audio_wm8978_ELink407` | 45.2 MB | 70.4 MB | 360 | ⚠️ 无 | 2016-04-10 | ⚠️ F407VGT6 + WM8978，StdPeriph |
| `wujique/stm32f407` | 5.3 MB | 22.7 MB | 1092 | ⚠️ 无 | 2019-04-12 | ⚠️ 自研底层，但含旧 ST USB Audio 库 |

> 体积大的原因：`libdriver` 含 64.7 MB 的示例 WAV（`we are the world.wav`）与 Polyspace 报告；`mythmyh` 含大量 `.o/.d/.su` 编译产物；`bangkr` 含 29.9 MB 的 StdPeriph CHM 手册。核心源码其实很小。
> **许可证风险**：3 个仓库无明确 LICENSE。按 Phase 8 上传 GitHub 前必须确认授权；在此之前这些包只作**只读参考**，不得并入项目源码。

---

## 2. 结构校验结果（相对 Phase 1 评估的三处修正）

| # | Phase 1 原判断 | 下载后实测 | 结论变化 |
|---|---|---|---|
| 1 | `libdriver/wm8978` =「平台无关 C + 模板接口」 | 核心 `src/` 确实平台无关，但 `project/stm32f407/` 是**完整 HAL 工程**：149 个 `stm32f4xx_hal*` 文件、`stm32f407.uvprojx`、`interface/src/iic.c`（软件 IIC）、`interface/src/iis.c`、`usr/src/stm32f4xx_hal_msp.c` | ✅ **升级**：与本项目 CubeMX + HAL + Keil MDK 工具链直接对齐，移植成本比预估更低 |
| 2 | `mythmyh/stm32lwipsendvoice` 因 lwIP 降级为「抽驱动片段」 | 实测是 **CubeMX 生成的 HAL 工程**，含 `stm32I2SLWIP.ioc` / `LWIPReceiveVoice.ioc`、`Core/Src/i2s.c`、`audio_player.c`、`stm32f4xx_hal_msp.c`，241 个 HAL 文件 | ✅ **升级为 I2S/WM8978 HAL 时序首选参考**；但音频数据源是 lwIP TCP（白名单禁止以太网），只抽 I2S/WM8978 层，网络层不引入 |
| 3 | 旧 ST USB Audio 库只存在于文档描述 | `wujique/stm32f407` 里找到 `StLib/STM32_USB_Device_Library/Class/audio/src/usbd_audio_core.c` + `usbd_audio_out_if.c`，同仓还有 `board_dev/dev_wm8978.c`、`mcu_dev/mcu_i2s.c` | ✅ UAC 备选路径（Phase 4 之后）有了可对照的现成组合 |

其余结论不变：`SmartSpeaker`（StdPeriph + FreeRTOS + SD/网络）、`bangkr`（StdPeriph + 老资料）仅作 WM8978 寄存器序列的交叉验证，不整体移植。

---

## 3. 摘录结果

从 5 个快照中按文件名规则提取 **85 个文件 / 约 11 MB** 到 `资料/开源参考/摘录/<仓库名>/`，保持原目录相对路径、内容零改动：

| 仓库 | 摘录数 | 关键内容 |
|---|---:|---|
| `libdriver_wm8978` | 48 | `README_zh-Hans.md`、`LICENSE`、`datasheet/wm8978_datasheet.pdf`（118 页）、`example/driver_wm8978_basic.c/.h`、`interface/` 模板、`project/stm32f407/` 的 MDK 工程 + HAL 接口实现（`iic.c`/`iis.c`/`uart.c`）、`stm32f4xx_hal_conf.h` |
| `mythmyh_stm32lwipsendvoice` | 13 | **2 个 `.ioc`**、`Core/Src/i2s.c`、`audio_player.c`、`main.c`、`stm32f4xx_hal_msp.c`、`原理图.pdf` |
| `lovelyterry_SmartSpeaker` | 7 | `Audio/wm8978.c/.h`、`Peripherals/spi_i2s.c/.h`、`LICENSE` |
| `wujique_stm32f407` | 8 | `board_dev/dev_wm8978.c/.h`、`mcu_dev/mcu_i2s.c/.h`、旧 ST USB Audio 类 4 个文件 |
| `bangkr_Audio_wm8978_ELink407` | 9 | `datasheet/WM8978G.pdf`、`WM8978中文资料.doc`、`Docs/wm8978.docx`、`SCH/Audio_WM8978.pdf`、`bsp/wm8978.c/.h`、`bsp/i2s.c/.h` |

### ⚠️ 一张必须排除的「原理图」

`mythmyh/摘录/原理图.pdf`（3 页）经文本核对，标题栏为 `E:\启明PCB资料\..\407高配版1~3.SCHDOC`、`Date: 2020/11/6`，是**启明 407 高配版**开发板，**不是正点原子探索者 V2.7**。
它含 WM8978 / I2S / USB / CAN，但**不得**作为本项目引脚依据。`bangkr/SCH/Audio_WM8978.pdf` 只是音频模块原理图，同样不是整板 V2.7。

---

## 4. 合规性扫描（禁止套用 V3 ES8388 驱动）

对 5 个 tarball 全量扫描：文件名 `ES8388` 命中、以及所有 <300 KB 的 `.c/.h/.md/.txt` 源码内容 `ES8388` 命中：

| 包 | 文件名命中 | 源码内容命中 |
|---|---:|---:|
| `libdriver_wm8978` | 0 | 0 |
| `mythmyh_stm32lwipsendvoice` | 0 | 0 |
| `lovelyterry_SmartSpeaker` | 0 | 0 |
| `bangkr_Audio_wm8978_ELink407` | 0 | 0 |
| `wujique_stm32f407` | 0 | 0 |

✅ 本轮获取的资源**全部是 WM8978 / 通用 USB-Audio 方向，未引入任何 ES8388 驱动**。
现有 `资料/原理图/`（V3 包）仍保留为版本比对证据，不参与移植。

---

## 5. V2.7 原理图获取进展

| 渠道 | 结果 |
|---|---|
| 正点原子官方**旧产品资料页** | ✅ 已定位：`https://www.openedv.com/docs/old-products/Old%20information/zdyz_stm32f407_explorer.html`，标题「STM32F407探索者开发板V2（停产）」——与 V2.7 老版对应 |
| **资料盘 A 盘** | ✅ 已定位：`https://pan.baidu.com/s/18FAortpn_sdvZocav-JFpQ` 提取码 `hhot`；A 盘目录含 `3ALIENTEK探索者STM32F4开发板原理图` |
| 老版例程 / 手册 | ✅ 已定位：A 盘含 `4程序源码` 与 `STM32F4开发指南-HAL库版本V1.2.pdf`（**老版资料盘本身就有 HAL 库版本**，可显著降低 StdPeriph→HAL 适配成本） |
| openedv 老版例程帖 | ✅ 实验43 音乐播放器（1.2 MB）、实验52 USB声卡(Slave)（835 KB）、第 48/57 章 PDF 均已定位 |
| GitCode 原理图镜像仓库 | ⚠️ 找到 3 个资源页，但文件需登录 / 无免登录直链，**未下载** |
| **V2.7 整板原理图 PDF** | 🔴 **仍未取得**。百度网盘需人工客户端下载，属于 Phase 0 人工项 A8 |

> 目前工作区内**没有任何一份**可以作为 V2.7 引脚依据的整板原理图。所有引脚号、I2C 地址、I2S 实例、跳线编号仍标记为「待核对」，不指定、不猜测。

---

## 6. 四件套（资源准备阶段适用形式）

**① 原理说明**
Phase 1.5 的目的是在动代码之前把「可移植的现成实现」真正拿到本地并验证其结构，避免按 README 想象着移植。结构校验直接改变了选型：发现 `libdriver/wm8978` 与 `mythmyh` 都是 HAL 工程，比 Phase 1 预估的适配成本更低；也发现一份被误认为探索者的「启明 407 高配版」原理图并予以排除。

**② 完整代码**
**本阶段零代码产出**，且**用户明确要求暂停代码适配**。第三方源码仅作只读摘录，未改动。
解除 `BLOCK-2`（丝印）与 `BLOCK-6`（暂停指令）后，才按 Phase 2→4 交付工程代码，并附「原文片段 → 改后片段」对照。

**③ 预期现象（本轮结束后应看到）**
- `资料/开源参考/` 下 5 个 `.tar.gz` + `摘录/` 85 个文件 + `README.md`。
- `docs/Phase1.5_资源获取与结构校验.md` 与更新后的 `README.md`。
- 项目状态为「资源就绪，代码适配暂停」；**不会**出现出声、枚举、烧录、上传等硬件现象。

**④ 故障排查清单**

| 现象 | 排查方向 |
|---|---|
| 某个 `.tar.gz` 打不开 / truncated | 首次 `libdriver` 下载被截断（397 KB），已用 `codeload.github.com` 直链重下为 67.5 MB；校验时用 `tarfile.getmembers()` 完整性确认 |
| 包体积异常大 | 是示例 WAV、CHM 手册、`.o/.d` 编译产物，不是核心源码；摘录目录已剔除 |
| 想直接用 `mythmyh` 工程 | 不行：其音频源是 lwIP TCP（白名单禁止以太网），且芯片外设配置需按 V2.7 原理图重核 |
| 把 `原理图.pdf` 当成 V2.7 | 已鉴定为「启明 407 高配版」，禁止使用；见第 3 节 |
| 想并入无许可证仓库的代码 | 3 个仓库无 LICENSE，Phase 8 上传前必须确认授权，否则只作只读参考 |
| 引脚 / 跳线编号无从确认 | 等 V2.7 整板原理图（A8）；跳线只需按实物「置 USB 侧」，不自行编号 |
| ES8388 混入 | 已全量扫描为 0；若后续新增资源，每包都要重跑该扫描 |

---

## 7. 仍待人工（未解除）

1. 🔴 **音频芯片丝印照片** → 解除 BLOCK-2 / BLOCK-6 的唯一条件。
2. 🔴 **V2.7 整板原理图**（A 盘 `3ALIENTEK探索者STM32F4开发板原理图`）→ 解除所有引脚「待核对」状态。
3. ⏸ 老版实验43 / 实验52 例程（如 A 盘可用，请一并放到 `资料/例程/`）。
4. ⏸ 跳线帽置于 USB 侧（人工，Phase 4 接线前）。
5. ⏸ CubeMX / Keil MDK 版本确认（Phase 2 前）。

在此之前：不写工程代码、不生成 `.ioc`、不改跳线、不烧录。
