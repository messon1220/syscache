@echo off
chcp 65001 >nul
title Ghost - Teste (janela visivel)
echo ============================================
echo   MODO TESTE - rodando visivel
echo   (com modo_simulacao=true, nada e apagado)
echo   Feche com Ctrl+C
echo ============================================
echo.
py "%LOCALAPPDATA%\SysCacheSync\app\ghost_wiper.pyw"
pause
