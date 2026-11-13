#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地备份：把工程源码与技能包各打一个 zip。

排除项：
  源码仓：.git / Output / *.wav / *.mp3 / __pycache__ / *.axf *.o *.map 等构建产物
  技能包：.git
"""
import os
import sys
import zipfile

SRC = r"C:/stm32TEST"
SKILL = r"C:/Users/mhh20/WorkBuddy/STM32项目/skills/stm32f407-explorer-audio"
BK = r"C:/Users/mhh20/WorkBuddy/STM32项目/backup"

SKIP_DIRS = {".git", "Output", "Objects", "Listings", "DebugConfig", "RTE",
             "__pycache__", ".workbuddy"}
SKIP_EXT = {".wav", ".mp3", ".flac", ".axf", ".o", ".d", ".crf", ".dep",
            ".lnp", ".lst", ".map", ".pyc", ".uvguix"}


def add_tree(zf, root, arc_prefix):
    n = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext in SKIP_EXT:
                continue
            if fn.startswith("_") and ext in (".txt", ".md"):
                continue
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, root).replace("\\", "/")
            arc = "%s/%s" % (arc_prefix, rel) if arc_prefix else rel
            try:
                zf.write(full, arc)
                n += 1
                total += os.path.getsize(full)
            except OSError as e:
                print("  skip", rel, e)
    return n, total


def make(zip_path, jobs):
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for root, prefix in jobs:
            n, total = add_tree(zf, root, prefix)
            print("  %-46s %4d 文件  %6.1f MB" % (prefix or os.path.basename(root), n, total / 1048576.0))
    print("=> %s  (%.1f MB)" % (zip_path, os.path.getsize(zip_path) / 1048576.0))


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else "20261114"
    print("== 工程源码（不含 .git / Output / 音频 / 构建产物）==")
    make(os.path.join(BK, "stm32-explorer-usb-audio_%s.zip" % day),
         [(SRC, "stm32-explorer-usb-audio")])
    print("== 技能包（不含 .git）==")
    make(os.path.join(BK, "stm32f407-explorer-audio_%s.zip" % day),
         [(SKILL, "stm32f407-explorer-audio")])
