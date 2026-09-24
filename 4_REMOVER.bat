@echo off
chcp 65001 >nul
title Ghost - Remocao
echo ============================================
echo   REMOVER TUDO DESTE PC
echo ============================================
echo.
choice /c SN /m "Tem certeza? S=Sim N= nao"
if errorlevel 2 exit /b 0

echo [1/3] Removendo tarefa agendada...
py "%LOCALAPPDATA%\SysCacheSync\app\ghost_wiper.pyw" --desinstalar 2>nul
schtasks /Delete /TN "SysCacheSync" /F >nul 2>&1

echo [2/3] Encerrando processo se estiver rodando...
taskkill /f /im pythonw.exe >nul 2>&1

echo [3/3] Apagando dados ocultos do PC...
if exist "%LOCALAPPDATA%\SysCacheSync" (
    rmdir /s /q "%LOCALAPPDATA%\SysCacheSync"
    echo       Pasta de dados apagada.
)

echo.
echo ============================================
echo   REMOVIDO. Nenhum rastro deixado.
echo ============================================
pause
