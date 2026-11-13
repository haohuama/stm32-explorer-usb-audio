/* ============================================================
 * usb_device.c —— USB 设备初始化（注册 CDC 类 + 接口，启动栈）
 * ============================================================ */
#include "usb_device.h"
#include "usbd_desc.h"
#include "usbd_cdc.h"
#include "usbd_cdc_if.h"

/* 全局句柄 */
USBD_HandleTypeDef hUsbDeviceFS;

void MX_USB_DEVICE_Init(void)
{
    /* 1. 绑定描述符（VID/PID/字符串见 usbd_desc.c） */
    if (USBD_Init(&hUsbDeviceFS, &FS_Desc, 0) != USBD_OK) return;

    /* 2. 注册 CDC 类 */
    if (USBD_RegisterClass(&hUsbDeviceFS, USBD_CDC_CLASS) != USBD_OK) return;

    /* 3. 注册本工程的应用回调（收 PCM → 环形缓冲） */
    if (USBD_CDC_RegisterInterface(&hUsbDeviceFS, &USBD_CDC_fops_FS) != USBD_OK) return;

    /* 4. 启动 USB 设备栈（开始枚举） */
    if (USBD_Start(&hUsbDeviceFS) != USBD_OK) return;
}
