/**
  ******************************************************************************
  * @file    usbd_cdc_if.c
  * @brief   CDC 应用层（基于 ST usbd_cdc_if_template.c，SLA0044 许可）
  *          定制：OUT 端点收到主机 PCM 字节 → 灌入音频环形缓冲；
  *                IN 端点不用（音频只下行）。本工程是「虚拟串口传 PCM」。
  ******************************************************************************
  * @attention
  * <h2><center>&copy; Copyright (c) 2015 STMicroelectronics.
  * All rights reserved.</center></h2>
  * This software component is licensed by ST under Ultimate Liberty license
  * SLA0044, the "License"; You may not use this file except in compliance with
  * the License. You may obtain a copy of the License at: www.st.com/SLA0044
  ******************************************************************************
  */

#include "usbd_cdc_if.h"
#include "usb_device.h"   /* hUsbDeviceFS */
#include "i2s_audio.h"    /* audio_stream_push() */
#include "lcd_ui.h"       /* lcd_ui_select_song()：用 DTR/RTS 选曲 */

/* 前向声明：USBD_CDC_fops_FS 初始化器在下方引用，必须在之前可见 */
static int8_t CDC_Init_FS(void);
static int8_t CDC_DeInit_FS(void);
static int8_t CDC_Control_FS(uint8_t cmd, uint8_t *pbuf, uint16_t length);
static int8_t CDC_Receive_FS(uint8_t *Buf, uint32_t *Len);
static int8_t CDC_TransmitCplt_FS(uint8_t *Buf, uint32_t *Len, uint8_t epnum);

/* CDC 类回调集合 */
USBD_CDC_ItfTypeDef USBD_CDC_fops_FS =
{
  CDC_Init_FS,
  CDC_DeInit_FS,
  CDC_Control_FS,
  CDC_Receive_FS,
  CDC_TransmitCplt_FS
};

/* OUT/IN 端点缓冲（IN 在本工程未使用，预留） */
static uint8_t UserRxBufferFS[64];
static uint8_t UserTxBufferFS[64];

USBD_CDC_LineCodingTypeDef linecoding =
{
  115200, /* baud rate（虚拟串口参数，PCM 传输忽略） */
  0x00,   /* stop bits */
  0x00,   /* parity */
  0x08    /* data bits */
};

/* ---- CDC 初始化：必须把 RxBuffer/TxBuffer 挂上！ ----
 * ST 这份库 USBD_CDC_Init 会用 hcdc->RxBuffer 调 PrepareReceive 武装 OUT 端点，
 * 但库里没有给 RxBuffer 赋值（它是指针，malloc 后是野指针）。
 * 若不在此处赋值，USB 收到数据会把 DMA 写向随机地址 → HardFault。
 * CDC_Init 在 USBD_CDC_Init 里、PrepareReceive 之前被调用，这里赋值刚好。 */
static int8_t CDC_Init_FS(void)
{
  USBD_CDC_HandleTypeDef *hcdc = (USBD_CDC_HandleTypeDef *)hUsbDeviceFS.pClassData;
  if (hcdc != NULL)
  {
    hcdc->RxBuffer = UserRxBufferFS;
    hcdc->TxBuffer = UserTxBufferFS;
  }
  return (0);
}

static int8_t CDC_DeInit_FS(void)
{
  return (0);
}

static int8_t CDC_Control_FS(uint8_t cmd, uint8_t *pbuf, uint16_t length)
{
  UNUSED(length);
  switch (cmd)
  {
    case CDC_SET_LINE_CODING:
      if (pbuf == NULL || length < 7u) break;
      linecoding.bitrate    = (uint32_t)pbuf[0] | ((uint32_t)pbuf[1] << 8) |
                              ((uint32_t)pbuf[2] << 16) | ((uint32_t)pbuf[3] << 24);
      linecoding.format     = pbuf[4];
      linecoding.paritytype = pbuf[5];
      linecoding.datatype   = pbuf[6];
      /* 选曲（主通道，可扩展到任意首数）：上位机把 ser.baudrate 设成 100000+idx，
       * 驱动就会发这条请求。只有落在 [100000,100000+16) 才当选曲，其余忽略。
       * 纯 USB 控制请求，占 0 字节音频带宽。 */
      if (linecoding.bitrate >= 100000u && linecoding.bitrate < (100000u + 16u)) {
        lcd_ui_select_song((uint8_t)(linecoding.bitrate - 100000u));
      }
      break;

    case CDC_SET_CONTROL_LINE_STATE:
      /* 兼容通道：wValue bit0 = DTR，bit1 = RTS，可表达第 1..3 首。
       * usbd_cdc.c 在 wLength==0 时把整个 Setup 包指针当 pbuf 传进来。
       * 3（DTR|RTS 都置位）是端口刚打开时的默认态，必须忽略。 */
      if (pbuf != NULL) {
        uint16_t wv = ((USBD_SetupReqTypedef *)pbuf)->wValue;
        if ((wv & 0x0003u) < 3u) {
          lcd_ui_select_song((uint8_t)(wv & 0x0003u));
        }
      }
      break;

    case CDC_GET_LINE_CODING:
      pbuf[0] = (uint8_t)(linecoding.bitrate);
      pbuf[1] = (uint8_t)(linecoding.bitrate >> 8);
      pbuf[2] = (uint8_t)(linecoding.bitrate >> 16);
      pbuf[3] = (uint8_t)(linecoding.bitrate >> 24);
      pbuf[4] = linecoding.format;
      pbuf[5] = linecoding.paritytype;
      pbuf[6] = linecoding.datatype;
      break;

    default:
      break;
  }
  return (0);
}

/* ---- OUT 端点收到数据：先把 PCM 字节灌进环形缓冲，再重新武装 OUT 端点 ----
 * 注意顺序：先 copy 再 PrepareReceive，否则下一包可能覆盖 UserRxBufferFS。 */
static int8_t CDC_Receive_FS(uint8_t *Buf, uint32_t *Len)
{
  audio_stream_push(Buf, *Len);
  USBD_CDC_ReceivePacket(&hUsbDeviceFS);
  return (0);
}

static int8_t CDC_TransmitCplt_FS(uint8_t *Buf, uint32_t *Len, uint8_t epnum)
{
  UNUSED(Buf);
  UNUSED(Len);
  UNUSED(epnum);
  return (0);
}

/************************ (C) COPYRIGHT STMicroelectronics *****END OF FILE****/
