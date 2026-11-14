# -*- coding: utf-8 -*-
"""patch_touch_diag.py —— 给触屏加自检统计与串口诊断，定位「按了没反应」"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rw(rel, fn):
    p = os.path.join(ROOT, rel)
    s = io.open(p, encoding="utf-8").read()
    s2 = fn(s)
    io.open(p, "w", encoding="utf-8", newline="\n").write(s2)
    print("已写", rel)


# ---------------------------------------------------------------- tp.h
def h(s):
    a = "uint8_t tp_pen_level(void);"
    b = a + "\n\n/* 诊断计数：PEN 检测到按下的次数 / 成功读到坐标 / ADC 无效丢弃。\n * 每 3 秒由主循环打印一次，用来判断是哪一层断了：\n *   pen=0            -> PEN 引脚没接 / 有效电平反了 / 屏不是这块触摸\n *   pen>0, ok=0      -> SPI 位操作没读到数据（MISO/MOSI/SCK/CS 引脚不对）\n *   pen>0, ok>0      -> 驱动正常，只是坐标校准不对（改 tp.c 顶部 4 个宏） */\nvoid tp_stats(uint32_t *pen, uint32_t *ok, uint32_t *bad);"
    assert a in s
    return s.replace(a, b, 1)


rw("User/Hardware/TOUCH/tp.h", h)


# ---------------------------------------------------------------- tp.c
def c(s):
    a = "static uint16_t s_raw_x, s_raw_y;"
    b = (a + "\n\n/* 触摸诊断计数（见 tp.h 说明） */\n"
         "static uint32_t s_pen_seen = 0, s_read_ok = 0, s_read_bad = 0;")
    assert a in s
    s = s.replace(a, b, 1)

    a = """uint8_t tp_pen_level(void)
{
    return (TPEN() == GPIO_PIN_SET) ? 1u : 0u;
}"""
    b = a + """

void tp_stats(uint32_t *pen, uint32_t *ok, uint32_t *bad)
{
    if (pen) *pen = s_pen_seen;
    if (ok)  *ok  = s_read_ok;
    if (bad) *bad = s_read_bad;
}"""
    assert a in s
    s = s.replace(a, b, 1)

    # PEN 检测到按下就计数
    a = """    if (TPEN() != GPIO_PIN_RESET) {     /* 没按下 */
        down_cnt = 0;
        return 0;
    }
    if (down_cnt < 2u) {                /* 去抖：连续两次才算 */"""
    b = """    if (TPEN() != GPIO_PIN_RESET) {     /* 没按下 */
        down_cnt = 0;
        return 0;
    }
    s_pen_seen++;                       /* 诊断：PEN 确实被拉低过 */
    if (down_cnt < 2u) {                /* 去抖：连续两次才算 */"""
    assert a in s
    s = s.replace(a, b, 1)

    a = """    if (s_raw_x == 0u || s_raw_x == 0x0FFFu || s_raw_y == 0u || s_raw_y == 0x0FFFu) {
        return 0;                       /* 明显无效，别乱点 */
    }"""
    b = """    if (s_raw_x == 0u || s_raw_x == 0x0FFFu || s_raw_y == 0u || s_raw_y == 0x0FFFu) {
        s_read_bad++;                   /* PEN 有反应但 ADC 全 0/全 1 -> 引脚或时序不对 */
        return 0;
    }
    s_read_ok++;"""
    assert a in s
    return s.replace(a, b, 1)


rw("User/Hardware/TOUCH/tp.c", c)


# ---------------------------------------------------------------- main.c
def m(s):
    # 开机打印 PEN 空闲电平
    a = 'uart_puts("[7] TOUCH     : XPT2046  T_PEN=PB1 T_CS=PC13 T_MISO=PB2 T_MOSI=PF11 T_SCK=PB0\\r\\n");'
    b = a + """
    uart_puts("[7] TP PEN    : 空闲电平=");
    uart_put_u8(tp_pen_level());
    uart_puts(" (1=高/未按, 0=低)  按屏幕会打印 [TP] x= y=\\r\\n");"""
    assert a in s
    s = s.replace(a, b, 1)

    # 触摸按下时打印坐标 + raw
    a = """                if (tp_scan(&tx, &ty) && (uint32_t)(HAL_GetTick() - last_tp) >= 350u) {
                    uint8_t hit = lcd_ui_hit(tx, ty);"""
    b = """                if (tp_scan(&tx, &ty)) {
                    /* 诊断：只要读到一次有效坐标就打印，方便判断校准/引脚 */
                    static uint32_t last_pr = 0;
                    if ((uint32_t)(HAL_GetTick() - last_pr) >= 250u) {
                        uint16_t rx = 0, ry = 0;
                        last_pr = HAL_GetTick();
                        tp_last_raw(&rx, &ry);
                        uart_puts("[TP] x="); uart_put_u32(tx);
                        uart_puts(" y=");    uart_put_u32(ty);
                        uart_puts(" raw=");  uart_put_u32(rx);
                        uart_puts(",");      uart_put_u32(ry);
                        uart_puts("\\r\\n");
                    }
                }
                if (tp_scan_ok_last && (uint32_t)(HAL_GetTick() - last_tp) >= 350u) {
                    uint8_t hit = lcd_ui_hit(tx, ty);"""
    # 上面这种写法需要额外状态，改成更简单的：把诊断塞进 tp_scan 成功的分支里
    b = """                if (tp_scan(&tx, &ty)) {
                    static uint32_t last_pr = 0;
                    if ((uint32_t)(HAL_GetTick() - last_pr) >= 250u) {
                        uint16_t rx = 0, ry = 0;
                        last_pr = HAL_GetTick();
                        tp_last_raw(&rx, &ry);
                        uart_puts("[TP] x="); uart_put_u32(tx);
                        uart_puts(" y=");    uart_put_u32(ty);
                        uart_puts(" raw=");  uart_put_u32(rx);
                        uart_puts(",");      uart_put_u32(ry);
                        uart_puts("\\r\\n");
                    }
                    if ((uint32_t)(HAL_GetTick() - last_tp) >= 350u) {
                    uint8_t hit = lcd_ui_hit(tx, ty);"""
    assert a in s
    s = s.replace(a, b, 1)

    # 补上多出来的一层大括号：找到 hit 分支结束处
    a = """                    }
                }
            }

            cdc_ctrl_poll();"""
    b = """                    }
                    }
                }
            }

            cdc_ctrl_poll();"""
    assert a in s, "找不到触摸块的收尾"
    s = s.replace(a, b, 1)

    # 每 3 秒打印触摸统计
    a = """                uart_puts("... USB CDC running, ring=");
                uart_put_u32(audio_stream_available());
                uart_puts(" bytes\\r\\n");"""
    b = a + """
                {
                    uint32_t pen = 0, ok = 0, bad = 0;
                    tp_stats(&pen, &ok, &bad);
                    uart_puts("      TP: pen="); uart_put_u32(pen);
                    uart_puts(" ok=");  uart_put_u32(ok);
                    uart_puts(" bad="); uart_put_u32(bad);
                    uart_puts("\\r\\n");
                }"""
    assert a in s
    return s.replace(a, b, 1)


rw("User/main.c", m)
print("触屏诊断补丁完成")
