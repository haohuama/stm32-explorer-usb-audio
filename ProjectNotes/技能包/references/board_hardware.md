# 板级硬件事实（探索者 STM32F407 老版 V2.7）

> 引脚以官方例程 + 实测确认为准；V3 资料（ES8388/Type-C/YT8512C）不可套用。

## MCU / 时钟
- STM32F407ZGT6，HSE 8MHz。
- 系统时钟：PLLM=8, PLLN=336, PLLP=2 → 168MHz；APB1=/4(42M)，APB2=/2(84M)。
- I2S 时钟（PLLI2S）：PLLI2SN=271, PLLI2SR=2 → VCO 271MHz → I2SCLK 135.5MHz → MCLK 11.2917MHz（目标 11.2896MHz，误差 +0.019%，可忽略）。

## I2S2（→ WM8978）
| 信号 | 引脚 | 复用 |
|---|---|---|
| WS(LRCK) | PB12 | AF5 |
| CK(BCLK) | PB13 | AF5 |
| SD(DACDAT) | PC3 | AF5 |
| MCK | PC6 | AF5 |

- I2S2 主模式发送、飞利浦标准、16bit、44.1kHz、MCLK 输出。
- DMA：**DMA1_Stream4 / Channel0**（SPI2_TX），**CIRCULAR**，MEMORY_TO_PERIPH，halfword 对齐，FIFO 关闭。
- 常规单音模式可不开 DMA 中断；双缓冲流播放**必须**开 `DMA1_Stream4_IRQn` 并在 `it.c` 里接 `HAL_DMA_IRQHandler`。

## CODEC：WM8978
- I2C：**PB8=SCL / PB9=SDA**（软件 I2C 开漏即可），7 位地址 0x1A → 写地址 **0x34**。
- WM8978 是"只写"器件：写 0x34 会 ACK，读 0x35 无应答（可作判型依据；ES8388 两地址都 ACK）。
- 寄存器写帧：`(reg<<1)|(val>>8)` 然后 `val&0xFF`（9 位值）。
- 初始化顺序建议：`audio_i2s_init()`（先出 MCLK/BCLK/LRCK）→ `WM8978_Init()` → `WM8978_PlayMode()` → `WM8978_SPKvol_Set()`。
- SPK 音量寄存器 6bit：低值衰减、0x3F≈+6dB（满档）。调试时别一上来满档，避免模拟削顶。

## USB
- USB_OTG_FS：PA11=DM / PA12=DP（AF10），全速 12Mbps，内嵌 PHY，无 VBUS 检测脚（vbus_sensing_enable=DISABLE）。
- FIFO 分配示例（总量 ≤ 320 字）：RX=0x60、TX0=0x10、TX1=0x40、TX2=0x10。
- 板载三个 USB 口：**USB_232**(CH340，下载/调试)、**USB_SLAVE**(OTG_FS，音频数据)、**USB-HOST**(USB-A，接U盘)。
- 做 CDC 时：跳线置 **USB 侧**，数据线插 **USB_SLAVE**。只插一根线时插 USB_SLAVE 也能放音（CH340 可留空，仅失去调试打印）。

## 调试串口
- CH340 → USART1（PA9=TX/PA10=RX），115200。调试打印只走这里；**CDC 只承载 PCM，禁止打印**。
