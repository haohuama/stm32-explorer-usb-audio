# Phase 4 · USB CDC 虚拟串口流 PCM —— 实施说明（四件套）

> 阶段目标：电脑把 16bit/44.1kHz/立体声 PCM 当“虚拟串口”字节流发给板子，
> 板子经已验证的 I2S→WM8978 链路播出来。之后可再平滑升级为 UAC 标准声卡（不阻塞主线）。
> 工程目录：`C:/stm32TEST`；MCU = STM32F407ZGT6；CODEC = WM8978（已 I2C 实测确认）。

---

## 1. 原理说明

### 1.1 链路
```
电脑(WAV/声卡) --USB_FS_CDC--> [USB_OTG_FS PA11/PA12]
        --USBD_CDC_Receive_FS--> 字节环形缓冲(8KB)
        --DMA HT/TC 中断--> I2S2 双缓冲(4KB)
        --I2S(PB12/13/PC3/PC6)--> WM8978 --> SPK 绿色端子 --> 喇叭
```

### 1.2 为什么用两块缓冲
- **USB 与 I2S 速率不匹配 + 不定时**：USB 一批 64 字节、何时来不确定；I2S 恒定吃数据。
  中间用「字节环形缓冲」吸收突发，「I2S 双缓冲」保证输出连续。
- **双缓冲（ping-pong）**：I2S 用 DMA **循环模式**播整块（2 个半区）；DMA 播到一半(HT)时第一半已空闲、
  播完(TC)时第二半已空闲，各自 refill —— 永远写“不在播”的那半，输出零间隙。
- **环形缓冲**：USB 接收中断(生产者)只管 `audio_stream_push()` 灌字节；DMA 中断(消费者)只管 `stream_fill_half()` 取字节。
  单生产者/单消费者 + 32 位原子读写 → 不会破坏数据；最坏只是偶发静音/丢包。
  环形写满时**丢弃最旧**以限制延迟（不会越积越多）。

### 1.3 关键源码分工
| 文件 | 作用 |
|---|---|
| `Middlewares/USB/STM32_USB_Device_Library/**` | ST 官方 USB 设备库（Core + CDC class），SLA0044 许可，原样复制 |
| `Middlewares/USB/USB_APP/usbd_conf.c/.h` | HAL-PCD 绑定层：PA11/12、OTG_FS 中断、FIFO、全部 `USBD_LL_*`、PCD 事件转发 |
| `Middlewares/USB/USB_APP/usbd_desc.c/.h` | 设备/字符串描述符（VID 0x0483 / PID 0x5722 / “WM8978 CDC PCM”） |
| `Middlewares/USB/USB_APP/usbd_cdc_if.c/.h` | CDC 应用层：**OUT 收到 PCM → 灌环形缓冲**；`CDC_Init_FS` 给 `hcdc->RxBuffer` 赋值（防 HardFault） |
| `Middlewares/USB/USB_APP/usb_device.c/.h` | `hUsbDeviceFS` + `MX_USB_DEVICE_Init()` 注册 CDC 类 |
| `User/Hardware/AUDIO/i2s_audio.c/.h` | 新增流播放：环形缓冲 + 双缓冲 + `HAL_I2S_TxHalfCplt/TxCplt` 回调；保留原 `audio_tone_start` 单音自测 |
| `User/stm32f4xx_it.c` | 新增 `OTG_FS_IRQHandler`（→`HAL_PCD_IRQHandler`）、`DMA1_Stream4_IRQHandler`（→`HAL_DMA_IRQHandler`） |
| `User/main.c` | 流程改为：I2S 初始化 → WM8978 初始化 → `audio_stream_start()` → `MX_USB_DEVICE_Init()` |

### 1.4 一个必踩的坑（已处理）
ST 这份 `usbd_cdc.c` 的 `USBD_CDC_Init` 会用 `hcdc->RxBuffer` 调 `PrepareReceive` 武装 OUT 端点，
但 `RxBuffer` 是指针、库里**没有赋值**（malloc 后是野指针）。若不处理，USB 一收到数据就把 DMA 写向随机地址 → **HardFault**。
已在 `CDC_Init_FS` 里 `hcdc->RxBuffer = UserRxBufferFS;` 解决（该回调在 `PrepareReceive` 之前被调用）。

---

## 2. 完整代码（关键片段）

### 2.1 USB 收数据 → 环形缓冲（`usbd_cdc_if.c`）
```c
static int8_t CDC_Init_FS(void) {
  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef *)hUsbDeviceFS.pClassData;
  if (hcdc != NULL) { hcdc->RxBuffer = UserRxBufferFS; hcdc->TxBuffer = UserTxBufferFS; }
  return 0;
}
static int8_t CDC_Receive_FS(uint8_t *Buf, uint32_t *Len) {
  audio_stream_push(Buf, *Len);              // 先复制
  USBD_CDC_ReceivePacket(&hUsbDeviceFS);     // 再重新武装 OUT 端点
  return 0;
}
```

### 2.2 双缓冲 refill + 环形缓冲（`i2s_audio.c`）
```c
#define AUDIO_STREAM_HALF_FRAMES 1024u
#define AUDIO_STREAM_HALF_LEN    (AUDIO_STREAM_HALF_FRAMES * 2u)
#define AUDIO_RING_SIZE          8192u
#define AUDIO_RING_MASK          (AUDIO_RING_SIZE - 1u)

static uint8_t s_stream_buf[AUDIO_STREAM_HALF_LEN * 2u];   // 双缓冲
static uint8_t s_ring[AUDIO_RING_SIZE];                    // 字节环形
static volatile uint32_t s_ring_w = 0, s_ring_r = 0;

void HAL_I2S_TxHalfCpltCallback(I2S_HandleTypeDef *hi2s){   // 第一半播完
  if (hi2s->Instance == SPI2) stream_fill_half((uint16_t*)&s_stream_buf[0], AUDIO_STREAM_HALF_LEN);
}
void HAL_I2S_TxCpltCallback(I2S_HandleTypeDef *hi2s){       // 第二半播完
  if (hi2s->Instance == SPI2) stream_fill_half((uint16_t*)&s_stream_buf[AUDIO_STREAM_HALF_LEN], AUDIO_STREAM_HALF_LEN);
}
int audio_stream_push(const uint8_t *data, uint32_t len){   // USB 中断调用
  uint32_t i;
  for (i=0;i<len;i++){ s_ring[s_ring_w]=data[i]; s_ring_w=(s_ring_w+1)&AUDIO_RING_MASK;
    if (s_ring_w==s_ring_r) s_ring_r=(s_ring_r+1)&AUDIO_RING_MASK; } // 满则丢最旧
  return (int)len;
}
void audio_stream_start(void){
  for (uint32_t i=0;i<AUDIO_STREAM_HALF_LEN*2u;i++) s_stream_buf[i]=0;  // 先静音
  s_ring_r = s_ring_w = 0;
  HAL_I2S_Transmit_DMA(&g_i2s2_handle, (uint16_t*)s_stream_buf, (uint16_t)(AUDIO_STREAM_HALF_LEN*2u));
}
```
> `stream_fill_half()` 从环形取 `need` 字节填半区；不足则填静音(0)。
> DMA 中断优先级设为 **1**（低于 USB 的 0），保证 USB 能抢占喂数据。

### 2.3 中断挂载（`stm32f4xx_it.c`）
```c
void OTG_FS_IRQHandler(void){ HAL_PCD_IRQHandler(&hpcd_USB_OTG_FS); }
void DMA1_Stream4_IRQHandler(void){ HAL_DMA_IRQHandler(&g_i2s2_tx_dma); }
```

### 2.4 工程配置（已用脚本改好 `atk_f407.uvprojx`）
- 新增 Group `Middlewares/USB`，加入 8 个 .c：
  `usbd_core / usbd_ctlreq / usbd_ioreq / usbd_cdc / usbd_conf / usbd_desc / usbd_cdc_if / usb_device`。
- 新增 3 条 IncludePath：
  `...\Middlewares\USB\STM32_USB_Device_Library\Core\Inc`、
  `...\Class\Inc`、`...\USB_APP`。

---

## 3. 预期现象

1. **Keil Rebuild**：0 Error。`USBD_LL_*` 的 12 个 stage/event 函数（`SetupStage`/`DataOutStage`/`DataInStage`/`Reset`/`SetSpeed`/`SOF`/`Suspend`/`Resume`/`IsoIN*`/`DevConnected`/`DevDisconnected`）已在 `usbd_core.c` 实现，本工程的 `usbd_conf.c` 只保留绑定层函数（`Init`/`Transmit`/`PrepareReceive` 等），**无重复定义**（初版误放的空 stub 已删除，否则既重复定义又会断流）。
2. **ST-Link LOAD** 烧录；**USB/CAN 跳线帽置 USB 侧**；板子 **USB_SLAVE** 口接电脑。
3. 电脑识别出一个串口（Windows 可能显示“未知 USB 设备”，见排查 §4.3；Linux 直接是 `/dev/ttyACM0`）。
4. 串口助手/SSCOM 看 CH340 调试串口打印：
   `[1] I2S2 init OK` → `[2] WM8978_Init OK` → `[3] PlayMode` → `[4] audio stream` → `[5] USB CDC` → `... ring=0 bytes`(每 3 秒)。
5. 运行电脑端 `python Tools/host_cdc_sender.py <端口> music.wav`，**喇叭播放该 WAV**；
   调试串口 `ring=` 数值随发送起伏（几十~几千字节），说明数据在流动。
6. Ctrl+C 停止发送后约 45ms（环形 8KB 排空），喇叭回到静音。

---

## 4. 故障排查清单

### 4.1 编译 / 链接
- **缺 `USBD_LL_*` 未定义**：确认 8 个 USB .c 已加入工程、3 条 IncludePath 已加（见 §2.4）。
- **`OTG_FS_IRQHandler` / `DMA1_Stream4_IRQHandler` 重定义**：检查 startup 文件是否已有同符号（标准 startup 只有 weak，不会重定义）；若曾手写过同名函数需删掉。
- **`HAL_PCD_IRQHandler` 未定义**：确认 `stm32f4xx_hal_pcd.c` 在工程（Phase 3 已在）。

### 4.2 烧录后无任何打印 / 不枚举
- USB/CAN 跳线**必须置 USB 侧**；线插的是 **USB_SLAVE** 口（不是 USB-HOST A 口）。
- 供电是否正常；CH340 串口能否看到 Phase3 那样的打印（先确认最小系统活着）。
- 若卡在 `[5]` 之前，说明 I2S/WM8978 初始化失败（回到 Phase 3 排查）。

### 4.3 电脑识别为“未知 USB 设备”（Windows）
- CDC-ACM 在 Windows 上常需手动绑定驱动：设备管理器 → 该设备 → 更新驱动 → 浏览 →
  选“USB 串行设备 (usbser)”或 ST 的 VCP 驱动（`STSW-STM32102`）。Linux/macOS 免驱。
- PID 当前为 `0x5722`（自定义）。若想用 ST 现成 VCP 驱动，可改为 `0x5740`（在 `usbd_desc.c` 改 `USBD_PID`）。

### 4.4 枚举成功但**喇叭不出声 / 只有静音**
- 先确认 Phase 3 单音还能出声（把 `main.c` 里 `audio_stream_start()` 换回 `audio_tone_start(1000)`，
  重烧验证 WM8978/I2S 本身正常）。
- 检查 WAV 格式：必须 **44100Hz / 16bit / 立体声**（44.1k×2×2=176.4KB/s，USB FS 带宽足够）。
- 检查端口号是否填对；脚本是否真的在写（看 `ring=` 是否有数值变化）。
- 若 `ring=` 一直很大且不清零 → 设备消费太慢（极少发生）；若一直是 0 → 主机没发出来（端口/驱动问题）。

### 4.5 爆音 / 卡顿
- 多半是环形被冲爆后丢最旧造成的“断续”。脚本已按实时节奏发送；不要在脚本里加 `sleep(0)` 之外的加速。
- 可调大 `AUDIO_RING_SIZE`（如 16384）；或确认电脑 USB 口没被其他设备抢占带宽。

---

## 5. 一键验证步骤（给用户）
```text
1) Keil 打开 C:/stm32TEST/Projects/MDK-ARM/atk_f407.uvprojx
2) Rebuild → 0 Error
3) ST-Link LOAD
4) 跳线置 USB 侧，USB_SLAVE 口接电脑
5) 电脑：python Tools/host_cdc_sender.py COMx music.wav   (COMx 换成实际端口)
6) 听喇叭；看 CH340 串口 ring= 数值
```
