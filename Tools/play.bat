@echo off
rem ================================================================
rem  play.bat -- one click: stream Tools\pl01..plNN.wav to the board
rem
rem  The song is NOT stored in the MCU. It is streamed from this PC
rem  over the USB cable (USB_SLAVE port) every time you play.
rem
rem  Keys on the board (host must be running this script):
rem    KEY0 short = next song      KEY0 long (0.7s) = play/pause
rem    KEY1 short = restart song   WK_UP / KEY2     = volume +/-
rem ================================================================
setlocal
cd /d "%~dp0.."

set "PY=py"
where py >nul 2>nul || set "PY=python"

echo.
echo === streaming Tools\pl01..plNN.wav to the board ===
echo     (plug the USB cable into the USB_SLAVE port, not USB_232)
echo.

"%PY%" Tools\host_cdc_sender.py --auto --wait --playlist --gain 1.0 --prefill 0 --keys

echo.
echo [ended] tips:
echo   - "no port found": cable must be in USB_SLAVE; check Device Manager
echo   - no sound but no error: check the CH340 serial log on the board side
echo.
pause
