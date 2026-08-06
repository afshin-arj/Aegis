@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ============================================================================
REM  Aegis — one-shot Windows bootstrap + UI launcher
REM  Double-click this file, or run it from a terminal.
REM  Installs (if missing): Python, Node, Git, API/UI deps, LAMMPS, KART clone
REM  Then starts API + web UI and opens the browser.
REM ============================================================================

cd /d "%~dp0"

echo.
echo  ============================================================
echo   Aegis setup ^& run
echo  ============================================================
echo.

where powershell >nul 2>nul
if errorlevel 1 (
  echo [FAIL] PowerShell is required.
  echo.
  pause
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAIL] Bootstrap exited with code %RC%
  echo [HINT] Scroll up for the error. Common fixes:
  echo        - Install Python 3.12 / Node LTS / Git via winget
  echo        - Or open a terminal here and re-run: setup_and_run.cmd
  echo.
  pause
  exit /b %RC%
)

echo.
echo [INFO] Servers stopped. You can close this window.
pause
exit /b 0
