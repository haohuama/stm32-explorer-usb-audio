# -*- coding: utf-8 -*-
"""collect_notes.py —— 汇总「今天的项目 + 日志 + 各种资料」进仓库 ProjectNotes/

幂等：重复运行只是覆盖同名文件。
只收纯文本/Markdown/小图标，不含音频、构建产物、认证信息。
"""
import os
import shutil

WS = r"C:/Users/mhh20/WorkBuddy/STM32项目"
MEMO = os.path.join(WS, ".workbuddy", "memory")
WS_DOCS = os.path.join(WS, "docs")
SKILL = os.path.join(WS, "skills", "stm32f407-explorer-audio")
DST = r"C:/stm32TEST/ProjectNotes"


def put(src, rel):
    dst = os.path.join(DST, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    print("  %-52s %7d B" % (rel, os.path.getsize(dst)))


def main():
    os.makedirs(DST, exist_ok=True)
    print("== 今日日志 / 项目约定 ==")
    for src, rel in ((os.path.join(MEMO, "2026-11-14.md"), "2026-11-14_工作日志.md"),
                     (os.path.join(MEMO, "MEMORY.md"), "项目长期约定.md")):
        if os.path.isfile(src):
            put(src, rel)

    print("== 工作区技术资料 ==")
    n = 0
    if os.path.isdir(WS_DOCS):
        for fn in sorted(os.listdir(WS_DOCS)):
            if fn.lower().endswith((".md", ".txt")):
                put(os.path.join(WS_DOCS, fn), "参考资料/" + fn)
                n += 1
    print("  共 %d 份" % n)

    print("== 技能包（工程踩坑经验）==")
    if os.path.isdir(SKILL):
        for root, dirs, files in os.walk(SKILL):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for fn in files:
                if fn.startswith("_"):
                    continue
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, SKILL).replace("\\", "/")
                put(full, "技能包/" + rel)


if __name__ == "__main__":
    main()
