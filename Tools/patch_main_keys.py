#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""main.c 接入 KEY_PLAY：按键 → CDC 上行命令 → 电脑端暂停/继续/切歌。"""
import os
import sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "User/main.c")


def main():
    s = open(P, encoding="utf-8").read()
    if "KEY_PLAY" in s:
        print("已打过补丁，跳过")
        return 0
    orig = s

    # 1) 声明
    s = s.replace('#include "cdc_ctrl.h"          /* USB 下行控制帧：歌词/封面 */',
                  '#include "cdc_ctrl.h"          /* USB 下行控制帧：歌词/封面 */\n'
                  '\n'
                  '/* usbd_cdc_if.c：给上位机发 1 字节命令（P 暂停 / R 继续 / N 下一首 / B 重播） */\n'
                  'extern int CDC_Cmd_Send(uint8_t c);')

    # 2) 循环里 KEY_PLAY + 切歌时通知电脑
    s = s.replace(
        '            } else if (ev == KEY_NEXT || ev == KEY_PREV) {',
        '            } else if (ev == KEY_PLAY) {\n'
        '                paused = (uint8_t)!paused;\n'
        '                (void)CDC_Cmd_Send(paused ? (uint8_t)\'P\' : (uint8_t)\'R\');\n'
        '                lcd_ui_set_paused(paused);\n'
        '                uart_puts(paused ? "[KEY] PAUSE -> 已通知电脑暂停\\r\\n"\n'
        '                                : "[KEY] PLAY  -> 已通知电脑继续\\r\\n");\n'
        '            } else if (ev == KEY_NEXT || ev == KEY_PREV) {', 1)

    s = s.replace(
        '                lcd_ui_set_meta("", "");        /* 按键切曲：回到内置歌名/歌手 */',
        '                (void)CDC_Cmd_Send((ev == KEY_NEXT) ? (uint8_t)\'N\' : (uint8_t)\'B\');\n'
        '                lcd_ui_set_meta("", "");        /* 按键切曲：回到内置歌名/歌手 */', 1)

    # 3) paused 变量
    s = s.replace('        uint8_t  vol = 0x30;',
                  '        uint8_t  vol = 0x30;\n'
                  '        uint8_t  paused = 0;', 1)

    # 4) 开机提示补一行
    s = s.replace('    uart_puts("[7] KEY       : KEY0=下一首 KEY1=上一首 WK_UP=音量+ KEY2=音量-\\r\\n");',
                  '    uart_puts("[7] KEY       : KEY0短按=下一首 / KEY0长按=播放暂停 / KEY1=上一首\\r\\n");\n'
                  '    uart_puts("              : WK_UP=音量+ / KEY2=音量-  (暂停需电脑端 --keys 在监听)\\r\\n");')

    if s == orig:
        print("没有匹配到锚点")
        return 1
    open(P, "w", encoding="utf-8", newline="\n").write(s)
    print("已写入", P)
    return 0


if __name__ == "__main__":
    sys.exit(main())
