#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
与 Keil MDK(ARMCLANG V6) 尽可能一致的“本地体积验证”脚本。

为什么需要它：
  Keil MDK-Lite(未授权) 限制 image <= 32768 字节。改完代码若只在 Keil 里试，
  一轮 Rebuild 才发现超限，来回成本高。本脚本按 uvprojx 的文件清单，
  用同一套 armclang/armlink + 同一份 .sct 真实编译链接，直接报出 image 体积。

用法:
  python Tools/build_check.py            # 默认 -Oz，不启用 microLIB
  python Tools/build_check.py --microlib # 启用 microLIB（对应 Keil useUlib=1）
  python Tools/build_check.py -O1        # 换优化等级
"""
import os
import re
import subprocess
import sys
import glob

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEIL = r"C:/Keil_v5/ARM/ARMCLANG/Bin"
AC = os.path.join(KEIL, "armclang.exe")
LD = os.path.join(KEIL, "armlink.exe")
FE = os.path.join(KEIL, "fromelf.exe")
AS = os.path.join(KEIL, "armasm.exe")

UV = os.path.join(ROOT, "Projects/MDK-ARM/atk_f407.uvprojx")
SCT = os.path.join(ROOT, "Output/atk_f407.sct")
OUT = os.path.join(os.environ.get("TEMP", "."), "bk_" + str(os.getpid()))

INCLUDES = [
    "Drivers/STM32F4xx_HAL_Driver/Inc",
    "Drivers/CMSIS/Device/ST/STM32F4xx/Include",
    "Drivers/CMSIS/Include",
    "Drivers",
    "Drivers/SYSTEM/sys",
    "Drivers/SYSTEM/usart",
    "Drivers/SYSTEM/delay",
    "Drivers/BSP/LED",
    "Drivers/BSP/BEEP",
    "User",
    "User/Hardware",
    "User/Hardware/WM8978",
    "User/Hardware/AUDIO",
    "User/Hardware/SDIO",
    "User/Hardware/LCD",
    "User/APP",
    "Middlewares/FATFS",
    "Middlewares/USB/STM32_USB_Device_Library/Core/Inc",
    "Middlewares/USB/STM32_USB_Device_Library/Class/Inc",
    "Middlewares/USB/USB_APP",
]


def project_sources():
    """按 uvprojx 里的 <FilePath> 顺序取源文件（.c/.s），保证与 Keil 一致。"""
    xml = open(UV, encoding="utf-8", errors="ignore").read()
    files = []
    for m in re.finditer(r"<FilePath>([^<]+)</FilePath>", xml):
        p = m.group(1).replace("\\", "/")
        p = p.replace("../../", "")
        full = os.path.normpath(os.path.join(ROOT, p))
        low = p.lower()
        if os.path.isfile(full) and (low.endswith(".c") or low.endswith(".s")):
            files.append(full)
    # 去重保序
    seen, out = set(), []
    for f in files:
        k = f.lower()
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def main():
    args = sys.argv[1:]
    opt = "-Oz"
    microlib = False
    lite = False
    for a in args:
        if a in ("-O0", "-O1", "-O2", "-O3", "-Os", "-Oz", "-Ofast"):
            opt = a
        elif a == "--microlib":
            microlib = True
        elif a == "--lite":
            lite = True

    os.makedirs(OUT, exist_ok=True)
    inc = " ".join("-I" + os.path.join(ROOT, i) for i in INCLUDES)
    base = [
        "--target=arm-arm-none-eabi",
        "-mcpu=cortex-m4",
        "-std=c99",
        opt,
        "-ffunction-sections",
        "-c",
        "-DUSE_HAL_DRIVER",
        "-DSTM32F407xx",
    ]

    srcs = project_sources()
    objs, failed = [], []
    for full in srcs:
        name = os.path.basename(full)
        stem = os.path.splitext(name)[0]
        obj = os.path.join(OUT, stem + ".o")
        if name.lower().endswith(".s"):
            cmd = [AS, "--cpu=Cortex-M4", "--pd", "__MICROLIB SETA 1", full, "-o", obj]
        else:
            extra = ["-D__MICROLIB"] if name.lower() == "usart.c" else []
            cmd = [AC] + base + extra + inc.split() + [full, "-o", obj]
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        if r.returncode != 0:
            failed.append((name, (r.stdout or b"").decode("utf-8", "replace")[:600]))
            continue
        objs.append(obj)

    print("sources=%d  compiled=%d  failed=%d  opt=%s  microlib=%s"
          % (len(srcs), len(objs), len(failed), opt, microlib))
    for n, msg in failed:
        print("FAIL", n)
        print(msg)

    if failed:
        return 2

    axf = os.path.join(OUT, "probe.axf")
    cmd = [LD, "--cpu=Cortex-M4", "--scatter", SCT, "--info=sizes"]
    if microlib:
        cmd += ["--library_type=microlib"]
    cmd += objs + ["-o", axf]
    r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    txt = (r.stdout or b"").decode("utf-8", "replace")
    if r.returncode != 0:
        print("LINK FAIL")
        print(txt[-2000:])
        return 3

    # 从 armlink 汇总行取体积（最可靠）
    rom = rw = 0
    for line in txt.splitlines():
        m = re.search(r"Total ROM Size.*?(\d+)", line)
        if m:
            rom = int(m.group(1))
        m = re.search(r"Total RW  Size.*?(\d+)", line)
        if m:
            rw = int(m.group(1))
    if rom == 0:
        print(txt[-1500:])
        return 4
    limit = 32768
    print("image  ROM(Code+RO+RWinit) = %d bytes (%.2f KB)" % (rom, rom / 1024.0))
    print("RAM    (RW+ZI)             = %d bytes (%.2f KB)" % (rw, rw / 1024.0))
    print("F407 Flash = 1024 KB / RAM = 128 KB")
    if lite:
        print("MDK-Lite 上限              = %d  余量 %+d" % (limit, limit - rom))
        print("结论:", "PASS" if rom <= limit else "OVER by %d" % (rom - limit))
        return 0 if rom <= limit else 1
    print("结论: 已授权 MDK（无 32KB 限制），链接通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
