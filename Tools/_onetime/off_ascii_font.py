#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性脚本：把 LCD 的 ASCII 字模及其绘制函数改为宏开关（默认关闭）。

背景：Keil MDK-Lite 32KB 限制。屏上只显示中文歌词，ASCII 字模
(asc2_1608, 95*16=1520B) 与 lcd_show_char/num/string 的代码无实际用途。

做法：
  1) lcd.h 增加 LCD_KEEP_ASCII_FONT（默认 0）
  2) lcd.c 把 #include "lcdfont.h" 与三个函数体包进 #if / #else 空实现
可逆：把宏改 1 即恢复原样。
"""
import re
import sys

LCD_H = r"C:/stm32TEST/User/Hardware/LCD/lcd.h"
LCD_C = r"C:/stm32TEST/User/Hardware/LCD/lcd.c"


def find_func_span(src, sig_regex):
    m = re.search(sig_regex, src)
    if not m:
        return None
    i = src.find("{", m.end() - 1)
    if i < 0:
        return None
    depth = 0
    j = i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return (m.start(), j + 1)
        j += 1
    return None


def main():
    # ---------- 1) lcd.h 增加开关 ----------
    h = open(LCD_H, encoding="utf-8", errors="ignore").read()
    if "LCD_KEEP_ASCII_FONT" not in h:
        anchor = "#define LCD_KEEP_ALL_IC   0\n#endif\n"
        if anchor not in h:
            print("lcd.h 锚点未找到"); return 1
        add = anchor + """
/* 关闭 ASCII 字模（asc2_1608, 95x16=1520B）及其绘制函数代码。
 * 本工程屏上只画中文歌词，ASCII 无用途；Keil MDK-Lite 只有 32KB。
 * 需要显示英文/数字时改为 1 即可恢复（lcd_show_char/num/string 同时回来）。 */
#ifndef LCD_KEEP_ASCII_FONT
#define LCD_KEEP_ASCII_FONT   0
#endif
"""
        h = h.replace(anchor, add, 1)
        open(LCD_H, "w", encoding="utf-8", newline="").write(h)
        print("lcd.h: LCD_KEEP_ASCII_FONT 已加入")

    # ---------- 2) lcd.c: include 包起来 ----------
    c = open(LCD_C, encoding="utf-8", errors="ignore").read()
    if '#if LCD_KEEP_ASCII_FONT\n#include "lcdfont.h"\n#endif' not in c:
        c = c.replace('#include "lcdfont.h"',
                      '#if LCD_KEEP_ASCII_FONT\n#include "lcdfont.h"\n#endif', 1)
        print('lcd.c: include "lcdfont.h" 已条件化')

    # ---------- 3) lcd.c: 三个函数包起来 ----------
    specs = [
        (r"void lcd_show_char\s*\([^)]*\)\s*\{", "lcd_show_char",
         "    (void)x; (void)y; (void)chr; (void)size; (void)mode; (void)color;"),
        (r"void lcd_show_num\s*\([^)]*\)\s*\{", "lcd_show_num",
         "    (void)x; (void)y; (void)num; (void)len; (void)size; (void)color;"),
        (r"void lcd_show_string\s*\([^)]*\)\s*\{", "lcd_show_string",
         "    (void)x; (void)y; (void)width; (void)height; (void)size; (void)p; (void)color;"),
    ]
    for sig, name, stub in specs:
        if ("#if LCD_KEEP_ASCII_FONT\n" + name) in c or ("/* ASCOFF " + name) in c:
            print(name, "已处理，跳过")
            continue
        span = find_func_span(c, sig)
        if not span:
            print("未找到函数:", name); continue
        a, b = span
        body = c[a:b]
        # 函数签名后紧跟 {，把 { 之后插入 #if，把最后 } 换成 #else stub #endif }
        brace = body.find("{")
        new = (body[:brace + 1] +
               "\n#if LCD_KEEP_ASCII_FONT\n" +
               body[brace + 1:-1] +
               "#else  /* ASCOFF %s */\n%s\n#endif\n}" % (name, stub))
        c = c[:a] + new + c[b:]
        print(name, "已条件化")

    open(LCD_C, "w", encoding="utf-8", newline="").write(c)
    print("lcd.c 写入完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
