/* ============================================================
 * key.c —— 4 个实体按键：消抖 + 单次触发 + 长按重复
 *
 * 为什么不去中断里做：按键只改 UI/音量，放主循环 10ms 轮询最省事，
 * 也不会跟 USB/I2S 中断抢时间（本项目贯穿原则：UI 不进中断）。
 *
 * 消抖：连续 2 次采样（≥10ms）一致才认；抬起也走同一套。
 * 长按：音量键按住 700ms 后，每 150ms 重复一次。
 *
 * ⚠️ 2026-11-14 修的两个问题：
 *   1) WK_UP 是**高电平有效**（PA0 接按键到 3.3V，板上只有弱下拉/无下拉）。
 *      原来配成 GPIO_PULLUP，内部上拉把 PA0 拉高 → 一上电就被当成「一直按着」，
 *      音量每 150ms 加一次，几秒顶到 63；此时按音量减马上又被加回去，
 *      现象就是「两个音量键都没反应」。→ WK_UP 改成 GPIO_PULLDOWN。
 *   2) KEY0 长按曾被我借去做「播放/暂停」，导致短按切歌要等松手、
 *      稍按久一点就变成暂停。现在屏幕上有 ▶/⏸ 按钮了，长按逻辑整段删掉，
 *      KEY0 恢复成纯粹的「下一首」。
 *   另外加了「先松手才认」的保险：某个键上电就是按下态（接触不良/被压住）时，
 *   它必须先读到一次抬起，之后才会产生事件，避免它把音量顶死。
 * ============================================================ */
#include "key.h"
#include "stm32f4xx_hal.h"

/* ---------------- 引脚定义（换板/换键位只改这里） ---------------- */
#define KEY0_PORT     GPIOE
#define KEY0_PIN      GPIO_PIN_4
#define KEY1_PORT     GPIOE
#define KEY1_PIN      GPIO_PIN_3
#define KEY2_PORT     GPIOE
#define KEY2_PIN      GPIO_PIN_2
#define WKUP_PORT     GPIOA
#define WKUP_PIN      GPIO_PIN_0

/* ---------------- 功能映射（觉得上下/左右反了就换这四行） ----------------
 * 用户指定(2026-11-14)：
 *   KEY0 = 下一首   KEY2 = 上一首   KEY1 = 音量-   WK_UP = 音量+
 * 播放/暂停只在屏幕按钮上（触屏），不再占用实体键。
 */
#define MAP_KEY0      KEY_NEXT
#define MAP_KEY1      KEY_VOL_DN
#define MAP_WKUP      KEY_VOL_UP
#define MAP_KEY2      KEY_PREV

#define KEY_NUM       4u
#define DEBOUNCE_N    2u        /* 连续一致次数 */
#define REPEAT_DELAY  700u      /* ms，长按多久开始重复（只有音量键） */
#define REPEAT_PERIOD 60u       /* ms，重复间隔（0~100 档，连发要快一点） */

typedef struct {
    uint8_t  stable;            /* 消抖后的按下状态 */
    uint8_t  cnt;               /* 抖动计数 */
    uint8_t  armed;             /* 已读到过一次抬起，才允许产生事件 */
    uint16_t hold_ms;           /* 按下持续时长 */
    uint16_t next_rep;          /* 下一次重复的时长阈值 */
} key_state_t;

static key_state_t s_key[KEY_NUM];

/* 读一次物理电平，返回「是否按下」位图：bit0..3 = KEY0,KEY1,KEY2,WK_UP */
static uint8_t key_read_raw(void)
{
    uint8_t m = 0;

    if (HAL_GPIO_ReadPin(KEY0_PORT, KEY0_PIN) == GPIO_PIN_RESET) m |= 0x01;  /* 低有效 */
    if (HAL_GPIO_ReadPin(KEY1_PORT, KEY1_PIN) == GPIO_PIN_RESET) m |= 0x02;
    if (HAL_GPIO_ReadPin(KEY2_PORT, KEY2_PIN) == GPIO_PIN_RESET) m |= 0x04;
    if (HAL_GPIO_ReadPin(WKUP_PORT, WKUP_PIN) == GPIO_PIN_SET)    m |= 0x08;  /* 高有效 */
    return m;
}

/* 给开机自检/串口打印用：当前 4 个键的原始电平位图 */
uint8_t key_raw_bits(void)
{
    return key_read_raw();
}

void key_init(void)
{
    GPIO_InitTypeDef g = {0};

    __HAL_RCC_GPIOA_CLK_ENABLE();
    __HAL_RCC_GPIOE_CLK_ENABLE();

    g.Mode  = GPIO_MODE_INPUT;
    g.Speed = GPIO_SPEED_FREQ_LOW;

    /* KEY0/1/2 低有效 → 内部上拉（松开=高） */
    g.Pull = GPIO_PULLUP;
    g.Pin  = KEY1_PIN | KEY2_PIN | KEY0_PIN;
    HAL_GPIO_Init(GPIOE, &g);

    /* WK_UP 高有效 → 必须下拉（松开=低）。配成上拉会把它拉成「永远按着」，
     * 表现就是音量被一直加到 63、两个音量键都像失灵。 */
    g.Pull = GPIO_PULLDOWN;
    g.Pin  = WKUP_PIN;
    HAL_GPIO_Init(GPIOA, &g);

    for (uint8_t i = 0; i < KEY_NUM; i++) {
        s_key[i].stable  = 0;
        s_key[i].cnt     = 0;
        s_key[i].armed   = 0;   /* 必须先读到抬起，见文件头说明 */
        s_key[i].hold_ms = 0;
        s_key[i].next_rep = REPEAT_DELAY;
    }
}

/* 位图 bit -> 事件 */
static key_evt_t map_event(uint8_t bit)
{
    switch (bit) {
        case 0:  return MAP_KEY0;
        case 1:  return MAP_KEY1;
        case 2:  return MAP_KEY2;
        default: return MAP_WKUP;
    }
}

/* 该键是否允许长按重复（只有音量键） */
static uint8_t map_repeatable(uint8_t bit)
{
    key_evt_t e = map_event(bit);
    return (e == KEY_VOL_UP || e == KEY_VOL_DN) ? 1u : 0u;
}

key_evt_t key_scan(void)
{
    uint8_t  raw = key_read_raw();
    key_evt_t evt = KEY_NONE;

    for (uint8_t i = 0; i < KEY_NUM; i++) {
        uint8_t down = (raw >> i) & 0x01u;
        key_state_t *k = &s_key[i];

        if (!down) k->armed = 1;          /* 见到抬起才「启用」这个键 */

        if (down != k->stable) {
            if (++k->cnt >= DEBOUNCE_N) {
                k->cnt = 0;
                k->stable = down;
                k->hold_ms = 0;
                k->next_rep = REPEAT_DELAY;
                if (down && k->armed && evt == KEY_NONE) evt = map_event(i);
            }
        } else {
            k->cnt = 0;
            if (!k->stable || !k->armed) continue;

            k->hold_ms = (uint16_t)(k->hold_ms + 10u);

            /* 音量键长按连发 */
            if (map_repeatable(i) && k->hold_ms >= k->next_rep) {
                k->next_rep = (uint16_t)(k->next_rep + REPEAT_PERIOD);
                if (evt == KEY_NONE) evt = map_event(i);
            }
        }
    }
    return evt;
}
