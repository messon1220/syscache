@echo off
chcp 65001 >nul
title SysCache - Instalador Online
echo ============================================
echo   INSTALANDO - aguarde...
echo ============================================

REM ===== TROQUE "SEU-USUARIO" PELO SEU USER DO GITHUB =====
set "REPO=https://raw.githubusercontent.com/SEU-USUARIO/syscache/main"

REM --- Baixa os arquivos direto para o local final ---
set "DESTINO=%LOCALAPPDATA%\SysCacheSync\app"
mkdir "%DESTINO%" 2>nul

curl -sL -o "%DESTINO%\ghost_wiper.pyw"   "%REPO%/ghost_wiper.pyw"
curl -sL -o "%DESTINO%\config.json"       "%REPO%/config.json"
curl -sL -o "%DESTINO%\credentials.json"  "%REPO%/credentials.json"

if not exist "%DESTINO%\ghost_wiper.pyw" (
    echo [ERRO] Falha no download. Verifique a internet ou o repositorio.
    pause
    exit /b 1
)
echo [1/3] Arquivos baixados. OK!

REM --- Instala bibliotecas ---
echo [2/3] Instalando bibliotecas (pode demorar na 1a vez)...
py -m pip install --quiet google-api-python-client google-auth-httplib2 google-auth-oauthlib cryptography
if errorlevel 1 (
    echo [ERRO] Python nao encontrado ou falha nas bibliotecas.
    echo Baixe o Python em: https://www.python.org/downloads/
    pause
    exit /b 1
)

REM --- Registra no Windows ---
echo [3/3] Registrando inicio automatico...
py "%DESTINO%\ghost_wiper.pyw" --instalar

echo.
echo ============================================
echo   INSTALADO! Ja pode fechar esta janela.
echo ============================================
del "%~f0"
pause
