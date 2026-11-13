/* ============================================================
 * wav_probe.c —— WAV(RIFF/PCM) 头解析实现
 *
 * 只做小端读取，不依赖 struct 打包/对齐，避免 ARM 对齐陷阱。
 * 支持 fmt chunk 后跟 LIST/fact 等任意 chunk 再出现 data 的常见布局。
 * ============================================================ */
#include <string.h>
#include "wav_probe.h"

static uint16_t rd_u16(const uint8_t *p)
{
    return (uint16_t)((uint16_t)p[0] | ((uint16_t)p[1] << 8));
}

static uint32_t rd_u32(const uint8_t *p)
{
    return (uint32_t)p[0]
         | ((uint32_t)p[1] << 8)
         | ((uint32_t)p[2] << 16)
         | ((uint32_t)p[3] << 24);
}

uint8_t wav_parse_header(const uint8_t *buf, uint32_t len, wav_info_t *out)
{
    uint32_t pos;
    uint8_t  got_fmt  = 0;
    uint8_t  got_data = 0;

    if (out == 0)   return 7;
    memset(out, 0, sizeof(*out));
    if (buf == 0 || len < 44u) return 1;

    /* RIFF header: "RIFF" + size + "WAVE" */
    if (memcmp(buf, "RIFF", 4) != 0) return 2;
    if (memcmp(buf + 8, "WAVE", 4) != 0) return 3;

    pos = 12u;
    while ((pos + 8u) <= len) {
        const uint8_t *id = buf + pos;
        uint32_t sz = rd_u32(buf + pos + 4);
        const uint8_t *body = buf + pos + 8;

        if (memcmp(id, "fmt ", 4) == 0) {
            if (sz < 16u || (pos + 8u + 16u) > len) return 5;
            out->audio_format    = rd_u16(body + 0);
            out->channels        = rd_u16(body + 2);
            out->sample_rate     = rd_u32(body + 4);
            out->byte_rate       = rd_u32(body + 8);
            out->block_align     = rd_u16(body + 12);
            out->bits_per_sample = rd_u16(body + 14);
            got_fmt = 1;
        } else if (memcmp(id, "data", 4) == 0) {
            out->data_size   = sz;
            out->data_offset = pos + 8u;
            got_data = 1;
            break;                       /* PCM 数据从这里开始，不必再扫 */
        }

        if (sz > len) break;             /* 防御损坏文件 */
        pos += 8u + sz + (sz & 1u);      /* chunk 按偶数字节对齐 */
    }

    if (!got_fmt)  return 4;
    if (!got_data) return 6;

    if (out->byte_rate != 0u) {
        out->duration_ms = (uint32_t)(((uint64_t)out->data_size * 1000u)
                                      / out->byte_rate);
    }
    return 0;
}

uint32_t wav_check_compatible(const wav_info_t *info)
{
    uint32_t e = 0;
    if (info == 0) return 0xFFu;

    if (info->sample_rate     != WAV_TARGET_RATE)     e |= WAV_ERR_RATE;
    if (info->bits_per_sample != WAV_TARGET_BITS)     e |= WAV_ERR_BITS;
    if (info->channels        != WAV_TARGET_CHANNELS) e |= WAV_ERR_CHANNELS;
    if (info->audio_format    != 1u)                  e |= WAV_ERR_FORMAT;
    if (info->data_size       == 0u ||
        info->block_align     == 0u ||
        (info->data_size % info->block_align) != 0u)  e |= WAV_ERR_DATASIZE;
    return e;
}
