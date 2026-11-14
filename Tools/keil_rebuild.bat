@echo off
rem ================================================================
rem  keil_rebuild.bat -- full rebuild of atk_f407.uvprojx from the CLI
rem  (no need to open the Keil IDE; works when Keil is not running)
rem
rem  Output : ..\Output\atk_f407.axf / .hex / rebuild_all.txt
rem  Exit   : 0 = OK (no error, no warning), 1 = warnings, 2 = errors
rem ================================================================
setlocal
set "UV4=C:\Keil_v5\UV4\UV4.exe"
set "PROJ=%~dp0..\Projects\MDK-ARM\atk_f407.uvprojx"
set "LOG=%~dp0..\Output\rebuild_all.txt"

if not exist "%UV4%" (
    echo [ERROR] Keil UV4.exe not found: %UV4%
    pause
    exit /b 3
)

echo Rebuilding: %PROJ%
"%UV4%" -r "%PROJ%" -j0 -o "%LOG%"
set RC=%ERRORLEVEL%

echo.
type "%LOG%"
echo.
if "%RC%"=="0" echo [OK] 0 error / 0 warning. Flash Output\atk_f407.hex with ST-Link.
if "%RC%"=="1" echo [WARN] build ok but has warnings - see log above.
if "%RC%"=="2" echo [FAIL] compile/link errors - see log above.
if "%RC%"=="3" echo [FAIL] fatal error.
echo.
rem double-click keeps the window open; pass --nopause to skip (CI / scripts)
if /i not "%~1"=="--nopause" pause
exit /b %RC%
