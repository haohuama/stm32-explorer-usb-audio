/* ============================================================
 * usbd_desc.h —— USB 设备描述符头（基于 ST usbd_desc_template.h）
 * ============================================================ */
#ifndef __USBD_DESC_H
#define __USBD_DESC_H

#include "usbd_def.h"

/* 供 usb_device.c 注册的描述符集合（全速） */
extern USBD_DescriptorsTypeDef FS_Desc;

#endif /* __USBD_DESC_H */
