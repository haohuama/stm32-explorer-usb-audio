/* ============================================================
 * wm8978.h —— WM8978 音频 CODEC 驱动（仅 I2C 控制层，不含 I2S）
 *
 * 目标硬件：正点原子「探索者 STM32F4 V2.7」+ WM8978
 *           （本项目已于 2026-11-13 用 I2C 只读地址帧实测确认：
 *             写 0x34 ACK、读 0x35 NACK → WM8978，只写器件）
 *
 * 来源声明：本驱动的寄存器配置序列与函数接口参照 lovelyterry/SmartSpeaker
 *           （MIT License）与正点原子官方 wm8978 例程的公开接口，经本项目
 *           改造为：① 基于 i2c_soft 软件 I2C；② HAL/ARMCLANG 可编译的
 *           定宽类型；③ 去掉一切板级 GPIO 初始化（引脚由工程统一配置）。
 *
 * 重要硬件事实：
 *   1) WM8978 的 I2C 是「只写」的：datasheet Rev4.5 p82 明确读操作会直接
 *      返回空闲、不发 ACK。因此本驱动维护一份 58 项的寄存器镜像
 *      g_wm8978_regs[]，所有「读」操作都是读镜像，不是读芯片。
 *   2) 写一帧 = 2 字节：byte1 = (reg<<1) | (val>>8)，byte2 = val & 0xFF。
 *   3) WM8978 的 I2S 侧是从机（由 MCU 提供 BCLK/LRCK/MCLK）；
 *      寄存器 R4 的 FMT 必须与 MCU 侧 I2S 标准一致（本工程用飞利浦标准）。
 * ============================================================ */
#ifndef __WM8978_H
#define __WM8978_H

#include "stm32f4xx_hal.h"
#include "i2c_soft.h"

/* WM8978 的 8 位写地址（7 位地址 0x1A << 1） */
#define WM8978_ADDR        0x34u

/* R4 的 FMT 字段：I2S 数据格式 */
#define WM8978_FMT_RIGHT_J   0u   /* 右对齐（LSB）*/
#define WM8978_FMT_LEFT_J    1u   /* 左对齐（MSB）*/
#define WM8978_FMT_I2S       2u   /* 飞利浦标准 I2S —— 本工程用这个 */
#define WM8978_FMT_PCM       3u   /* PCM/DSP */

/* R4 的 WL 字段：字长 */
#define WM8978_WL_16BIT      0u
#define WM8978_WL_20BIT      1u
#define WM8978_WL_24BIT      2u
#define WM8978_WL_32BIT      3u

/* 绑定 WM8978 所在的 I2C 总线（本板为 PB8=SCL / PB9=SDA，已实测） */
void WM8978_BindBus(const soft_i2c_t *bus);

/* 读寄存器（实际读的是内存镜像，因为芯片只写） */
uint16_t WM8978_ReadReg(uint8_t reg);
/* 写寄存器，返回 0=成功，1=失败（NACK/总线异常）。同时更新镜像。 */
uint8_t  WM8978_WriteReg(uint8_t reg, uint16_t val);

/* 上电初始化 + 复位（不包含 I2S 引脚，I2S 由 i2s_audio.c 负责）
 * 返回 0=全部写入成功，非 0=有寄存器写入失败（通常是 I2C 不通/芯片不在位） */
uint8_t WM8978_Init(void);

/* 放音模式：开 DAC、关输入、开输出、设 I2S 飞利浦 16bit */
void WM8978_PlayMode(void);
/* 录音模式（本阶段不用，保留接口） */
void WM8978_RecoMode(void);

/* 音量：0~63；0 会静音。耳机用 HPvol，喇叭（SPK）用 SPKvol */
void WM8978_HPvol_Set(uint8_t voll, uint8_t volr);
void WM8978_SPKvol_Set(uint8_t volx);

/* 分项配置（需要细调时用） */
void WM8978_I2S_Cfg(uint8_t fmt, uint8_t len);
void WM8978_ADDA_Cfg(uint8_t dacen, uint8_t adcen);
void WM8978_Input_Cfg(uint8_t micen, uint8_t lineinen, uint8_t auxen);
void WM8978_Output_Cfg(uint8_t dacen, uint8_t bpsen);
void WM8978_MIC_Gain(uint8_t gain);
void WM8978_LINEIN_Gain(uint8_t gain);
void WM8978_AUX_Gain(uint8_t gain);

#endif /* __WM8978_H */
