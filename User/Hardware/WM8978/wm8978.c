/* ============================================================
 * wm8978.c —— WM8978 控制层实现（软件 I2C，仅写）
 *
 * 参照 lovelyterry/SmartSpeaker（MIT License）与正点原子官方例程的寄存器
 * 配置序列，改造点：
 *   1) 底层从 soft_iic 换成本工程的 i2c_soft（开漏 GPIO 位操作）；
 *   2) 类型统一为 uint8_t / uint16_t（HAL + ARMCLANG）；
 *   3) 不含任何 GPIO 初始化（PB8/PB9 由 i2c_soft_init 配，I2S 引脚由
 *      i2s_audio.c 配），避免误改 I2S 复用引脚。
 * ============================================================ */
#include "wm8978.h"

/* WM8978 只写，因此寄存器值全部缓存在这里。
 * 数组长度 58 = WM8978 寄存器最大编号 (R57) + 1。 */
static uint16_t g_wm8978_regs[58] = {
    0x0000, 0x0000, 0x0000, 0x0000, 0x0050, 0x0000, 0x0140, 0x0000,
    0x0000, 0x0000, 0x0000, 0x00FF, 0x00FF, 0x0000, 0x0100, 0x00FF,
    0x00FF, 0x0000, 0x012C, 0x002C, 0x002C, 0x002C, 0x002C, 0x0000,
    0x0032, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000, 0x0000,
    0x0038, 0x000B, 0x0032, 0x0000, 0x0008, 0x000C, 0x0093, 0x00E9,
    0x0000, 0x0000, 0x0000, 0x0000, 0x0003, 0x0010, 0x0010, 0x0100,
    0x0100, 0x0002, 0x0001, 0x0001, 0x0039, 0x0039, 0x0039, 0x0039,
    0x0001, 0x0001
};

/* WM8978 挂在哪条 I2C 总线上，由 WM8978_BindBus 指定 */
static const soft_i2c_t *g_wm8978_bus = 0;

void WM8978_BindBus(const soft_i2c_t *bus)
{
    g_wm8978_bus = bus;
}

uint16_t WM8978_ReadReg(uint8_t reg)
{
    if (reg >= 58u) return 0;
    return g_wm8978_regs[reg];
}

uint8_t WM8978_WriteReg(uint8_t reg, uint16_t val)
{
    if (g_wm8978_bus == 0) return 1;              /* 未绑定总线 */
    if (reg >= 58u) return 1;

    val &= 0x01FFu;                                /* 寄存器只有 9 位有效 */

    i2c_soft_start(g_wm8978_bus);

    /* 器件地址（写） */
    if (i2c_soft_write_byte(g_wm8978_bus, WM8978_ADDR)) {
        i2c_soft_stop(g_wm8978_bus);
        return 1;
    }
    /* 第 1 字节：寄存器地址(7bit) + 数据最高位 */
    if (i2c_soft_write_byte(g_wm8978_bus,
            (uint8_t)(((reg << 1) & 0xFEu) | ((val >> 8) & 0x01u)))) {
        i2c_soft_stop(g_wm8978_bus);
        return 1;
    }
    /* 第 2 字节：数据低 8 位 */
    if (i2c_soft_write_byte(g_wm8978_bus, (uint8_t)(val & 0xFFu))) {
        i2c_soft_stop(g_wm8978_bus);
        return 1;
    }

    i2c_soft_stop(g_wm8978_bus);

    g_wm8978_regs[reg] = val;                      /* 更新镜像 */
    return 0;
}

/* 一次设定耳机左右 + 喇叭左右音量（0~63） */
void WM8978_SetVolume(uint8_t vol)
{
    uint16_t v;
    vol &= 0x3Fu;
    v = vol;
    WM8978_WriteReg(52, v);
    WM8978_WriteReg(53, (uint16_t)(v | (1u << 8)));   /* HPVU=1 同步更新 */
    WM8978_WriteReg(54, v);
    WM8978_WriteReg(55, (uint16_t)(v | (1u << 8)));   /* SPKVU=1 同步更新 */
}

void WM8978_MIC_Gain(uint8_t gain)
{
    gain &= 0x3Fu;
    WM8978_WriteReg(45, gain);
    WM8978_WriteReg(46, (uint16_t)(gain | (1u << 8)));
}

/* fmt: 0=右对齐 1=左对齐 2=飞利浦I2S 3=PCM ; len: 0=16bit 1=20bit 2=24bit 3=32bit */
void WM8978_I2S_Cfg(uint8_t fmt, uint8_t len)
{
    fmt &= 0x03u;
    len &= 0x03u;
    WM8978_WriteReg(4, (uint16_t)((fmt << 3) | (len << 5)));
}

void WM8978_ADDA_Cfg(uint8_t dacen, uint8_t adcen)
{
    uint16_t regval;

    regval = WM8978_ReadReg(3);
    if (dacen) regval |= 3u << 0;
    else       regval &= (uint16_t)~(3u << 0);
    WM8978_WriteReg(3, regval);

    regval = WM8978_ReadReg(2);
    if (adcen) regval |= 3u << 0;
    else       regval &= (uint16_t)~(3u << 0);
    WM8978_WriteReg(2, regval);
}

/* gain: 0~7，0=关闭，1~7 = -12dB~6dB，3dB/step */
void WM8978_LINEIN_Gain(uint8_t gain)
{
    uint16_t regval;

    gain &= 0x07u;
    regval = WM8978_ReadReg(47);
    regval &= (uint16_t)~(7u << 4);
    WM8978_WriteReg(47, (uint16_t)(regval | ((uint16_t)gain << 4)));

    regval = WM8978_ReadReg(48);
    regval &= (uint16_t)~(7u << 4);
    WM8978_WriteReg(48, (uint16_t)(regval | ((uint16_t)gain << 4)));
}

void WM8978_AUX_Gain(uint8_t gain)
{
    uint16_t regval;

    gain &= 0x07u;
    regval = WM8978_ReadReg(47);
    regval &= (uint16_t)~(7u << 0);
    WM8978_WriteReg(47, (uint16_t)(regval | (uint16_t)gain));

    regval = WM8978_ReadReg(48);
    regval &= (uint16_t)~(7u << 0);
    WM8978_WriteReg(48, (uint16_t)(regval | (uint16_t)gain));
}

void WM8978_Input_Cfg(uint8_t micen, uint8_t lineinen, uint8_t auxen)
{
    uint16_t regval;

    regval = WM8978_ReadReg(2);
    if (micen) regval |= 3u << 2;                     /* INPPGAENR/L */
    else       regval &= (uint16_t)~(3u << 2);
    WM8978_WriteReg(2, regval);

    regval = WM8978_ReadReg(44);
    if (micen) regval |= (3u << 4) | (3u << 0);       /* BUFFER→PGA 通路 */
    else       regval &= (uint16_t)~((3u << 4) | (3u << 0));
    WM8978_WriteReg(44, regval);

    WM8978_LINEIN_Gain(lineinen ? 5 : 0);              /* 5 = 0dB */
    WM8978_AUX_Gain(auxen ? 7 : 0);                    /* 7 = +6dB */
}

/* dacen: DAC→输出；bpsen: 旁路（模拟直通） */
void WM8978_Output_Cfg(uint8_t dacen, uint8_t bpsen)
{
    uint16_t regval = 0;

    if (dacen) regval |= 1u << 0;
    if (bpsen) {
        regval |= 1u << 1;
        regval |= 5u << 2;                             /* 0dB */
    }
    WM8978_WriteReg(50, regval);
    WM8978_WriteReg(51, regval);
}

void WM8978_HPvol_Set(uint8_t voll, uint8_t volr)
{
    voll &= 0x3Fu;
    volr &= 0x3Fu;
    if (voll == 0) voll |= 1u << 6;                     /* HPVU 静音位 */
    if (volr == 0) volr |= 1u << 6;

    WM8978_WriteReg(52, voll);
    WM8978_WriteReg(53, (uint16_t)(volr | (1u << 8)));
}

void WM8978_SPKvol_Set(uint8_t volx)
{
    volx &= 0x3Fu;
    if (volx == 0) volx |= 1u << 6;

    WM8978_WriteReg(54, volx);
    WM8978_WriteReg(55, (uint16_t)(volx | (1u << 8)));
}

/* 上电初始化：复位 → 关音量防爆音 → 开 BIAS/VMID/输出 → 关掉不需要的旁路
 * 返回 0 = 全部成功；非 0 = 至少一处写入失败（I2C 不通或芯片不在位） */
uint8_t WM8978_Init(void)
{
    uint8_t err = 0;

    if (g_wm8978_bus == 0) return 1;

    i2c_soft_init(g_wm8978_bus);                        /* PB8/PB9 开漏 + 上拉 */

    err |= WM8978_WriteReg(0, 0x0000);                  /* 软复位 */

    /* 先把音量关到最小，避免上电噪声 */
    WM8978_HPvol_Set(0, 0);
    WM8978_SPKvol_Set(0);

    err |= WM8978_WriteReg(1, 0x001B);   /* R1: MICEN/BIASEN/VMIDSEL=11(5k) */
    err |= WM8978_WriteReg(2, 0x01B0);   /* R2: ROUT1/LOUT1 使能(耳机), BOOSTEN */
    err |= WM8978_WriteReg(3, 0x006C);   /* R3: LOUT2/ROUT2 使能(喇叭), LMIX/RMIX */
    err |= WM8978_WriteReg(6, 0x0000);   /* R6: MCLK 由外部（MCU）提供 */

    err |= WM8978_WriteReg(43, (uint16_t)(1u << 4));  /* R43: INVROUT2 反相驱动喇叭 */
    err |= WM8978_WriteReg(47, (uint16_t)(1u << 8));  /* R47: PGABOOSTL 20dB */
    err |= WM8978_WriteReg(48, (uint16_t)(1u << 8));  /* R48: PGABOOSTR 20dB */
    err |= WM8978_WriteReg(49, (uint16_t)(1u << 1));  /* R49: TSDEN 过热保护 */
    err |= WM8978_WriteReg(10, (uint16_t)(1u << 3));  /* R10: DAC 128x 过采样 */
    err |= WM8978_WriteReg(14, (uint16_t)(1u << 3));  /* R14: ADC 128x 过采样 */

    return err;                                         /* 0 = OK */
}

/* 放音模式 */
void WM8978_PlayMode(void)
{
    WM8978_ADDA_Cfg(1, 0);        /* 开 DAC，关 ADC */
    WM8978_Input_Cfg(0, 0, 0);    /* 关所有模拟输入，避免噪声混入 */
    WM8978_Output_Cfg(1, 0);      /* DAC → 输出；不开 bypass */
    WM8978_HPvol_Set(20, 20);     /* 耳机中等音量 */
    WM8978_SPKvol_Set(0x30);      /* 喇叭音量（0~63）；先给中等 */
    WM8978_MIC_Gain(0);
    WM8978_I2S_Cfg(WM8978_FMT_I2S, WM8978_WL_16BIT);   /* 与 MCU 侧一致 */
}

/* 录音模式（保留，本阶段不用） */
void WM8978_RecoMode(void)
{
    WM8978_ADDA_Cfg(0, 1);
    WM8978_Input_Cfg(1, 0, 0);
    WM8978_Output_Cfg(0, 1);
    WM8978_HPvol_Set(0, 0);
    WM8978_SPKvol_Set(0);
    WM8978_MIC_Gain(50);
    WM8978_I2S_Cfg(WM8978_FMT_I2S, WM8978_WL_16BIT);
}
