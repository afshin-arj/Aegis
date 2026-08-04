@echo off
setlocal EnableExtensions EnableDelayedExpansion
REM ============================================================================
REM  Aegis — one-shot Windows bootstrap + UI launcher
REM  Installs (if missing): Python, Node, Git, API/UI deps, LAMMPS, KART clone
REM  Skips any component already present. Then starts API + web UI.
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
  exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap.ps1"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo.
  echo [FAIL] Bootstrap exited with code %RC%
  exit /b %RC%
)

echo.
echo [INFO] Press Ctrl+C in this window to stop Aegis servers.
exit /b 0
