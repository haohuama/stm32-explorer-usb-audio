/* ============================================================
 * usbd_cdc_if.h —— CDC 应用接口头文件（基于 ST usbd_cdc_if_template.h）
 * ============================================================ */
#ifndef __USBD_CDC_IF_H
#define __USBD_CDC_IF_H

#include "usbd_cdc.h"

/* CDC 类应用回调集合（在 usbd_cdc_if.c 定义） */
extern USBD_CDC_ItfTypeDef USBD_CDC_fops_FS;

#endif /* __USBD_CDC_IF_H */
