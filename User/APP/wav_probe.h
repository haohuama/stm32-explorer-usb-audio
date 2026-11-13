/* ============================================================
 * wav_probe.h —— WAV(RIFF/PCM) 头解析（P2.1，纯软件、无硬件依赖）
 *
 * 用途：在接 I2S 之前，先把卡里 WAV 的真实参数打印出来并校验，
 *       避免把 48kHz / 单声道 / 24bit 的文件喂给固定 44.1kHz/16bit/立体声
 *       的 I2S 链路而误判成"音频驱动坏了"。
 *
 * 与本项目 I2S 时钟绑定：PLLI2SN=271 / PLLI2SR=2 → 固定 44.1kHz。
 * ============================================================ */
#ifndef __WAV_PROBE_H
#define __WAV_PROBE_H

#include <stdint.h>

#define WAV_TARGET_RATE     44100u
#define WAV_TARGET_BITS     16u
#define WAV_TARGET_CHANNELS 2u

typedef struct {
    uint32_t sample_rate;
    uint16_t channels;
    uint16_t bits_per_sample;
    uint16_t audio_format;      /* 1 = PCM */
    uint32_t byte_rate;
    uint16_t block_align;
    uint32_t data_size;         /* data chunk 字节数 */
    uint32_t data_offset;       /* PCM 数据在文件中的起始偏移 */
    uint32_t duration_ms;       /* 由 data_size / byte_rate 推算 */
} wav_info_t;

/* 解析完整文件头（读前 512 字节足够覆盖常见 chunk 组合）。
   0=成功；非 0=错误码：
     1 文件太短  2 非 RIFF  3 非 WAVE  4 找不到 fmt
     5 fmt 长度不足  6 找不到 data  7 文件读取失败 */
uint8_t wav_parse_header(const uint8_t *buf, uint32_t len, wav_info_t *out);

/* 校验是否适配本工程 I2S。0=适配；位标志见 wav_check() 实现 */
uint32_t wav_check_compatible(const wav_info_t *info);
#define WAV_ERR_RATE     0x01u
#define WAV_ERR_BITS     0x02u
#define WAV_ERR_CHANNELS 0x04u
#define WAV_ERR_FORMAT   0x08u
#define WAV_ERR_DATASIZE 0x10u

#endif
