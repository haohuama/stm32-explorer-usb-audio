/*-----------------------------------------------------------------------/
/  Low level disk interface module include file
/
/  Interface declarations follow the ChaN FatFs R0.14 diskio.h API
/  (DSTATUS/DRESULT/disk_* prototypes and CTRL_* command codes).
/  This file is the project's own clean header; ff.c / ff.h / ffunicode.c
/  are ChaN originals distributed under the FatFs License (see LICENSE.txt).
/-----------------------------------------------------------------------*/

#ifndef _DISKIO_DEFINED
#define _DISKIO_DEFINED

#ifdef __cplusplus
extern "C" {
#endif

#include "ff.h"

typedef BYTE    DSTATUS;

typedef enum {
    RES_OK = 0,
    RES_ERROR,
    RES_WRPRT,
    RES_NOTRDY,
    RES_PARERR
} DRESULT;

DSTATUS disk_initialize (BYTE pdrv);
DSTATUS disk_status     (BYTE pdrv);
DRESULT disk_read       (BYTE pdrv, BYTE *buff, LBA_t sector, UINT count);
DRESULT disk_write      (BYTE pdrv, const BYTE *buff, LBA_t sector, UINT count);
DRESULT disk_ioctl      (BYTE pdrv, BYTE cmd, void *buff);

/* Disk status bits */
#define STA_NOINIT      0x01
#define STA_NODISK      0x02
#define STA_PROTECT     0x04

/* Generic ioctl commands used by FatFs */
#define CTRL_SYNC           0
#define GET_SECTOR_COUNT    1
#define GET_SECTOR_SIZE     2
#define GET_BLOCK_SIZE      3
#define CTRL_TRIM           4

/* Generic ioctl commands not used by FatFs */
#define CTRL_POWER          5
#define CTRL_LOCK           6
#define CTRL_EJECT          7
#define CTRL_FORMAT         8

/* MMC/SDC specific ioctl commands */
#define MMC_GET_TYPE        10
#define MMC_GET_CSD         11
#define MMC_GET_CID         12
#define MMC_GET_OCR         13
#define MMC_GET_SDSTAT      14

/* ATA/CF specific ioctl commands */
#define ATA_GET_REV         20
#define ATA_GET_MODEL       21
#define ATA_GET_SN          22

#ifdef __cplusplus
}
#endif

#endif
