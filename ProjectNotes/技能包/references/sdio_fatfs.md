# SDIO + FatFs 读 TF 卡（轮询式，零 DMA 冲突）

目标：从 TF 卡读 44.1k/16bit/立体声 WAV，复用已经跑通的音频输出链
（`audio_stream_push()` → 环形缓冲 → DMA 双缓冲 → I2S → CODEC）。

**核心判断：不要重建音频链，只换数据源。** 下游一行都不用改。

---

## 1. 硬件事实（F407 芯片固定复用，与板版本无关）

| 信号 | 引脚 |
|---|---|
| D0~D3 | PC8 / PC9 / PC10 / PC11 |
| SCK | PC12 |
| CMD | PD2 |

全部 **AF12**。两个独立来源（MIT LibDriver 的 `hal_msp.c`、正点原子例程的 `sdio_sdcard.c`）完全一致，
所以**不需要等某个特定版本的原理图**。

**冲突排查**：FSMC 屏占 PD0/1/4/5/8/9/10/14/15、PE7-15、PF12、PG12、PB15 —— **不含 PD2**，与 SDIO 不冲突。
SDIO DMA 走 `DMA2_Stream3/6`，I2S 走 `DMA1_Stream4`，不同控制器；USB 是 `OTG_FS_IRQ`。

---

## 2. 首选"零风险"配置：轮询读，不启用 SDIO DMA/中断

```c
g_sd_handle.Init.ClockEdge           = SDIO_CLOCK_EDGE_RISING;
g_sd_handle.Init.ClockBypass         = SDIO_CLOCK_BYPASS_DISABLE;
g_sd_handle.Init.ClockPowerSave      = SDIO_CLOCK_POWER_SAVE_DISABLE;
g_sd_handle.Init.BusWide             = SDIO_BUS_WIDE_1B;      /* 先 1bit，稳了再 4bit */
g_sd_handle.Init.HardwareFlowControl = SDIO_HARDWARE_FLOW_CONTROL_DISABLE;
g_sd_handle.Init.ClockDiv            = 4;                     /* 48MHz/(4+2)=8MHz，≈1MB/s 足够 */
```

- **用 `HAL_SD_ReadBlocks()`（轮询）读扇区**，不用 `_DMA` 版本 → 不占任何 DMA、不开 SDIO 中断，
  冲突风险归零。
- 不要照抄老例程里的 `__disable_irq()` 包住整个读操作 —— 那会打断 USB/I2S 中断。
  轮询速度慢一点就够（WAV 只需 176400 B/s），**用降频代替关中断**。
- `HAL_SD_MspInit()` 自己写强符号（HAL 库里那份是 `WEAK`），里面配 GPIO AF12、SDIO 时钟、
  NVIC（轮询模式下可以不使能中断）。

---

## 3. FatFs 集成

**源码选择**：ChaN 原版 R0.14b（`ff.c / ff.h / ffunicode.c` + 自写 `diskio.c/h`）。
不要搬第三方工程里带自定义版权头的 `diskio.c/h`，那部分自己写更干净（单卷、几十行）。

`ffconf.h` 关键项：

| 项 | 值 | 原因 |
|---|---|---|
| `FF_FS_READONLY` | 1 | 只读，不引 `disk_write`/`get_fattime` |
| `FF_USE_LFN` | **0**（Keil-Lite 时）/ 1（已授权） | **LFN 会把 GBK936 双字节转换表（175KB）拖进链接** |
| `FF_CODE_PAGE` | 936 | 中文文件名（与 LCD 点阵编码一致） |
| `FF_FS_NORTC` | 1 | 不引 RTC |
| `FF_USE_MKFS` / `FF_USE_FASTSEEK` | 0/1 | 按需 |

> `FF_USE_LFN=1` 配 `ffunicode.c` 才有 GBK 支持；`=0` 时**必须把 `ffunicode.c` 移出工程**，
> 否则它仍然被编进去（虽然部分被链接器丢弃，但体积账会很难看）。

`diskio.c` 要点：单卷（`pdrv==0` 对应 SD 卡），`disk_initialize` 调 `sd_init()`，
`disk_read` 调 `sd_read_blocks()`，`disk_write`/`disk_ioctl(CTRL_SYNC)` 可直接返回 OK。

---

## 4. 数据源抽象（先定契约，别留到后面）

模式 1（USB CDC）和模式 2（TF 卡）只是数据来源不同，必须先把接口定下来，
否则后加的模式会到处改：

```c
typedef struct {
    const char *name;
    uint8_t (*is_available)(void);
    uint8_t (*start)(const char *path);   /* NULL = 从列表头开始 */
    void    (*stop)(void);
    void    (*feed)(void);                /* 主循环里按环形低水位补数据 */
} src_ops_t;
```

- `feed()` **只能在主循环调用**：`f_read` 是毫秒级阻塞操作，**绝不能放进 DMA 中断**
- 低水位判断直接用现有的 `audio_stream_available()`
- 播放位置仍由"真实 PCM 字节数 / 176400"推算，切源时清零

---

## 5. WAV 头必须校验

I2S 时钟被 `PLLI2SN=271 / PLLI2SR=2` 绑死在 **44.1kHz**，所以：

- `nChannels == 2`、`bitsPerSample == 16`、`sampleRate == 44100`、`blockAlign == 4`
- `data_size != 0` 且能被 `blockAlign` 整除
- 先按 `RIFF`/`WAVE` 走块（`fmt ` / `data`），不要硬编码 44 字节偏移（很多文件带 `LIST` 块）

不校验的后果：放 48k 或单声道文件 → 变调 + 噪声，很难判断是编解码问题还是文件问题。

---

## 6. 分段验收（每步都能单独定位）

1. **只做** `f_mount` → `f_opendir` 列目录 → 读一个 WAV 头，把参数用调试串口打出来。
   **完全不碰 I2S/USB。** 这样 SDIO 引脚/卡初始化/FatFs 任何一个出问题都能单独看出来。
2. 再把 `f_read` 结果接 `audio_stream_push()`。
3. 最后才做按键/列表/歌词。

**每步回归验收：切回 USB 模式，`host_cdc_sender.py` 仍能正常放歌。**
（自检入口放在 I2S/USB 启动**之前**，失败只打印不阻断，避免把冻结基线改坏。）
