#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""第二轮精简：去掉底部时间/进度条 footer，并停用 ST7789 控制器分支。

目标：给 Keil 的 startup_stm32f407xx.s（约 600B）留出余量，
使 Local ROM total <= 32200，最终 Keil 链接 <= 32768。
"""
import re

# ---------- 1) lcd_ui.c: 删除 draw_footer 相关 ----------
p = r"C:/stm32TEST/User/Hardware/LCD/lcd_ui.c"
s = open(p, "r", encoding="utf-8", errors="ignore").read()

# 删掉 draw_footer 函数定义（整段）
pat_fn = re.compile(
    r"/\* 底部信息：曲目 \+ 时间 \+ 进度条 \*/\nstatic void draw_footer\(.*?\n\}\n",
    re.S)
if pat_fn.search(s):
    s = pat_fn.sub("", s, count=1)
    print("draw_footer removed")
else:
    print("draw_footer pattern NOT found")

# draw_frame 里底部进度条背景那一行去掉
s = re.sub(r"\n\s*/\* 底部进度条背景 \*/\n\s*lcd_fill\(20u?, UI_FOOTER_Y[^\n]*\n",
           "\n", s)

# lcd_ui_tick 里的 draw_footer 调用去掉
s = re.sub(r"\n\s*draw_footer\([^\n]*\n", "\n", s)

# sys 里 s_last_ms_shown 不再使用 -> 去掉声明与其初始化/使用
s = s.replace("static uint32_t  s_last_ms_shown = 0xFFFFFFFFu;\n", "")
s = s.replace("    s_last_ms_shown = 0xFFFFFFFFu;\n", "")

open(p, "w", encoding="utf-8", newline="").write(s)
print("lcd_ui.c patched")

# ---------- 2) lcd_ex.c: ST7789 也纳入开关 ----------
p2 = r"C:/stm32TEST/User/Hardware/LCD/lcd_ex.c"
s2 = open(p2, "r", encoding="utf-8", errors="ignore").read()
m = re.search(r"void lcd_ex_st7789_reginit\(void\)\s*\{", s2)
if m and "#if !LCD_KEEP_ALL_IC" not in s2[max(0, m.start() - 120):m.start()]:
    start = m.start()
    i = s2.find("{", m.end() - 1)
    depth = 0
    j = i
    while j < len(s2):
        if s2[j] == "{":
            depth += 1
        elif s2[j] == "}":
            depth -= 1
            if depth == 0:
                break
        j += 1
    s2 = s2[:start] + "#if !LCD_KEEP_ALL_IC\n" + s2[start:j + 1] + "\n#endif\n" + s2[j + 1:]
    open(p2, "w", encoding="utf-8", newline="").write(s2)
    print("st7789 disabled")

# ---------- 3) lcd.c: ST7789 分支加宏 ----------
p3 = r"C:/stm32TEST/User/Hardware/LCD/lcd.c"
s3 = open(p3, "r", encoding="utf-8", errors="ignore").read()
old = """    if (lcddev.id == 0x7789)
    {
        lcd_ex_st7789_reginit();    /* 执行ST7789初始化 */
    }
    else if (lcddev.id == 0x9341)"""
new = """#if LCD_KEEP_ALL_IC
    if (lcddev.id == 0x7789)
    {
        lcd_ex_st7789_reginit();    /* 执行ST7789初始化 */
    }
    else
#endif
    if (lcddev.id == 0x9341)"""
if old in s3:
    s3 = s3.replace(old, new, 1)
    print("lcd.c: st7789 branch wrapped")
else:
    print("lcd.c: st7789 branch pattern NOT found")

open(p3, "w", encoding="utf-8", newline="").write(s3)
print("done")
