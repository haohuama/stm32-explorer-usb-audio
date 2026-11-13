#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 lcd_ui.c 的标题栏/空歌词提示从 ASCII 改成中文（配合 LCD_KEEP_ASCII_FONT=0）。"""
import io

UI = r"C:/stm32TEST/User/Hardware/LCD/lcd_ui.c"


def esc(txt):
    return "".join("\\x%02X" % b for b in txt.encode("gbk"))


def main():
    s = open(UI, encoding="utf-8", errors="ignore").read()

    title = esc("江南 林俊杰")
    nolyr = esc("无歌词")

    old_frame = '''    /* 字号统一 16px：24px 字模占 3420B Flash，MDK-Lite 32KB 装不下 */
    lcd_show_string(12u, 18u, 300u, 16u, 16u, (char *)"Explorer F407", UI_COL_TITLE);
    lcd_show_string(12u, 40u, 320u, 16u, 16u, (char *)"MODE 1 : USB CDC", UI_COL_HINT);
    lcd_show_string(UI_W - 110u, 18u, 100u, 16u, 16u, (char *)"44.1k/16", UI_COL_TITLE);'''
    new_frame = '''    /* ASCII 字模已关闭（省 2.4KB Flash），标题用内置中文点阵绘制 */
    draw_gbk_string(16u, 22u, (const char *)"%s", UI_COL_TITLE);''' % title
    assert old_frame in s, "draw_frame 未匹配"
    s = s.replace(old_frame, new_frame)

    old_hint = '''        lcd_show_string(20u, UI_BAND_Y + 100u, 400u, 32u, 16u,
                        (char *)"NO LRC LOADED", UI_COL_HINT);'''
    new_hint = '''        draw_gbk_string(20u, UI_BAND_Y + 100u, (const char *)"%s", UI_COL_HINT);''' % nolyr
    assert old_hint in s, "NO LRC LOADED 未匹配"
    s = s.replace(old_hint, new_hint)

    # s_track 默认值改中文（lcd_ui_set_track 才会用到）
    s = s.replace('static char      s_track[64] = "USB CDC  music stream";',
                  'static char      s_track[64] = "";')

    open(UI, "w", encoding="utf-8", newline="").write(s)
    print("lcd_ui.c 已改：标题=%s / 空歌词=%s" % ("江南 林俊杰", "无歌词"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
