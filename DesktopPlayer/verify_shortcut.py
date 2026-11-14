# -*- coding: utf-8 -*-
"""verify_shortcut.py —— 模拟双击桌面快捷方式，验证 GUI 真的能启动并截一张干净图"""
import os
import subprocess
import time

import win32gui
from PIL import ImageGrab

LNK = r"C:\Users\mhh20\Desktop\STM32 音乐播放器.lnk"
SHOT = r"C:\stm32TEST\docs\img\desktop_app_live.png"
TITLE_KEY = "STM32 音乐播放器"


def pids():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq pythonw.exe"],
                         capture_output=True).stdout.decode("gbk", "ignore")
    r = set()
    for line in out.splitlines():
        parts = line.split()
        if parts and parts[0].lower() == "pythonw.exe" and len(parts) > 1:
            try:
                r.add(int(parts[1]))
            except ValueError:
                pass
    return r


def find_hwnd():
    found = []

    def cb(h, _):
        if win32gui.IsWindowVisible(h) and TITLE_KEY in win32gui.GetWindowText(h):
            found.append(h)

    win32gui.EnumWindows(cb, None)
    return found[0] if found else None


def main():
    before = pids()
    print("启动前 pythonw 进程:", sorted(before))
    os.startfile(LNK)
    hwnd = None
    for _ in range(20):
        time.sleep(0.3)
        hwnd = find_hwnd()
        if hwnd:
            break
    new = pids() - before
    print("新增 pythonw 进程:", sorted(new), "| 窗口句柄:", hwnd)
    ok = bool(new) and bool(hwnd)

    if hwnd:
        try:
            win32gui.ShowWindow(hwnd, 9)                 # SW_RESTORE
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.7)
            ImageGrab.grab().save(SHOT)
            print("全屏截图:", SHOT)
        except Exception as e:
            print("置顶/截图失败:", e)
            ImageGrab.grab().save(SHOT)

    for p in new:
        subprocess.run(["taskkill", "/F", "/PID", str(p)], capture_output=True)
    print("结果:", "快捷方式能启动 GUI" if ok else "启动失败")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
