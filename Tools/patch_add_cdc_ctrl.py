#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 cdc_ctrl.c 加进 uvprojx 的 User/APP 组（幂等）。"""
import os

UV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "Projects/MDK-ARM/atk_f407.uvprojx")

ANCHOR = (
    "            <File>\n"
    "              <FileName>wav_probe.c</FileName>\n"
    "              <FileType>1</FileType>\n"
    "              <FilePath>" + ".." + chr(92) + ".." + chr(92) + "User" + chr(92) + "APP" + chr(92) + "wav_probe.c</FilePath>\n"
    "            </File>"
)

ADD = (
    "\n            <File>\n"
    "              <FileName>cdc_ctrl.c</FileName>\n"
    "              <FileType>1</FileType>\n"
    "              <FilePath>" + ".." + chr(92) + ".." + chr(92) + "User" + chr(92) + "APP" + chr(92) + "cdc_ctrl.c</FilePath>\n"
    "            </File>"
)


def main():
    s = open(UV, encoding="utf-8", errors="ignore").read()
    if "cdc_ctrl.c" in s:
        print("cdc_ctrl.c 已在工程里，跳过")
        return 0
    if ANCHOR not in s:
        print("没找到锚点（wav_probe.c），请手工添加")
        return 1
    s = s.replace(ANCHOR, ANCHOR + ADD, 1)
    open(UV, "w", encoding="utf-8", newline="\n").write(s)
    print("已加入 cdc_ctrl.c")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
