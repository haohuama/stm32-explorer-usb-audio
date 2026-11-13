#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一次性补丁：把播放列表从 3 首扩到 4 首，并把选曲信号改为 SET_LINE_CODING 的波特率字段。

选曲协议（占用 0 字节音频带宽，纯 USB 控制请求）：
    ser.baudrate = 100000 + idx      # idx = 0..N-1
设备端 CDC_Control_FS 收到 CDC_SET_LINE_CODING(0x20) 时读 dwDwellTime(前 4 字节 LE)，
落在 [100000, 100000+16) 区间就当作"切到第 (baud-100000) 首"。
原来的 DTR/RTS 两位仍保留，作为 0/1 两首的兼容通道。
"""
import io
import os
import re

ROOT = r"C:/stm32TEST"


def rd(p):
    return open(p, "r", encoding="utf-8", errors="ignore", newline="").read()


def wr(p, s):
    open(p, "w", encoding="utf-8", newline="").write(s)


def patch_playlist():
    p = os.path.join(ROOT, "Tools/lrc_playlist.py")
    s = rd(p)
    s = s.replace("MAX_SONGS = 3          # 与 lcd_ui.c 的 SONG_COUNT 对应",
                  "MAX_SONGS = 4          # 与 lcd_ui.c 的 SONG_COUNT 对应")
    s = s.replace('print("最多 %d 首（lcd_ui.c 只定义了 SONG1_MS/SONG2_MS）" % MAX_SONGS)',
                  'print("最多 %d 首（与 lcd_ui.c 的 SONG_COUNT 一致）" % MAX_SONGS)')
    wr(p, s)
    print("[1/4] lrc_playlist.py: MAX_SONGS=4")


def patch_lcd_ui():
    p = os.path.join(ROOT, "User/Hardware/LCD/lcd_ui.c")
    s = rd(p)
    s = s.replace('#include "lrc_data.h"         /* s_lrc1..3 / s_title1..3（自动生成） */',
                  '#include "lrc_data.h"         /* s_lrc1..4 / s_title1..4（自动生成） */')
    s = s.replace("#define SONG_COUNT           3u        /* 与 Tools/lrc_playlist.py 的 MAX_SONGS 一致 */",
                  "#define SONG_COUNT           4u        /* 与 Tools/lrc_playlist.py 的 MAX_SONGS 一致 */")
    s = s.replace("static const char *const s_lrcs[SONG_COUNT]   = { s_lrc1, s_lrc2, s_lrc3 };",
                  "static const char *const s_lrcs[SONG_COUNT]   = { s_lrc1, s_lrc2, s_lrc3, s_lrc4 };")
    s = s.replace("static const char *const s_titles[SONG_COUNT] = { s_title1, s_title2, s_title3 };",
                  "static const char *const s_titles[SONG_COUNT] = { s_title1, s_title2, s_title3, s_title4 };")
    wr(p, s)
    print("[2/4] lcd_ui.c: SONG_COUNT=4 + 4 首表项")


def patch_cdc_if():
    p = os.path.join(ROOT, "Middlewares/USB/USB_APP/usbd_cdc_if.c")
    s = rd(p)
    old = """    case CDC_SET_CONTROL_LINE_STATE:"""
    new = """    case CDC_SET_LINE_CODING:
      /* 选曲（可扩展）：上位机把 ser.baudrate 设成 100000+idx，
       * 驱动会发 CDC_SET_LINE_CODING(0x20, 7 字节)，前 4 字节 LE = baudrate。
       * 只有落在 [100000,100000+16) 才认，是正常配置时一律忽略。 */
      if (pbuf != NULL && length >= 4u) {
        uint32_t baud = (uint32_t)pbuf[0]
                      | ((uint32_t)pbuf[1] << 8)
                      | ((uint32_t)pbuf[2] << 16)
                      | ((uint32_t)pbuf[3] << 24);
        if (baud >= 100000u && baud < (100000u + 16u)) {
          lcd_ui_select_song((uint8_t)(baud - 100000u));
        }
      }
      break;

    case CDC_SET_CONTROL_LINE_STATE:"""
    assert old in s
    s = s.replace(old, new, 1)
    # 控制线注释更新：现在只是 0/1 两首的兼容通道
    s = s.replace("""       * 约定：0 = 第 1 首，1 = 第 2 首，2/3（端口刚打开时的默认态）忽略。 */""",
                  """       * 这里只作 0/1 两首的兼容通道（2/3 是端口刚打开时的默认态，忽略）；
       * 3 首以上靠上面的 SET_LINE_CODING 波特率编码，DTR/RTS 位数不够。 */""")
    wr(p, s)
    print("[3/4] usbd_cdc_if.c: 支持 SET_LINE_CODING 选曲")


def patch_sender():
    p = os.path.join(ROOT, "Tools/host_cdc_sender.py")
    s = rd(p)
    old = """    try:
        # 先设 RTS(bit1) 再设 DTR(bit0)，把中间态控制在我们想要的值
        ser.rts = bool(idx & 2)
        ser.dtr = bool(idx & 1)
    except Exception:
        pass"""
    new = """    try:
        # 主通道：把波特率设成 100000+idx（触发 CDC_SET_LINE_CODING，0 字节音频开销）。
        # 这是可扩展的，任意首数都行。
        ser.baudrate = 100000 + idx
    except Exception:
        pass
    try:
        # 兼容通道：0/1 两首用 DTR/RTS 表达（老固件也能正确切曲）
        ser.rts = bool(idx & 2)
        ser.dtr = bool(idx & 1)
    except Exception:
        pass"""
    assert old in s, "sender 选曲块未找到"
    s = s.replace(old, new)
    wr(p, s)
    print("[4/4] host_cdc_sender.py: 波特率编码选曲")


if __name__ == "__main__":
    patch_playlist()
    patch_lcd_ui()
    patch_cdc_if()
    patch_sender()
    print("补丁完成")
