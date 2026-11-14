# -*- coding: utf-8 -*-
"""patch_sync.py —— 歌词/音频严格同步 + 屏上切歌真的换歌

背景（两个真问题）：
1. 设备端歌词时间轴 = 收到的真实 PCM 字节数，本来与音频同源、天然同步；
   但桌面软件 seek / 换倍速后是「从 base_ms 开始的一段新 PCM」，设备时间轴
   仍从 0 起算 -> 歌词提前。需要新增 T_POS 帧把时间轴基准下发。
2. 屏上按键/触屏切歌只改了内置播放列表（封面/歌词），音频仍由电脑送原文件
   -> 「切到哪首歌词却不唱哪首」。新增 CDC 上行 2 字节命令 'S'+idx，
   电脑端据此跳到对应 WAV。
"""
import io
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def rw(rel, pairs):
    p = os.path.join(ROOT, rel)
    s = io.open(p, encoding="utf-8").read()
    for a, b in pairs:
        if a in s:
            s = s.replace(a, b, 1)
        else:
            print("!! 未找到 [%s]: %s" % (rel, a[:70].replace("\n", " | ")))
    io.open(p, "w", encoding="utf-8", newline="\n").write(s)
    print("已写", rel)


# ---------------------------------------------------------------- 1. 时间轴基准
rw("User/Hardware/AUDIO/i2s_audio.h", [
    ("void     audio_stream_reset_position(void);",
     "void     audio_stream_reset_position(void);\n"
     "/* 由上位机在 seek/倍速/切歌后下发的「歌词时间轴基准」（ms）。\n"
     " * 注意：这里传的是**已按倍速缩放过**的时间，和设备上那份 LRC 的时间戳同尺度。 */\n"
     "void     audio_stream_set_position(uint32_t ms);"),
])

rw("User/Hardware/AUDIO/i2s_audio.c", [
    ("void audio_stream_reset_position(void)\n"
     "{\n"
     "    s_pos_bytes = 0;\n"
     "}",
     "void audio_stream_reset_position(void)\n"
     "{\n"
     "    s_pos_bytes = 0;\n"
     "}\n\n"
     "void audio_stream_set_position(uint32_t ms)\n"
     "{\n"
     "    /* ms -> 字节：176400 B/s（44.1k * 2ch * 2B）。用 64 位避免溢出。 */\n"
     "    s_pos_bytes = (uint32_t)(((uint64_t)ms * (uint32_t)(AUDIO_SAMPLE_RATE * 4u)) / 1000u);\n"
     "    s_idle_cnt = 0;\n"
     "}"),
])

# ---------------------------------------------------------------- 2. T_POS 控制帧
rw("User/APP/cdc_ctrl.c", [
    ("#define T_COVER_ROW 0x04u",
     "#define T_COVER_ROW 0x04u\n"
     "#define T_POS       0x05u     /* 4 字节 LE 毫秒：歌词时间轴基准 */"),
    ("        case T_COVER_ROW: {",
     "        case T_POS: {\n"
     "            /* 上位机 seek / 换倍速 / 切歌后同步歌词时间轴，\n"
     "             * 传进来的是「已按倍速缩放」的时间，与下发 LRC 的时间戳同尺度。 */\n"
     "            if (len >= 4u) {\n"
     "                uint32_t ms = (uint32_t)p[0] | ((uint32_t)p[1] << 8) |\n"
     "                              ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);\n"
     "                audio_stream_set_position(ms);\n"
     "            }\n"
     "            break;\n"
     "        }\n"
     "        case T_COVER_ROW: {"),
])

rw("User/APP/cdc_ctrl.h", [
    (" *   type 0x04 COVER_ROW: row_lo, row_hi, 240×RGB565(小端)",
     " *   type 0x04 COVER_ROW: row_lo, row_hi, 240×RGB565(小端)\n"
     " *   type 0x05 POS       : 4 字节 LE 毫秒，设置歌词时间轴基准（seek/倍速/切歌后用）"),
])

# ---------------------------------------------------------------- 3. CDC 上行 2 字节命令
rw("Middlewares/USB/USB_APP/usbd_cdc_if.c", [
    ("int CDC_Cmd_Send(uint8_t c)\n"
     "{",
     "/* 2 字节上行命令：'S' + 曲目绝对索引(0 基)。\n"
     " * 屏上切歌时用，电脑端据此跳到对应 WAV，做到「切到哪首歌词就唱哪首」。 */\n"
     "int CDC_Cmd_Send2(uint8_t c, uint8_t d)\n"
     "{\n"
     "  if (s_cmd_busy || hUsbDeviceFS.pClass == NULL) return -1;\n"
     "  s_cmd_buf[0] = c;\n"
     "  s_cmd_buf[1] = d;\n"
     "  s_cmd_busy = 1;\n"
     "  if (USBD_CDC_SetTxBuffer(&hUsbDeviceFS, s_cmd_buf, 2) != USBD_OK)\n"
     "  {\n"
     "    s_cmd_busy = 0;\n"
     "    return -2;\n"
     "  }\n"
     "  if (USBD_CDC_TransmitPacket(&hUsbDeviceFS) != USBD_OK)\n"
     "  {\n"
     "    s_cmd_busy = 0;\n"
     "    return -3;\n"
     "  }\n"
     "  return 0;\n"
     "}\n\n"
     "int CDC_Cmd_Send(uint8_t c)\n"
     "{"),
])

rw("User/main.c", [
    ("extern int CDC_Cmd_Send(uint8_t c);",
     "extern int CDC_Cmd_Send(uint8_t c);\n"
     "extern int CDC_Cmd_Send2(uint8_t c, uint8_t d);   /* 'S'+idx：屏上切歌通知电脑换 WAV */"),
    # 实体键切歌
    ("                (void)CDC_Cmd_Send((ev == KEY_NEXT) ? (uint8_t)'N' : (uint8_t)'B');",
     "                (void)CDC_Cmd_Send2((uint8_t)'S', (uint8_t)nxt);"),
    # 触屏切歌
    ("                                (void)CDC_Cmd_Send((hit == 3u) ? (uint8_t)'N' : (uint8_t)'B');",
     "                                (void)CDC_Cmd_Send2((uint8_t)'S', (uint8_t)nxt);"),
])

print("固件同步补丁完成")
