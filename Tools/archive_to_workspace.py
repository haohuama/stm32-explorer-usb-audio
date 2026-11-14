# -*- coding: utf-8 -*-
"""archive_to_workspace.py —— 把今天的成果补充进「之前项目」工作区

在 C:/Users/mhh20/WorkBuddy/STM32项目/ 下建 项目归档_20261114/，
只放日志、约定、本轮文档与最终预览图（不含源码，源码在 GitHub 与 backup zip）。
幂等：重复运行覆盖同名文件。
"""
import os
import shutil

WS = r"C:/Users/mhh20/WorkBuddy/STM32项目"
SRC = r"C:/stm32TEST"
MEMO = os.path.join(WS, ".workbuddy", "memory")
DST = os.path.join(WS, "项目归档_20261114")

DOCS = [
    "docs/歌词音频同步_屏上切歌换歌_实施说明.md",
    "docs/居中歌词_封面去黑底_0到100音量_触屏诊断.md",
    "docs/音量键修复_按键重定义_观感优化_默认封面_实施说明.md",
    "docs/触屏按钮_第六首_英文单语_实施说明.md",
    "docs/按键_歌词动效_通用字库_实施说明.md",
    "docs/USB下发歌词与封面_实施说明.md",
]
IMGS = ["final_v3_s6.png", "final_v3_s5.png", "desktop_app_live.png"]


def put(src, rel):
    dst = os.path.join(DST, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print("  " + rel)


def main():
    os.makedirs(DST, exist_ok=True)
    print("== 日志与约定 ==")
    put(os.path.join(MEMO, "2026-11-14.md"), "2026-11-14_工作日志.md")
    put(os.path.join(MEMO, "MEMORY.md"), "项目长期约定.md")

    print("== 本轮实施说明 ==")
    for rel in DOCS:
        p = os.path.join(SRC, rel)
        if os.path.isfile(p):
            put(p, "实施说明/" + os.path.basename(rel))
    p = os.path.join(SRC, "DesktopPlayer", "README.md")
    if os.path.isfile(p):
        put(p, "实施说明/桌面控制台_README.md")

    print("== 最终预览图 ==")
    for fn in IMGS:
        p = os.path.join(SRC, "docs", "img", fn)
        if os.path.isfile(p):
            put(p, "最终预览/" + fn)


if __name__ == "__main__":
    main()
