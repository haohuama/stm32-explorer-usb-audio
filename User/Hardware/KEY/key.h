/* ============================================================
 * key.h —— 板载 4 个实体按键（正点原子 探索者 F407）
 *
 * 引脚（老版 V2.7 官方例程口径，与 FSMC 屏不冲突）：
 *   KEY0  = PE4   （低电平有效，内部上拉）
 *   KEY1  = PE3   （低电平有效）
 *   KEY2  = PE2   （低电平有效）
 *   WK_UP = PA0   （**高电平有效**，必须配置成内部下拉）
 *
 * 映射（key.c 顶部 4 个 MAP_KEYx 宏可改）：
 *   KEY0 = 下一首    KEY2 = 上一首    KEY1 = 音量-    WK_UP = 音量+
 *   播放/暂停只在屏幕触屏按钮上，不占实体键。
 *
 * 用法：主循环每 10ms 调一次 key_scan()，非 0 即一次按键事件
 *      （长按音量键会自动重复）。全部在 main 上下文，不进中断。
 * ============================================================ */
#ifndef __KEY_H
#define __KEY_H

#include <stdint.h>

typedef enum {
    KEY_NONE = 0,
    KEY_NEXT,        /* 下一首（KEY0） */
    KEY_PREV,        /* 上一首（KEY2） */
    KEY_VOL_UP,      /* 音量 +（WK_UP） */
    KEY_VOL_DN,      /* 音量 -（KEY1） */
    KEY_PLAY         /* 保留：现在只有触屏按钮会触发播放/暂停 */
} key_evt_t;

void      key_init(void);
key_evt_t key_scan(void);      /* 10ms 周期调用 */

/* 当前 4 个键的原始电平位图（bit0..3 = KEY0,KEY1,KEY2,WK_UP），开机自检用 */
uint8_t   key_raw_bits(void);

#endif /* __KEY_H */
