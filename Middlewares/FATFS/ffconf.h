/*---------------------------------------------------------------------------/
/  FatFs Functional Configurations  (P2.1: TF card read-only probe)
/  FatFs R0.14b -- configuration for STM32F407 Explorer / SDIO TF card
/
/  NOTE: ff.c / ff.h / ffunicode.c are ChaN original files (FatFs License,
/        see LICENSE.txt). This configuration file is written for this project.
/---------------------------------------------------------------------------*/

#define FFCONF_DEF  86631   /* Revision ID -- must match ff.h FF_DEFINED */

/*---------------------------------------------------------------------------/
/ Function Configurations
/---------------------------------------------------------------------------*/

#define FF_FS_READONLY  1
/* 1: Read-only. P2.1/P2.2 only read WAV files; prevents accidental card writes. */

#define FF_FS_MINIMIZE  0
/* 0: All basic API available (f_opendir / f_readdir / f_stat ...). */

#define FF_USE_FIND     0
#define FF_USE_MKFS     0   /* No formatting on MCU */
#define FF_USE_FASTSEEK 0
#define FF_USE_EXPAND   0
#define FF_USE_CHMOD    0
#define FF_USE_LABEL    0
#define FF_USE_FORWARD  0

#define FF_USE_STRFUNC  0   /* No f_gets/f_putc/f_printf -> no stdio/va_list dependency */
#define FF_PRINT_LLI    0
#define FF_PRINT_FLOAT  0
#define FF_STRF_ENCODE  0

/*---------------------------------------------------------------------------/
/ Locale and Namespace Configurations
/---------------------------------------------------------------------------*/

#define FF_CODE_PAGE    936
/* 936 = GBK / Simplified Chinese. Must match the LCD font encoding (GBK).
   Requires ffunicode.c to be compiled into the project. */

#define FF_USE_LFN      0
/* 0 = no long file name. Keil MDK-Lite caps the image at 32KB; LFN pulls the
   GBK 936 DBCS tables into the link. P2.1 only mounts/lists/reads 8.3 names.
   Re-enable (1) after upgrading to a licensed Keil, together with ffunicode.c. */
#define FF_MAX_LFN      255
/* 1 = static LFN working buffer (no malloc / no ffsystem.c needed).
   Single-threaded main loop; not reentrant, which is fine here. */

#define FF_LFN_UNICODE  0   /* API strings are ANSI/OEM (GBK), NOT UTF-8 */
#define FF_LFN_BUF      255
#define FF_SFN_BUF      12

#define FF_FS_RPATH     0
#define FF_VOLUMES      1   /* Only one physical drive: SD card (pdrv 0) */
#define FF_STR_VOLUME_ID 0
#define FF_VOLUME_STRS  "SD"
#define FF_MULTI_PARTITION 0

#define FF_MIN_SS       512
#define FF_MAX_SS       512
#define FF_LBA64        0   /* TF cards here are FAT32 <= 32GB */
#define FF_MIN_GPT      0x10000000
#define FF_USE_TRIM     0

/*---------------------------------------------------------------------------/
/ Drive Configurations
/---------------------------------------------------------------------------*/

#define FF_FS_TINY      1
/* 1 = FIL shares the FATFS common sector buffer -> saves 512 bytes per FIL. */

#define FF_FS_EXFAT     0
/* 0 = FAT16/FAT32 only. Cards must be formatted FAT32 (see docs). */

#define FF_FS_NORTC     1
#define FF_NORTC_MON    1
#define FF_NORTC_MDAY   1
#define FF_NORTC_YEAR   2026
/* No RTC peripheral (whitelist) and no get_fattime() implementation needed. */

#define FF_FS_NOFSINFO  0
#define FF_FS_LOCK      0
#define FF_FS_REENTRANT 0
#define FF_FS_TIMEOUT   1000
