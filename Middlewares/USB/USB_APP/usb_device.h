/* ============================================================
 * usb_device.h —— USB 设备实例 + 初始化
 * ============================================================ */
#ifndef __USB_DEVICE_H
#define __USB_DEVICE_H

#include "usbd_core.h"

/* 全局 USB 设备句柄（usbd_conf.c 的 PCD 回调转发给它） */
extern USBD_HandleTypeDef hUsbDeviceFS;

/* 初始化并启动 USB 设备（CDC 类，全速） */
void MX_USB_DEVICE_Init(void);

#endif /* __USB_DEVICE_H */
