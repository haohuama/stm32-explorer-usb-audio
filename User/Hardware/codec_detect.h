#ifndef __CODEC_DETECT_H
#define __CODEC_DETECT_H
#include "i2c_soft.h"

typedef enum {
    CODEC_NONE      = 0,   /* 未识别 */
    CODEC_WM8978    = 1,   /* 7位 0x1A，只写 */
    CODEC_ES8388    = 2,   /* 7位 0x10，可读写 */
    CODEC_AMBIGUOUS = 3    /* 两个地址都应答，需人工核对 */
} codec_type_t;

/* 在一组 I2C 引脚上探测 CODEC 型号（只读地址帧，不写寄存器） */
codec_type_t codec_detect(const soft_i2c_t *bus);

#endif /* __CODEC_DETECT_H */
