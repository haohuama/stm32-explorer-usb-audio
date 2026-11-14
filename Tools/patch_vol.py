#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本轮补丁：
   1) 软件音量（在 DMA refill 里做定点乘法）——音量键不再依赖 WM8978 的 I2C 写入
   2) 默认音量下调（治"炸"）
   3) 界面改成「左 1/3 图片 + 右 2/3 歌词」
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rep(path, pairs, label):
    p = os.path.join(ROOT, path)
    s = open(p, encoding="utf-8").read()
    hit = 0
    for old, new in pairs:
        if old in s:
            s = s.replace(old, new, 1)
            hit += 1
        else:
            print("  !! 未匹配(%s): %r" % (label, old[:50]))
    if hit:
        open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("%s: %d/%d 处已改" % (path, hit, len(pairs)))


# ---------------- 1) 软件音量 ----------------
rep("User/Hardware/AUDIO/i2s_audio.h", [
    ("uint32_t audio_stream_position_ms(void);",
     "uint32_t audio_stream_position_ms(void);\n\n"
     "/* 软件音量（0~63，DMA refill 里定点乘法，不依赖 CODEC 的 I2C）。\n"
     " * 与 WM8978 的 SPK 音量是两级串联：这里管数字，那里管模拟。 */\n"
     "void audio_stream_set_volume(uint8_t vol);\n"
     "uint8_t audio_stream_volume(void);"),
], "h")

rep("User/Hardware/AUDIO/i2s_audio.c", [
    ("static volatile uint32_t s_pos_bytes  = 0;    /* 真实 PCM 累计字节（歌词时间轴） */",
     "static volatile uint32_t s_pos_bytes  = 0;    /* 真实 PCM 累计字节（歌词时间轴） */\n"
     "/* 软件音量：Q8 定点（256 = 0dB）。默认 0xB0≈0.69，先给功放留余量，治\"炸\"。 */\n"
     "static volatile uint16_t s_sw_gain    = 0xB0u;\n"
     "static volatile uint8_t  s_sw_vol     = 44u;"),
    ("""    for (i = 0; i < n; i++) {
        d[i] = s_ring[s_ring_r];
        s_ring_r = (s_ring_r + 1u) & AUDIO_RING_MASK;
    }""",
     """    /* 软件音量：逐 16bit 样本做 (v*g)>>8。g=256 时就是直通，
     * 乘法只在有真实数据时跑（2048 样本/23ms ≈ 0.8% CPU），不影响时序。 */
    {
        uint16_t g = s_sw_gain;

        if (g == 256u) {
            for (i = 0; i < n; i++) {
                d[i] = s_ring[s_ring_r];
                s_ring_r = (s_ring_r + 1u) & AUDIO_RING_MASK;
            }
        } else {
            uint32_t k = 0;
            for (i = 0; i < n; i++) {
                d[i] = s_ring[s_ring_r];
                s_ring_r = (s_ring_r + 1u) & AUDIO_RING_MASK;
                k++;
                if (k == 2u) {                       /* 凑够一个 16bit 样本 */
                    int32_t v = (int16_t)((uint16_t)d[i - 1u] | ((uint16_t)d[i] << 8));
                    v = (v * (int32_t)g) >> 8;
                    if (v > 32767) v = 32767;
                    if (v < -32768) v = -32768;
                    d[i - 1u] = (uint8_t)((uint16_t)v & 0xFFu);
                    d[i]      = (uint8_t)(((uint16_t)v >> 8) & 0xFFu);
                    k = 0;
                }
            }
        }
    }"""),
    ("uint32_t audio_stream_position_ms(void)",
     """void audio_stream_set_volume(uint8_t vol)
{
    if (vol > 63u) vol = 63u;
    s_sw_vol  = vol;
    s_sw_gain = (uint16_t)((uint32_t)vol * 4u + 4u);   /* 0->4(静音附近) 63->256(0dB) */
}

uint8_t audio_stream_volume(void) { return s_sw_vol; }

uint32_t audio_stream_position_ms(void)"""),
], "c")

# ---------------- 2) main：音量键同时改软件音量 ----------------
rep("User/main.c", [
    ("""                WM8978_SPKvol_Set(vol);       /* 只动模拟增益，不碰数字链路 */
                lcd_ui_set_volume(vol);""",
     """                audio_stream_set_volume(vol);  /* 数字端（一定生效） */
                WM8978_SPKvol_Set(vol);        /* 模拟端（若 I2C 正常则再叠一层） */
                lcd_ui_set_volume(vol);"""),
    ("        uint8_t  vol = 0x30;", "        uint8_t  vol = 44u;      /* 默认 44/63：软件 0.69 + 模拟 -9dB，先不炸 */"),
    ("""    WM8978_SPKvol_Set(0x30);
    uart_puts("[3] PlayMode  : DAC 开 / 输入关 / 输出开 / SPK vol=0x30(clean)\\r\\n");""",
     """    WM8978_SPKvol_Set(44);
    audio_stream_set_volume(44);           /* 软件音量：44/63 ≈ 0.69，给功放留余量 */
    uart_puts("[3] PlayMode  : DAC 开 / 输入关 / 输出开 / vol=44/63(软+硬两级)\\r\\n");"""),
], "main")

print("done")
