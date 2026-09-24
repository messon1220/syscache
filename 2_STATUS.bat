@echo off
chcp 65001 >nul
title Ghost - Status
echo ============================================
echo   CONTAS JA PROCESSADAS NESTE PC
echo ============================================
py "%LOCALAPPDATA%\SysCacheSync\app\ghost_wiper.pyw" --status
echo.
pause
