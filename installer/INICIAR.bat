@echo off
title Search+ - App rodando
setlocal

echo ============================================================
echo   SEARCH+ - INICIANDO O APP
echo ============================================================
echo.

REM Detecta Python
set PYCMD=
where py >nul 2>&1 && set PYCMD=py
if "%PYCMD%"=="" (
    where python >nul 2>&1 && set PYCMD=python
)
if "%PYCMD%"=="" (
    echo [ERRO] Python nao encontrado.
    echo Rode primeiro o arquivo 1-INSTALAR-DEPENDENCIAS.bat
    pause
    exit /b 1
)

REM Verifica se .env existe (credenciais do Supabase)
if not exist "%~dp0backend\.env" (
    echo ============================================================
    echo   [ERRO] Arquivo backend\.env nao encontrado
    echo ============================================================
    echo.
    echo Voce precisa criar o arquivo de credenciais antes de iniciar.
    echo.
    echo 1. Copie o arquivo "backend\.env.example" para "backend\.env"
    echo 2. Abra o backend\.env em um editor de texto
    echo 3. Cole sua connection string do Supabase em DATABASE_URL
    echo.
    echo Veja o INSTRUTIVO.txt - Passo 3 para detalhes.
    echo.
    pause
    exit /b 1
)

REM Garante que o Ollama esta rodando
where ollama >nul 2>&1
if %errorlevel% equ 0 (
    tasklist /FI "IMAGENAME eq ollama.exe" 2>nul | find /I "ollama.exe" >nul
    if errorlevel 1 (
        echo Iniciando o Ollama em segundo plano...
        start /b "" ollama serve >nul 2>&1
        timeout /t 4 /nobreak > nul
    )
) else (
    echo [AVISO] Ollama nao encontrado. A IA nao vai funcionar.
    echo Rode 2-INSTALAR-OLLAMA.bat se quiser as funcionalidades de busca semantica.
    timeout /t 3 /nobreak > nul
)

echo Iniciando o servidor Search+...
echo Em alguns segundos seu navegador vai abrir em http://127.0.0.1:5000
echo.
echo Para FECHAR o app: feche esta janela.
echo ============================================================
echo.

REM Abre navegador apos 5s e inicia servidor
start "" cmd /c "timeout /t 5 /nobreak > nul && start http://127.0.0.1:5000"

REM Roda o servidor (bloqueia ate fechar a janela)
%PYCMD% "%~dp0backend\app.py"

pause
