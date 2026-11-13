/* ============================================================
 * p2_selftest.c —— P2.1 零风险自检实现
 *
 * 输出全部通过 CH340 → USART1（由 main.c 注入打印回调），
 * 不使用 printf / malloc / 中断，不触碰任何音频或 USB 外设。
 * ============================================================ */
#include <string.h>
#include "ff.h"
#include "sdio_sd.h"
#include "wav_probe.h"
#include "p2_selftest.h"

static FATFS  s_fs;                 /* 卷 0 文件系统对象（静态，避免 malloc） */
static FIL    s_fil;
static DIR    s_dir;
static FILINFO s_fno;
static uint8_t s_hdr[512] __attribute__((aligned(4)));
static char    s_wav_path[FF_LFN_BUF + 1];   /* 静态：栈仅 1KB，避免把 256B 放栈上 */

static p2_puts_fn    g_puts   = 0;
static p2_put_u32_fn g_put_u32 = 0;

static void P(const char *s) { if (g_puts) g_puts(s); }
static void U(uint32_t v)   { if (g_put_u32) g_put_u32(v); }

/* 把 FRESULT 打印成 "FR_xx(code)" */
static void print_fr(const char *tag, FRESULT fr)
{
    P(tag); P(" code="); U((uint32_t)fr); P("\r\n");
}

/* 判断扩展名是否 .wav（大小写不敏感，兼容 LFN 与 8.3 短名） */
static int is_wav_name(const char *n)
{
    const char *p = n;
    const char *last = 0;
    while (*p) { if (*p == '.') last = p; p++; }
    if (!last) return 0;
    last++;
    return (last[0] == 'w' || last[0] == 'W') &&
           (last[1] == 'a' || last[1] == 'A') &&
           (last[2] == 'v' || last[2] == 'V') &&
           (last[3] == '\0');
}

static void print_wav_info(const wav_info_t *w)
{
    uint32_t bad;

    P("    rate=");     U(w->sample_rate);
    P(" Hz  bits=");    U(w->bits_per_sample);
    P("  ch=");         U(w->channels);
    P("  fmt=");        U(w->audio_format);      P("\r\n");
    P("    byte_rate="); U(w->byte_rate);
    P(" B/s  data=");   U(w->data_size);
    P(" B  offset=");   U(w->data_offset);       P("\r\n");
    P("    duration="); U(w->duration_ms);       P(" ms\r\n");

    bad = wav_check_compatible(w);
    if (bad == 0) {
        P("    [OK] 适配本工程 I2S: 44100Hz/16bit/立体声 PCM\r\n");
    } else {
        P("    [WARN] 格式不符 flags="); U(bad);
        P("  (1=rate 2=bits 4=ch 8=非PCM 16=data)\r\n");
        P("           请转成 44100Hz/16bit/立体声 WAV 后再进 P2.2\r\n");
    }
}

int p2_selftest_run(p2_puts_fn puts, p2_put_u32_fn put_u32)
{
    FRESULT fr;
    UINT    br = 0;
    int     n_files = 0;
    int     n_wav   = 0;
    int     rc      = 0;
    char   *wav_path = s_wav_path;

    g_puts = puts; g_put_u32 = put_u32;

    P("\r\n==== P2.1  TF card / FATFS zero-risk self-test ====\r\n");
    P("SDIO PC8-PC12+PD2 AF12 | polling read | NO DMA, NO IRQ\r\n");

    /* ---- ① 挂载 ---- */
    fr = f_mount(&s_fs, "", 1);          /* opt=1 立即执行初始化 */
    if (fr != FR_OK) {
        print_fr("[P2.1] f_mount FAIL", fr);
        P("  check: TF card inserted? FAT/FAT32 formatted? 3.3V?\r\n");
        P("  sd_last_error="); U(sd_last_error()); P("\r\n");
        return 1;
    }
    P("[P2.1] f_mount     : OK\r\n");
    P("[P2.1] sector size : "); U(sd_sector_size());  P(" B\r\n");
    P("[P2.1] sector count: "); U(sd_sector_count()); P("\r\n");

    /* ---- ② 列目录 ---- */
    fr = f_opendir(&s_dir, "");
    if (fr != FR_OK) {
        print_fr("[P2.1] f_opendir FAIL", fr);
        return 2;
    }
    P("[P2.1] root dir:\r\n");
    for (;;) {
        fr = f_readdir(&s_dir, &s_fno);
        if (fr != FR_OK || s_fno.fname[0] == 0) break;
        n_files++;
        P("  - "); P(s_fno.fname);
        if (s_fno.fattrib & AM_DIR) P("  <DIR>");
        else { P("  "); U(s_fno.fsize); P(" B"); }
        P("\r\n");
    }
    f_closedir(&s_dir);
    P("[P2.1] entries     : "); U((uint32_t)n_files); P("\r\n");
    if (n_files == 0) {
        P("  [WARN] 根目录为空，请放一个 44.1k/16bit/立体声 WAV 再测\r\n");
        return 3;
    }

    /* ---- ③ 找第一个 .wav 并读头 ---- */
    fr = f_opendir(&s_dir, "");
    if (fr != FR_OK) { print_fr("[P2.1] f_opendir(2) FAIL", fr); return 4; }
    for (;;) {
        fr = f_readdir(&s_dir, &s_fno);
        if (fr != FR_OK || s_fno.fname[0] == 0) break;
        if (s_fno.fattrib & AM_DIR) continue;
        if (is_wav_name(s_fno.fname)) {
            n_wav++;
            if (n_wav == 1) {
                size_t l = strlen(s_fno.fname);
                if (l > FF_LFN_BUF) l = FF_LFN_BUF;
                memcpy(wav_path, s_fno.fname, l);
                wav_path[l] = '\0';
            }
        }
    }
    f_closedir(&s_dir);
    P("[P2.1] wav files   : "); U((uint32_t)n_wav); P("\r\n");
    if (n_wav == 0) {
        P("  [WARN] 没有 .wav 文件（MP3 不行，只认 PCM WAV）\r\n");
        return 5;
    }

    P("[P2.1] probe file  : "); P(wav_path); P("\r\n");
    fr = f_open(&s_fil, wav_path, FA_READ);
    if (fr != FR_OK) { print_fr("[P2.1] f_open FAIL", fr); return 6; }

    fr = f_read(&s_fil, s_hdr, sizeof(s_hdr), &br);
    f_close(&s_fil);
    if (fr != FR_OK) { print_fr("[P2.1] f_read FAIL", fr); return 7; }
    P("[P2.1] header bytes: "); U((uint32_t)br); P("\r\n");

    {
        wav_info_t w;
        uint8_t e = wav_parse_header(s_hdr, br, &w);
        if (e != 0) {
            P("[P2.1] WAV parse FAIL err="); U((uint32_t)e); P("\r\n");
            rc = 8;
        } else {
            print_wav_info(&w);
        }
    }

    P("[P2.1] result      : ");
    P(rc == 0 ? "PASS" : "CHECK OUTPUT ABOVE");
    P("  (no audio touched)\r\n");
    P("==== P2.1 end ====\r\n\r\n");
    return rc;
}
