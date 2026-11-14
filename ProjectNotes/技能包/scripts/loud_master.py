#!/usr/bin/env python3
# 两遍法 loudnorm：把任意音频做成"响度最大化、真峰值不削波"的 44.1k/16bit/立体声 WAV。
# 用法: python loud_master.py <输入音频(mp3/wav)> <输出wav> [目标LUFS，默认-8]
import subprocess, json, re, sys, os
import imageio_ffmpeg

ff = imageio_ffmpeg.get_ffmpeg_exe()
src = sys.argv[1]
out = sys.argv[2]
I = float(sys.argv[3]) if len(sys.argv) > 3 else -8.0
TP, LRA = -1.5, 9.0
raw = out + ".raw.tmp.wav"

# 1) 先统一成 44.1k/16bit/立体声（同时丢掉 MP3 头/编码）
subprocess.run([ff, "-y", "-loglevel", "error", "-i", src,
                "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", raw], check=True)

# 2) 第一遍：测量
p = subprocess.run([ff, "-hide_banner", "-i", raw, "-af",
                    f"loudnorm=I={I}:TP={TP}:LRA={LRA}:print_format=json",
                    "-f", "null", "-"], capture_output=True, text=True)
m = json.loads(re.search(r"\{[\s\S]*\}", p.stderr).group(0))

# 3) 第二遍：用测量值精确施加（linear=true 尽量线性、少泵动）
subprocess.run([ff, "-y", "-loglevel", "error", "-i", raw, "-af",
                (f"loudnorm=I={I}:TP={TP}:LRA={LRA}"
                 f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                 f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                 f":offset={m['target_offset']}"),
                "-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le", out], check=True)
os.remove(raw)
print("done:", out, " target_lufs=", I)
print("measured: input_I=%s input_TP=%s input_LRA=%s" % (m['input_i'], m['input_tp'], m['input_lra']))
