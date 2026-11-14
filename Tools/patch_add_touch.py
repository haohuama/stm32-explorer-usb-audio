# -*- coding: utf-8 -*-
"""把 tp.c（XPT2046 触屏）加进 Keil 工程：新建 User/Hardware/TOUCH 组 + 头文件路径。

幂等：已经加过就跳过。
"""
import io
import os
import sys

P = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "Projects", "MDK-ARM", "atk_f407.uvprojx")
s = io.open(P, encoding="utf-8", errors="ignore").read()

if "tp.c" in s:
    print("tp.c 已在工程里，跳过")
    sys.exit(0)

# 1) 组：插在 <GroupName>User/Hardware/KEY</GroupName> 那一组的 </Group> 之后
key_group_end = None
i = s.find("<GroupName>User/Hardware/KEY</GroupName>")
if i < 0:
    print("找不到 KEY 组，请手工添加")
    sys.exit(1)
j = s.find("</Group>", i)
key_group_end = j + len("</Group>")

group = """
        <Group>
          <GroupName>User/Hardware/TOUCH</GroupName>
          <Files>
            <File>
              <FileName>tp.c</FileName>
              <FileType>1</FileType>
              <FilePath>..\\..\\User\\Hardware\\TOUCH\\tp.c</FilePath>
            </File>
          </Files>
        </Group>"""

s = s[:key_group_end] + group + s[key_group_end:]

# 2) 头文件路径（两处：C 与汇编共用同一串）
s = s.replace(r"..\..\User\Hardware\KEY</IncludePath>",
              r"..\..\User\Hardware\KEY;..\..\User\Hardware\TOUCH</IncludePath>")

io.open(P, "w", encoding="utf-8", newline="\n").write(s)
print("已加入 tp.c + IncludePath(TOUCH)")
