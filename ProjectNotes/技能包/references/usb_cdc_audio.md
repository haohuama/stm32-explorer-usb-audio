# USB CDC 集成 + 流式音频播放

## 一、把 ST USB Device Library（CDC）接进 Keil 工程

需要的文件（ST 官方，SLA0044 许可）：
- Core：`usbd_core.c/.h`、`usbd_ctlreq.c/.h`、`usbd_ioreq.c/.h`、`usbd_def.h`
- Class/CDC：`usbd_cdc.c/.h`
- 自己的 USB_APP 层：`usbd_conf.c/.h`、`usbd_desc.c/.h`、`usbd_cdc_if.c/.h`、`usb_device.c/.h`
- HAL/LL 依赖：`stm32f4xx_hal_pcd.c`、`stm32f4xx_hal_pcd_ex.c`、`stm32f4xx_ll_usb.c`

初始化：`MX_USB_DEVICE_Init()` = `USBD_Init(&hUsbDeviceFS,&FS_Desc,0)` → `USBD_RegisterClass(USBD_CDC_CLASS)` → `USBD_CDC_RegisterInterface(&USBD_CDC_fops_FS)` → `USBD_Start()`。

CDC 应用回调里最容易漏的：
- **`CDC_Init_FS` 必须给 `hcdc->RxBuffer = UserRxBufferFS; hcdc->TxBuffer = UserTxBufferFS;`** —— ST 库里 RxBuffer 是野指针，不赋值 → USB 收到数据写随机地址 → HardFault。
- 初始化器用的 5 个 `CDC_*_FS` 函数要在 `USBD_CDC_fops_FS` 之前**前向声明**（static）。
- `CDC_Receive_FS(Buf,Len)`：先处理数据（如 `audio_stream_push`），再 `USBD_CDC_ReceivePacket(&hUsbDeviceFS)` 重新武装 OUT。

## 二、Windows 枚举失败：Code 10 / Code 28 / 复合设备

**症状**（设备管理器）：
```
USB Composite Device (VID_xxxx&PID_xxxx)
 ├─ MI_00   "USB 串行设备 (COMx)"   ERR=10 无法启动
 └─ MI_01   "..."                   ERR=28 无驱动
```
**根因**：设备描述符 `bDeviceClass = 0x00`。CDC 有 2 个接口（通信+数据），`0x00` 且无 IAD → Windows 当"复合设备"拆开各自找驱动 → usbser 起不来。

**修法**（`usbd_desc.c` 的设备描述符）：
```c
0x02,   /* bDeviceClass: CDC 类   ← 关键，必须是 0x02，不能 0x00 */
0x00,   /* bDeviceSubClass */
0x00,   /* bDeviceProtocol */
```
通信接口描述符保持标准 ACM：`bInterfaceClass=0x02, bInterfaceSubClass=0x02(ACM), bInterfaceProtocol=0x01`。
改完 Windows 用**内置 usbser** 自动认成标准 `USB 串行设备 (COMx)`，**无需装驱动、即插即用**。
（若改了还不认，先在设备管理器里"卸载设备(勾删除驱动)"再拔插，避免按 VID/PID 缓存旧配置。）

## 三、电脑 → MCU 流式 PCM 播放（设备端）

架构：`USB OUT 中断写环形缓冲` → `DMA 半/全传输中断 refill 双缓冲` → `I2S → CODEC`。
- **环形缓冲**（字节）：生产者=USB 接收（`audio_stream_push`），消费者=DMA HT/TC 中断。32KB 抗抖动。
- **双缓冲**：`HAL_I2S_Transmit_DMA` 以整块循环；HT 中断 refill 前半、TC 中断 refill 后半。
- **单位极重要**：`HAL_I2S_Transmit_DMA(hi2s, pData, Size)` 的 `Size` 是**半字数（16bit样本数）**。双缓冲要声明成 `uint16_t buf[HALF_SAMPLES*2]`（= 2×半区样本数的字节），`Size = HALF_SAMPLES*2`。若误声明成 `uint8_t[2*HALF]` 却按 `2*HALF` 样本传 → 越界读相邻内存 → **刺耳噪声**。

`audio_stream_push` 关键点：
- **按 4 字节（一个立体声帧）对齐写入/溢出丢弃**，否则丢单字节会破坏 16bit/L-R 对齐 → 位错爆音。
- 溢出时丢最旧一帧（`r += 4`），保持 `w != r`。

`stream_fill_half` 关键点：
- 欠载时"有多少填多少 + 剩余补 0"（不要"不足就整半静音"，那是 23ms 整段静音跳变）。

## 四、电脑 → MCU 流式 PCM 播放（上位机）

用 `scripts/host_cdc_sender.py`：按 44.1k 实时匀速把 WAV（16bit/44.1k/立体声）发给虚拟串口。
- **绝对时间调度**（`next_t += len/rate`）消除 `time.sleep` 累积误差，否则发送偏慢 → 缓冲抽干 → 间断。
- **`write_timeout=None`**（阻塞写），避免 USB 偶发卡顿的写超时让整个脚本退出；整块写出保持帧对齐。
- `--rate` 微调发送速率（偶发断音调大、偶发爆音调小）。
- `--gain` 可选数字增益（源已满量程时放大会削波，不推荐大倍数）。

> CDC 是批量传输、无实时流控，长放可能有极偶发 glitch；要彻底无瑕需走 **UAC（等时传输）**。
