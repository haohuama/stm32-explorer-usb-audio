# -*- coding: utf-8 -*-
"""patch_volume.py —— 音量刻度 0~63 改成 0~100（101 档，每次 ±1）"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def edit(rel, pairs):
    p = os.path.join(ROOT, rel)
    s = io.open(p, encoding="utf-8").read()
    for a, b in pairs:
        if a in s:
            s = s.replace(a, b, 1)
        else:
            print("!! 未找到 [%s]: %s" % (rel, a[:60].replace("\n", "|")))
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("已写", rel)


edit("User/Hardware/AUDIO/i2s_audio.c", [
    ("static volatile uint16_t s_sw_gain    = 0x64u;   /* 24/63 -> 0.39x，默认别太吵 */",
     "static volatile uint16_t s_sw_gain    = 0x61u;   /* 38/100 -> 0.38x，默认别太吵 */"),
    ("static volatile uint8_t  s_sw_vol     = 24u;",
     "static volatile uint8_t  s_sw_vol     = 38u;"),
    ("    if (vol > 63u) vol = 63u;\n"
     "    s_sw_vol  = vol;\n"
     "    s_sw_gain = (uint16_t)((uint32_t)vol * 4u + 4u);   /* 0->4(静音附近) 63->256(0dB) */",
     "    if (vol > 100u) vol = 100u;\n"
     "    s_sw_vol  = vol;\n"
     "    /* 0~100 线性映射到 Q8 增益 0..256：0=静音，100=0dB 直通。\n"
     "     * 之前是 0~63、每次 ±4（只有 16 档），现在 101 档、每次 ±1。 */\n"
     "    s_sw_gain = (uint16_t)(((uint32_t)vol * 256u) / 100u);"),
])

edit("User/Hardware/LCD/lcd_ui.c", [
    ("static uint8_t    s_volume = 24u;   /* 与 i2s_audio.c 默认一致 */",
     "static uint8_t    s_volume = 38u;   /* 与 i2s_audio.c 默认一致，量程 0~100 */"),
    ("    if (vol > 63u) vol = 63u;", "    if (vol > 100u) vol = 100u;"),
])

edit("User/main.c", [
    ("audio_stream_set_volume(24);  /* 数字音量默认 24/63≈0.39x，音量键只改这个 */",
     "audio_stream_set_volume(38);  /* 数字音量默认 38/100≈0.38x，音量键只改这个 */"),
    ("模拟固定0x30 + 数字24", "模拟固定0x30 + 数字38/100"),
    ("uint8_t  vol = 24u;      /* 默认 24/63：软件 0.39x，开机偏轻；WK_UP 加、KEY1 减 */",
     "uint8_t  vol = 38u;      /* 0~100 共 101 档，默认 38；WK_UP 加、KEY1 减 */"),
    ("                    vol = (uint8_t)((vol + 4u > 63u) ? 63u : vol + 4u);\n"
     "                } else {\n"
     "                    vol = (uint8_t)((vol < 4u) ? 0u : vol - 4u);",
     "                    vol = (uint8_t)((vol >= 100u) ? 100u : vol + 1u);\n"
     "                } else {\n"
     "                    vol = (uint8_t)((vol == 0u) ? 0u : vol - 1u);"),
    ('uart_puts("/63\\r\\n");', 'uart_puts("/100\\r\\n");'),
])

edit("User/Hardware/KEY/key.c", [
    ("#define REPEAT_PERIOD 150u      /* ms，重复间隔 */",
     "#define REPEAT_PERIOD 60u       /* ms，重复间隔（0~100 档，连发要快一点） */"),
])

print("音量 0~100 改造完成")
