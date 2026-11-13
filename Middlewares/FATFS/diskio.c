/* ============================================================
 * diskio.c —— FatFs R0.14b 与本项目 SDIO 底层之间的胶水层（P2.1）
 *
 * 本文件为本项目自行编写，仅调用 ChaN FatFs 定义的 disk_* 标准接口
 * 与 sdio_sd.h 的轮询读函数；不移植任何第三方 diskio 实现。
 *
 * 单卷：pdrv 0 = TF 卡（SDIO）。
 * 只读：FF_FS_READONLY=1，disk_write() 恒返回 RES_WRPRT。
 * 对齐：FatFs 传入的 buff 不保证 4 字节对齐，而 HAL_SD_ReadBlocks()
 *       按 32bit 访问，故未对齐时经静态对齐缓冲中转。
 * ============================================================ */
#include <string.h>        /* memcpy */
#include "ff.h"
#include "diskio.h"
#include "sdio_sd.h"

#define SD_PDRV   0

/* 静态对齐缓冲：避免为 FatFs 的每个 buffer 加对齐约束 */
#if defined(__ARMCC_VERSION) || defined(__GNUC__)
static uint8_t s_align_buf[SD_SECTOR_SIZE] __attribute__((aligned(4)));
#else
static uint8_t s_align_buf[SD_SECTOR_SIZE];
#endif

static volatile DSTATUS s_stat = STA_NOINIT;

/* ------------------------------------------------------------ */
DSTATUS disk_status(BYTE pdrv)
{
    if (pdrv != SD_PDRV) return STA_NOINIT;
    return s_stat;
}

/* ------------------------------------------------------------ */
DSTATUS disk_initialize(BYTE pdrv)
{
    if (pdrv != SD_PDRV) return STA_NOINIT;

    if (sd_init() == 0) {
        s_stat = 0;                       /* 已就绪、非写保护 */
    } else {
        s_stat = STA_NOINIT | STA_NODISK;
    }
    return s_stat;
}

/* ------------------------------------------------------------ */
DRESULT disk_read(BYTE pdrv, BYTE *buff, LBA_t sector, UINT count)
{
    UINT i;
    uint8_t rc;

    if (pdrv != SD_PDRV || count == 0) return RES_PARERR;
    if (s_stat & STA_NOINIT)           return RES_NOTRDY;

    /* 对齐且单缓冲直读；未对齐则逐扇区中转 */
    if (((uint32_t)buff & 3u) == 0u) {
        rc = sd_read_blocks((uint32_t)sector, buff, count);
        return (rc == 0) ? RES_OK : RES_ERROR;
    }

    for (i = 0; i < count; i++) {
        rc = sd_read_blocks((uint32_t)(sector + i), s_align_buf, 1u);
        if (rc != 0) return RES_ERROR;
        memcpy(buff + (i * SD_SECTOR_SIZE), s_align_buf, SD_SECTOR_SIZE);
    }
    return RES_OK;
}

/* ------------------------------------------------------------ */
DRESULT disk_write(BYTE pdrv, const BYTE *buff, LBA_t sector, UINT count)
{
    (void)pdrv; (void)buff; (void)sector; (void)count;
    return RES_WRPRT;      /* P2.1 只读，防止误写 TF 卡 */
}

/* ------------------------------------------------------------ */
DRESULT disk_ioctl(BYTE pdrv, BYTE cmd, void *buff)
{
    (void)buff;
    if (pdrv != SD_PDRV)                return RES_PARERR;
    if (s_stat & STA_NOINIT)            return RES_NOTRDY;

    switch (cmd) {
    case CTRL_SYNC:                     /* 无写缓存，直接成功 */
        return RES_OK;

    case GET_SECTOR_COUNT:
        *(LBA_t *)buff = (LBA_t)sd_sector_count();
        return RES_OK;

    case GET_SECTOR_SIZE:
        *(WORD *)buff = (WORD)SD_SECTOR_SIZE;
        return RES_OK;

    case GET_BLOCK_SIZE:
        *(DWORD *)buff = 1u;           /* 未知擦除块大小，返回 1 扇区 */
        return RES_OK;

    case CTRL_TRIM:
        return RES_OK;

    default:
        return RES_PARERR;
    }
}
