@echo off
rem ================================================================
rem  test_tone.bat -- play a CLEAN -6 dBFS 1 kHz sine through the board
rem
rem  Use it as a reference: if this tone is clean but the song sounds
rem  harsh/clipped, the problem is the music file being too hot
rem  (loud master), not the amp. If the tone itself is harsh, suspect
rem  the amp / 5V supply.
rem
rem  --no-norm keeps the exact -6 dB amplitude (no auto normalization).
rem ================================================================
setlocal
cd /d "%~dp0.."
set "PY=py"
where py >nul 2>nul || set "PY=python"

echo.
echo === -6 dBFS 1 kHz test tone (should be a clean whistle) ===
echo.
"%PY%" Tools\host_cdc_sender.py --auto --wait -f Tools\t_1k_m6.wav --no-norm --gain 1.0 --no-loop

echo.
echo now try the song:  Tools\play.bat
pause
