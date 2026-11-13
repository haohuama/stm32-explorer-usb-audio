/* ============================================================
 * usbd_conf.h —— USB 设备库硬件适配层头文件（HAL 版）
 *
 * 把 ST 官方 USB 设备库（Core + CDC class）绑定到本工程：
 *   - STM32F407ZGT6 的 USB_OTG_FS（PA11/PA12，全速 12Mbps）
 *   - 用 HAL 的 PCD 驱动（stm32f4xx_hal_pcd.c 已在工程内）
 *
 * 重要：本文件【禁止】#include "usbd_core.h"。
 *   usbd_core.h / usbd_def.h 都会反过来 #include "usbd_conf.h"，若这里再 include
 *   usbd_core.h 就形成循环包含；且该循环会让 usbd_def.h 在 uint8_t / USBD_StatusTypeDef
 *   尚未可见时被解析，导致全工程 "unknown type / conflicting types"。
 *   本文件只需 stm32f4xx_hal.h（提供 stdint 与 PCD_HandleTypeDef），其余 USBD_LL_*
 *   原型由 usbd_core.h 提供（usbd_conf.c 改去 include usbd_core.h）。
 * ============================================================ */
#ifndef __USBD_CONF_H
#define __USBD_CONF_H

#include "stm32f4xx_hal.h"
#include <stdlib.h>   /* USBD_malloc / USBD_free 底层用 malloc/free */

/* ---- 动态内存分配：CDC class 用 USBD_malloc/free 分配句柄（HAL 模板惯例）---- */
#ifndef USBD_malloc
#define USBD_malloc     malloc
#endif
#ifndef USBD_free
#define USBD_free       free
#endif

/* ---- 描述符相关宏（原 usbd_desc_template.h 提供，这里集中定义）---- */
#define USBD_LANGID_STRING         0x0409U   /* 英语(美国) */
#define USBD_MAX_STR_DESC_SIZ      0x100U
#define USB_SIZ_STRING_SERIAL      0x1AU
#define DEVICE_ID1                 UID_BASE
#define DEVICE_ID2                 (UID_BASE + 0x04U)
#define DEVICE_ID3                 (UID_BASE + 0x08U)

/* ---- USB 设备库可配置项（usbd_def.h 里也有默认，这里显式给出）---- */
#ifndef USBD_SELF_POWERED
#define USBD_SELF_POWERED          1U
#endif
#ifndef USBD_MAX_POWER
#define USBD_MAX_POWER             0x32U     /* 100mA（2mA 单位） */
#endif

/* ---- 全局 PCD 句柄（由 usbd_conf.c 定义，其余引用）---- */
extern PCD_HandleTypeDef hpcd_USB_OTG_FS;

#endif /* __USBD_CONF_H */
