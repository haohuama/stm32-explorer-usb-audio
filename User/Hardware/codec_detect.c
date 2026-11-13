#include "codec_detect.h"

/* 判定矩阵（仅看地址帧应答，绝不写寄存器）：
 *   WM8978 : 写 0x34 ACK 且 读 0x35 NACK（只写器件对读地址无应答）
 *   ES8388 : 写 0x20 ACK 且 读 0x21 ACK（可读写）
 *   两者都 ACK → 异常/冲突，不下结论
 */
codec_type_t codec_detect(const soft_i2c_t *bus)
{
    uint8_t a34 = i2c_soft_probe_addr(bus, 0x34); /* WM8978 写地址 (0x1A<<1|0) */
    uint8_t a35 = i2c_soft_probe_addr(bus, 0x35); /* WM8978 读地址 (0x1A<<1|1) */
    uint8_t a20 = i2c_soft_probe_addr(bus, 0x20); /* ES8388 写地址 (0x10<<1|0) */
    uint8_t a21 = i2c_soft_probe_addr(bus, 0x21); /* ES8388 读地址 (0x10<<1|1) */

    if (a34 && !a35 && a20 && a21) return CODEC_AMBIGUOUS;
    if (a34 && !a35)              return CODEC_WM8978;
    if (a20 && a21)               return CODEC_ES8388;
    return CODEC_NONE;
}
