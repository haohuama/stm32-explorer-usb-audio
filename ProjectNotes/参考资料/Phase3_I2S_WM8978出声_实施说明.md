# Phase 3：I2S2 + WM8978 独立出声 —— 实施说明

> 状态：代码已写入 `C:/stm32TEST`，**未编译、未烧录**（按约定由用户在 Keil 执行）
> 前置已放行：`ADAPT_OK`（2026-11-13 11:04，用户确认）
> 判型依据：I2C 只读探测实测 `[PB8/PB9] W0x34=ACK R0x35=NACK W0x20=NACK R0x21=NACK => WM8978`

---

## 1. 本阶段做什么 / 不做什么

**做**：打通「MCU → I2S → WM8978 → SPK 端子 → 喇叭」这条模拟链路，让喇叭发出
连续稳定的 1kHz 单音。这是整个项目的地基——音频链路不通，后面接 USB 毫无意义。

**不做**：USB（CDC/UAC）、LCD、TF 卡、按键。全部后置。

---

## 2. 硬件事实与依据

### 2.1 控制总线（已实测确认）

| 信号 | 引脚 | 依据 |
|------|------|------|
| I2C SCL | **PB8** | I2C 探测固件实测 ACK |
| I2C SDA | **PB9** | 同上 |
| 器件地址 | **0x1A（7位）/ 0x34（写）** | WM8978 datasheet Rev4.5 p83 |
| 读操作 | **不支持**（NACK） | datasheet p82，故驱动用寄存器镜像 |

### 2.2 音频总线（来源：正点原子《STM32F4 开发指南》I2S 实验章节 —— V2.7 官方例程）

| 信号 | 引脚 | 复用 |
|------|------|------|
| I2S2_WS (LRCK) | **PB12** | AF5 |
| I2S2_CK (BCLK) | **PB13** | AF5 |
| I2S2_SD (DACDAT) | **PC3** | AF5 |
| I2S2_MCK (MCLK) | **PC6** | AF5 |
| DMA | **DMA1_Stream4 / Channel0** | SPI2_TX |

> ⚠️ **唯一未实物验证项**：这组 I2S 引脚。BLOCK-1（真 V2.7 原理图）仍缺，
> 此组来自官方例程而非实物测绘。**若 I2C 通了但完全没声音，第一嫌疑就是这里**
> （见 §6 的 L4）。

### 2.3 时钟树（44.1kHz 精度核算）

```
HSE 8MHz ──/PLLM=8──> 1MHz ──×PLLI2SN=271──> VCO 271MHz ──/PLLI2SR=2──> I2SCLK 135.5MHz
MCLK = I2SCLK / (2×I2SDIV)  ，HAL 自动取 I2SDIV=6
     = 135.5MHz / 12 = 11.2917MHz
目标 MCLK = 256 × 44100 = 11.2896MHz
误差 = +0.019%  → 完全听不出跑调
```

---

## 3. 代码结构与职责

| 文件 | 职责 | 来源 |
|------|------|------|
| `User/Hardware/i2c_soft.c/.h` | 软件 I2C 底层。**本轮新增** `i2c_soft_start / write_byte / stop` 三个原语（原有 `probe_addr` 保留） | 自写 |
| `User/Hardware/WM8978/wm8978.c/.h` | WM8978 控制层：寄存器镜像 + 初始化序列 + 音量 + PlayMode | **MIT**（lovelyterry/SmartSpeaker）+ 正点原子公开序列，改造为 i2c_soft / HAL |
| `User/Hardware/AUDIO/i2s_audio.c/.h` | I2S2 初始化（PLLI2S + GPIO + DMA）+ 正弦波生成 + 循环播放 | 自写 |
| `User/main.c` | Phase 3 测试流程 + 串口打印 | 改写（原探测固件保留可回溯） |

工程侧改动（`Projects/MDK-ARM/atk_f407.uvprojx`）：

- 编译列表新增：`wm8978.c`、`i2s_audio.c`、`stm32f4xx_hal_i2s.c`
- IncludePath 新增：`..\..\User\Hardware\WM8978`、`..\..\User\Hardware\AUDIO`

---

## 4. 关键设计决策（为什么这么写）

### 4.1 DMA 用循环模式，不开中断

```c
DMA_CIRCULAR + FIFOMODE_DISABLE
/* 故意不调 HAL_NVIC_EnableIRQ(DMA1_Stream4_IRQn) */
```

- 缓冲区填一次，硬件无限循环播放，**CPU 零参与** → 这是"流畅"的根本；
- 本工程 `stm32f4xx_it.c` **没有** `DMA1_Stream4_IRQHandler`，若使能 NVIC 会落到
  `Default_Handler` 死循环（`while(1)` 卡死）。循环模式下也不需要中断。

### 4.2 正弦波用整数相位累加器，不依赖 libm

```c
step  = freq × (32×65536) / 44100
idx   = phase >> 16        /* 0..31 表索引 */
frac  = phase & 0xFFFF     /* 线性插值权重 */
v     = sin_tab[idx] + (sin_tab[idx+1] - sin_tab[idx]) * frac >> 16
```

- 零 `math.h` / 零浮点 / 零 libm，任何 Keil 配置（含 MicroLIB）都能编；
- 32 点表 + 线性插值误差 < 0.3%，作测试音绰绰有余；
- 1000Hz 时 `step = 47554`，实际 999.99Hz。

### 4.3 顺序：先起 I2S，再配 WM8978

I2S 一使能，MCLK 立即输出给 WM8978；此时再写寄存器，芯片是在"有主时钟"
的正常状态下完成初始化，比反过来更规范（WM8978 的模拟部分需要 MCLK 才启动）。

### 4.4 首次出声音量压到 0x20

`WM8978_SPKvol_Set(0x20)` = 32/63 ≈ -6dB。第一次测试不要用 0x3F，避免
爆音/吓人/伤喇叭。确认能响再往上加。

### 4.5 三个已规避的工程级坑（沿用上一轮经验）

1. **不定义** `HAL_UART_MspInit` —— 工程 `usart.c:135` 已有强符号，重复定义=L6200E；
2. **不调用** `usart_init()` —— 它开 RX 中断，而 `it.c` 没有 `USART1_IRQHandler` → 跑飞；
3. 时钟用自包含 `SystemClock_Config()` —— 不依赖 `sys.h` 的包含路径。

---

## 5. 预期现象

### 5.1 串口（COM4 / 115200）

```
==== Phase3  I2S2 + WM8978 出声测试 ====
44.1kHz / 16bit / I2S飞利浦 / MCU主模式 / DMA循环
[1] I2S2 init : OK
[2] WM8978_Init: OK (I2C 全部 ACK)
[3] PlayMode  : DAC 开 / 输入关 / 输出开 / SPK vol=0x20
[4] tone start: 1kHz sine, amp -8.7dBFS
---- 预期现象 ----
喇叭 -> 连续稳定的 1kHz 单音（每秒 1000 次的"嗡"）
...
... still playing 1kHz
```

### 5.2 喇叭

连续、稳定、无断续的 1kHz 单音。不是"滴、滴"的间断，不是沙沙噪声，
不是忽大忽小的爆音。

### 5.3 判定

`[1] OK` + `[2] OK` + 喇叭有声 = **音频链路打通，Phase 3 通过**。

---

## 6. 故障排查清单（按顺序查，不要跳）

| # | 现象 | 最可能原因 | 处理 |
|---|------|-----------|------|
| **L1** | `[2] WM8978_Init: FAIL` | I2C 不通：PB8/PB9 上拉缺失、CODEC 未供电、跳线 | 但探测固件在同一组引脚能 ACK → 说明供电与上拉没问题。若此刻 FAIL，多半是 `WM8978_BindBus` 未生效或 `i2c_soft_init` 时序差异 → 把串口输出发我 |
| **L2** | `[1] I2S2 init: FAIL code=1` | PLLI2S 配置失败（已被占用/HSE 未起振） | 检查 `[1]` 前的时钟是否 OK；code=1 是 `HAL_RCCEx_PeriphCLKConfig` 失败 |
| **L3** | `[1] I2S2 init: FAIL code=2` | `HAL_I2S_Init` 失败 | 多半是 MspInit 里 GPIO/DMA 配置参数问题，发我 code |
| **L4** | `[1][2] 都 OK`，但**完全没声音** | **I2S 引脚组不对**（唯一未实测项） | 这是首要嫌疑。核对板上 WM8978 周边走线，或把 PB12/PB13/PC3/PC6 改为实际引脚后重烧 |
| **L5** | 有声音但**极小/几乎听不到** | 音量太低 / 接的是耳机口而非 SPK 端子 | `WM8978_SPKvol_Set(0x3F)` 试最大；确认喇叭接 **SPK 绿色端子**（不是 PHONE 耳机座） |
| **L6** | 声音**断续/卡顿** | DMA 未进循环模式 / 缓冲太小 | 本设计已用 CIRCULAR + 50ms 缓冲，正常不会出现；若出现查是否误开了其他 DMA |
| **L7** | **沙沙噪声**、无音调 | I2S 格式不匹配（飞利浦 vs 左/右对齐）、位宽不匹配 | MCU 侧 `I2S_STANDARD_PHILIPS` / `I2S_DATAFORMAT_16B` 必须与 WM8978 R4 的 `FMT=2, WL=0` 一致（代码已对齐） |
| **L8** | 巨大爆音/啸叫 | 音量过大或 INVROUT2 相位问题 | 立刻断电，把 SPKvol 降到 0x10 再试；查 R43 的 INVROUT2 位 |
| **L9** | 串口**完全无输出** | SSCOM 又开了循环发送 / COM 号不对 / 波特率 | 先确认「循环发送」是灭的（上次踩过这个坑） |

> 出现任一现象，把**串口全部输出**发我，我按上表定位。

---

## 7. 与主线的衔接

Phase 3 通过后：

- **Phase 4（CDC）**：把 `audio_tone_start()` 换成「USB 收到的 PCM 写入环形缓冲，
  DMA 半满/全满时切换缓冲区」。I2S/DMA 骨架**不用改**，只换数据来源。
- **Phase 5（LCD 歌词）**：`lcd_lyrics/` 模块独立，不依赖音频层，随时可并。
- **Phase 2（CubeMX）**：本工程是手写 HAL（用户选择不用 CubeMX），后续若改用
  CubeMX，把上面三处配置搬进 `.ioc` 即可，注意放在 `USER CODE` 区间。

---

## 8. 许可证与来源

| 代码 | 许可证 | 处理 |
|------|--------|------|
| `wm8978.c/.h` 的寄存器序列与接口 | **MIT**（lovelyterry/SmartSpeaker）+ 正点原子公开例程序列 | 可复制改编，已在文件头注明来源 |
| `bangkr` 版驱动 | **无 LICENSE** | ❌ 未使用其代码（只作接口风格对照） |
| `libdriver/wm8978` | MIT | 未直接使用（9547 行过重，本阶段不需要） |

Phase 8 上传 GitHub 前，`wm8978.c` 头部来源声明需保留。

---

## 9. 本轮**没有**做的事（诚实边界）

- ❌ 没有编译（无 Keil/armclang CLI 环境）
- ❌ 没有烧录（按约定由用户操作）
- ❌ 没有修改 `D:\4，程序源码\` 下任何原厂例程
- ❌ 没有验证 I2S 引脚实物走线（BLOCK-1 仍缺）
- ❌ 没有接入 USB / LCD / TF 卡

---

## 10. 用户下一步（3 步）

1. Keil 打开 `C:/stm32TEST/Projects/MDK-ARM/atk_f407.uvprojx` → **Rebuild**
   （预期 0 Error；若报错把输出发我）
2. ST-Link **LOAD** 下载（上次已验证可用，`Flash Load finished`）
3. SSCOM（COM4 / 115200，**确认循环发送是关的**）→ 按 RESET → 看串口 + 听喇叭
