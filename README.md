# STM32F407 探索者 · USB 电脑音频播放器

把电脑通过 USB 发来的 PCM 音频，经 STM32 的 I2S 送给 WM8978 解码，从喇叭播放。

```
电脑 ──(USB CDC, PCM 16bit/44.1kHz/立体声)──> STM32F407 ──(I2S2)──> WM8978 ──> 喇叭
```

> 音频只走这一条数字链路；绿色端子仅输出模拟音频，CH340 只做下载/调试打印。

## 硬件

| 项 | 说明 |
|---|---|
| 开发板 | 正点原子 探索者 STM32F407ZGT6（老版 V2.7，**不是 V3/ES8388**） |
| CODEC | **WM8978**（I2C：PB8=SCL / PB9=SDA，地址 0x34，只写） |
| I2S2 | PB12=WS / PB13=CK / PC3=SD / PC6=MCK（AF5），DMA1_Stream4 循环模式 |
| USB | USB_OTG_FS（PA11/PA12），全速 12Mbps，CDC 虚拟串口 |
| 跳线 | USB/CAN 跳线帽须置于 **USB 侧** |

## 特性

- USB 设备描述符为标准 **CDC ACM**（`bDeviceClass=0x02`），Windows 即插即用，无需装驱动
- 设备端 **32KB 字节环形缓冲 + 8KB 双缓冲（2×4KB 半区）**，DMA 半传输/全传输中断里 refill
- 环形写入/溢出按 **4 字节立体声帧对齐**，避免字节错位噪声
- 欠载时"有多少填多少 + 补零"，避免整段静音跳变
- 上位机脚本：按实时匀速发送（绝对时间调度，消除 sleep 累积误差），支持数字增益 + 限幅
- 已实测：电脑经 USB_SLAVE 发 WAV → 喇叭出声

## 构建

- 工具链：Keil MDK（ARMCLANG），工程文件 `Projects/MDK-ARM/atk_f407.uvprojx`
- 依赖：STM32F4 HAL（含 `HAL_PCD`、`stm32f4xx_ll_usb`）、ST USB Device Library（Core + CDC class）
- 步骤：用 Keil 打开工程 → **Rebuild** → ST-Link 烧录

## 使用

1. 烧录固件
2. 用**能传数据**的 USB 线把电脑连到板载 **USB_SLAVE** 口（跳线置 USB 侧）
3. 设备管理器「端口」出现 **`USB 串行设备 (COMx)`**（首次可能需拔插一次）
4. 电脑装 pyserial：`pip install pyserial`
5. 发一个 **44.1kHz / 16bit / 立体声** 的 WAV（MP3 需先转 WAV）：
   ```
   python Tools/host_cdc_sender.py -p COMx -f song.wav
   ```
   - `--gain N`：发送前数字增益（默认 10，`1.0` 表示不处理）
   - `--rate R`：发送速率倍数（偶发断音调大、偶发爆音调小）
6. 喇叭出声

> 只有一根 USB 线时：插 USB_SLAVE 即可（CH340 调试口可留空，不影响放音）。

## 目录结构

```
User/            应用层：main.c、i2s_audio.c/.h、wm8978.c/.h、i2c_soft、codec_detect
Middlewares/USB/ ST USB 设备库(Core+CDC) + USB_APP 适配层(usbd_conf/desc/cdc_if/usb_device)
Drivers/         STM32F4 HAL + CMSIS
Projects/MDK-ARM Keil 工程
Tools/           上位机脚本：host_cdc_sender.py（发送）、gen_test_wav.py、loud_master.py
docs/            开发过程与技术文档（硬件核对、I2S/WM8978、CDC 实施等）
REPRODUCE.md     陌生人复现指南
```

## 许可证与第三方

本项目包含 STM32 HAL / CMSIS、ST USB Device Library、WM8978 驱动等第三方组件，
详见 [NOTICE.md](NOTICE.md)。原始第三方手册与版权音乐**不包含**在本仓库内。
