@echo off
title Search+ - Servidor
cd /d "%~dp0"

echo ============================================================
echo   SEARCH+ - INICIANDO SERVIDOR (IA via Claude + busca CLIP)
echo ============================================================
echo.

REM Detecta Python
set PYCMD=
where py >nul 2>&1 && set PYCMD=py
if "%PYCMD%"=="" (
    where python >nul 2>&1 && set PYCMD=python
)
if "%PYCMD%"=="" (
    echo [ERRO] Python nao encontrado no PATH.
    pause
    exit /b 1
)

REM A descricao de imagens e o re-rank da busca usam a API do Claude.
REM A chave fica em backend\.env (ANTHROPIC_API_KEY). Precisa de internet.

REM SEARCHPLUS_OFFLINE=0 permite baixar os modelos CLIP na primeira vez.
REM Depois disso eles ficam em cache e carregam sozinhos.
set SEARCHPLUS_OFFLINE=0

echo Abrindo o navegador em http://127.0.0.1:5000 em alguns segundos...
start "" cmd /c "timeout /t 6 /nobreak >nul && start http://127.0.0.1:5000"

echo Iniciando o servidor (feche esta janela para parar)...
echo ============================================================
echo.
%PYCMD% backend\app.py

pause
