/* ============================================================
 * tp.c —— XPT2046 电阻触摸（位操作 SPI，12bit）
 *
 * 一次转换流程（与 XPT2046 数据手册一致）：
 *   CS 拉低 → 发 8 位命令（如 0xD0 = 读 X，12 位，差分）→ 读 12 位 → CS 拉高
 * 按下判定用 T_PEN（低有效），配合 20ms 去抖。
 *
 * 校准：先用固定量程把原始值线性映射到屏幕，再按需微调下面的宏。
 * 串口会打印 raw 值，用「点屏幕四角看打印」就能算出真实量程。
 * ============================================================ */
#include "tp.h"
#include "stm32f4xx_hal.h"

/* ---------------- 引脚（换板/换屏只改这里） ---------------- */
#define TPEN_PORT   GPIOB
#define TPEN_PIN    GPIO_PIN_1
#define TCS_PORT    GPIOC
#define TCS_PIN     GPIO_PIN_13
#define TMISO_PORT  GPIOB
#define TMISO_PIN   GPIO_PIN_2
#define TMOSI_PORT  GPIOF
#define TMOSI_PIN   GPIO_PIN_11
#define TSCK_PORT   GPIOB
#define TSCK_PIN    GPIO_PIN_0

#define TPEN()      HAL_GPIO_ReadPin(TPEN_PORT, TPEN_PIN)
#define TMISO()     HAL_GPIO_ReadPin(TMISO_PORT, TMISO_PIN)
#define TCS(x)      HAL_GPIO_WritePin(TCS_PORT, TCS_PIN, (x) ? GPIO_PIN_SET : GPIO_PIN_RESET)
#define TMOSI(x)    HAL_GPIO_WritePin(TMOSI_PORT, TMOSI_PIN, (x) ? GPIO_PIN_SET : GPIO_PIN_RESET)
#define TSCK(x)     HAL_GPIO_WritePin(TSCK_PORT, TSCK_PIN, (x) ? GPIO_PIN_SET : GPIO_PIN_RESET)

/* ---------------- 校准（左右反了改 INV_X，上下反了改 INV_Y，轴对调改 SWAP） -------- */
#define TP_RAW_MIN   200
#define TP_RAW_MAX   3800
#define TP_SWAP_XY   1        /* 1 = 用 rawY 算屏幕 X，rawX 算屏幕 Y */
#define TP_INV_X     0
#define TP_INV_Y     1
#define TP_W         800
#define TP_H         480

#define TP_CMD_X     0xD0u    /* 读 X：A2A1A0=101，12bit，差分 */
#define TP_CMD_Y     0x90u    /* 读 Y */

static uint16_t s_raw_x, s_raw_y;

/* 触摸诊断计数（见 tp.h 说明） */
static uint32_t s_pen_seen = 0, s_read_ok = 0, s_read_bad = 0;

/* 读一次 12 位结果 */
static uint16_t tp_xfer(uint8_t cmd)
{
    uint16_t v = 0;
    uint8_t  i;

    TCS(0);
    for (i = 0; i < 8u; i++) {          /* 命令 8 位，高位先出 */
        TMOSI((cmd & 0x80u) ? 1 : 0);
        TSCK(0);
        TSCK(1);
        cmd = (uint8_t)(cmd << 1);
    }
    for (i = 0; i < 12u; i++) {         /* 读 12 位 */
        TSCK(0);
        v = (uint16_t)((v << 1) | (TMISO() ? 1u : 0u));
        TSCK(1);
    }
    TCS(1);
    return (uint16_t)(v & 0x0FFFu);
}

void tp_init(void)
{
    GPIO_InitTypeDef g = {0};

    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOF_CLK_ENABLE();

    TCS(1);
    TSCK(0);
    TMOSI(0);

    /* 输出：CS / SCK / MOSI */
    g.Mode  = GPIO_MODE_OUTPUT_PP;
    g.Pull  = GPIO_NOPULL;
    g.Speed = GPIO_SPEED_FREQ_HIGH;

    g.Pin = TCS_PIN;  HAL_GPIO_Init(TCS_PORT, &g);
    g.Pin = TSCK_PIN; HAL_GPIO_Init(TSCK_PORT, &g);
    g.Pin = TMOSI_PIN; HAL_GPIO_Init(TMOSI_PORT, &g);

    /* 输入：PEN（上拉）/ MISO（下拉也行，这里上拉） */
    g.Mode = GPIO_MODE_INPUT;
    g.Pull = GPIO_PULLUP;
    g.Pin = TPEN_PIN;  HAL_GPIO_Init(TPEN_PORT, &g);
    g.Pin = TMISO_PIN; HAL_GPIO_Init(TMISO_PORT, &g);
}

void tp_last_raw(uint16_t *rx, uint16_t *ry)
{
    if (rx) *rx = s_raw_x;
    if (ry) *ry = s_raw_y;
}

uint8_t tp_pen_level(void)
{
    return (TPEN() == GPIO_PIN_SET) ? 1u : 0u;
}

void tp_stats(uint32_t *pen, uint32_t *ok, uint32_t *bad)
{
    if (pen) *pen = s_pen_seen;
    if (ok)  *ok  = s_read_ok;
    if (bad) *bad = s_read_bad;
}

static int32_t map_axis(uint16_t raw, uint16_t span, uint8_t inv)
{
    int32_t v;

    if (raw < TP_RAW_MIN) raw = TP_RAW_MIN;
    if (raw > TP_RAW_MAX) raw = TP_RAW_MAX;
    v = (int32_t)(((uint32_t)(raw - TP_RAW_MIN) * span) / (TP_RAW_MAX - TP_RAW_MIN));
    if (inv) v = (int32_t)span - v;
    if (v < 0) v = 0;
    if (v >= (int32_t)span) v = (int32_t)span - 1;
    return v;
}

uint8_t tp_scan(uint16_t *x, uint16_t *y)
{
    static uint8_t  down_cnt = 0;
    uint32_t a, b;

    if (TPEN() != GPIO_PIN_RESET) {     /* 没按下 */
        down_cnt = 0;
        return 0;
    }
    s_pen_seen++;                       /* 诊断：PEN 确实被拉低过 */
    if (down_cnt < 2u) {                /* 去抖：连续两次才算 */
        down_cnt++;
        return 0;
    }

    /* 各读两次取平均，抖动小很多 */
    a = tp_xfer(TP_CMD_X); b = tp_xfer(TP_CMD_X);
    s_raw_x = (uint16_t)((a + b) / 2u);
    a = tp_xfer(TP_CMD_Y); b = tp_xfer(TP_CMD_Y);
    s_raw_y = (uint16_t)((a + b) / 2u);

    if (s_raw_x == 0u || s_raw_x == 0x0FFFu || s_raw_y == 0u || s_raw_y == 0x0FFFu) {
        s_read_bad++;                   /* PEN 有反应但 ADC 全 0/全 1 -> 引脚或时序不对 */
        return 0;
    }
    s_read_ok++;

#if TP_SWAP_XY
    *x = (uint16_t)map_axis(s_raw_y, TP_W, TP_INV_X);
    *y = (uint16_t)map_axis(s_raw_x, TP_H, TP_INV_Y);
#else
    *x = (uint16_t)map_axis(s_raw_x, TP_W, TP_INV_X);
    *y = (uint16_t)map_axis(s_raw_y, TP_H, TP_INV_Y);
#endif
    return 1;
}
