#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一次性的工程补丁打进 uvprojx（幂等：已存在就跳过）。

用法: python Tools/patch_project.py
目前处理：
  1) IncludePath 里补 ..\\..\\User\\Hardware\\KEY
  2) 新增源文件组 User/Hardware/KEY（key.c）
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UV = os.path.join(ROOT, "Projects/MDK-ARM/atk_f407.uvprojx")

INC_ADD = r"..\..\User\Hardware\KEY"

FILES = [
    ("User/Hardware/KEY", [("key.c", r"..\..\User\Hardware\KEY\key.c")]),
]


def main():
    s = open(UV, encoding="utf-8", errors="ignore").read()
    orig = s

    # 1) IncludePath
    if INC_ADD not in s:
        s = re.sub(r"(<IncludePath>)([^<]*)(</IncludePath>)",
                   lambda m: m.group(1) + (m.group(2) + ";" if m.group(2) else "") + INC_ADD + m.group(3),
                   s)
        print("include path: 已加入", INC_ADD)
    else:
        print("include path: 已存在，跳过")

    # 2) 新增组
    for grp, files in FILES:
        if "<GroupName>%s</GroupName>" % grp in s:
            print("group %s: 已存在，跳过" % grp)
            continue
        body = ["        <Group>",
                "          <GroupName>%s</GroupName>" % grp,
                "          <Files>"]
        for name, path in files:
            body += ["            <File>",
                     "              <FileName>%s</FileName>" % name,
                     "              <FileType>1</FileType>",
                     "              <FilePath>%s</FilePath>" % path,
                     "            </File>"]
        body += ["          </Files>", "        </Group>", "      </Groups>"]
        s = s.replace("      </Groups>", "\n".join(body), 1)
        print("group %s: 已加入 %d 个文件" % (grp, len(files)))

    if s != orig:
        open(UV, "w", encoding="utf-8", newline="\n").write(s)
        print("已写回", UV)
    else:
        print("无需修改")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
