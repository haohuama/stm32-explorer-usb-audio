# -*- coding: utf-8 -*-
"""make_shortcut.py —— 在桌面创建「STM32 音乐播放器」快捷方式

用 pythonw.exe 启动（无黑框控制台），图标用 app.ico。
重复运行会覆盖同名快捷方式，不会堆积。
"""
import os
import sys

import win32com.client


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    app = os.path.join(here, "app.py")
    ico = os.path.join(here, "app.ico")
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    if not os.path.isfile(pythonw):
        pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if not os.path.isfile(pythonw):
        print("找不到 pythonw.exe，改用 python.exe（会带控制台窗口）")
        pythonw = sys.executable

    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    if not os.path.isdir(desktop):
        # OneDrive 重定向等情况
        desktop = os.environ.get("USERPROFILE", "") + r"\Desktop"
    lnk = os.path.join(desktop, "STM32 音乐播放器.lnk")

    sh = win32com.client.Dispatch("WScript.Shell")
    s = sh.CreateShortCut(lnk)
    s.TargetPath = pythonw
    s.Arguments = '"%s"' % app
    s.WorkingDirectory = here
    s.IconLocation = "%s,0" % ico
    s.Description = "STM32 探索者 F407 音乐播放器 - 桌面控制台"
    s.WindowStyle = 1
    s.Save()

    # 回读校验
    v = sh.CreateShortCut(lnk)
    print("快捷方式 :", lnk)
    print("目标     :", v.TargetPath)
    print("参数     :", v.Arguments)
    print("工作目录 :", v.WorkingDirectory)
    print("图标     :", v.IconLocation)
    ok = (os.path.isfile(lnk) and os.path.isfile(app)
          and v.TargetPath.lower().endswith("pythonw.exe")
          and app.lower() in v.Arguments.lower())
    print("结果     :", "OK" if ok else "异常")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
