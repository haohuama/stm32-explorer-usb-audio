@echo off
rem ============================================================
rem  STM32 music player - desktop console
rem  Double-click to launch. Needs: python 3 (with tkinter),
rem  pyserial, Pillow, and ffmpeg.exe (auto-detected).
rem ============================================================
setlocal
cd /d "%~dp0"

set "PY=py"
where py >nul 2>nul || set "PY=python"

echo.
echo  Starting desktop player...
echo  (USB cable must be in the USB_SLAVE port of the board)
echo.

"%PY%" app.py
if errorlevel 1 (
  echo.
  echo [ERROR] launch failed - see message above.
  pause
)
