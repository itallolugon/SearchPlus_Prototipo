@echo off
title Search+ - Passo 1 de 3: Dependencias Python
setlocal

echo ============================================================
echo   SEARCH+ - PASSO 1 DE 3: DEPENDENCIAS PYTHON
echo ============================================================
echo.

REM Verifica se Python esta instalado
set PYCMD=
where py >nul 2>&1 && set PYCMD=py
if "%PYCMD%"=="" (
    where python >nul 2>&1 && set PYCMD=python
)

if "%PYCMD%"=="" (
    echo [ERRO] Python nao foi encontrado nesta maquina.
    echo.
    echo Voce precisa instalar Python 3.10 ou superior antes de continuar.
    echo Abrindo a pagina oficial de download no navegador...
    echo.
    echo IMPORTANTE: na tela de instalacao, MARQUE a opcao
    echo             "Add Python to PATH" antes de clicar em Install.
    echo.
    start https://www.python.org/downloads/
    echo Apos instalar, FECHE este terminal e rode este script novamente.
    pause
    exit /b 1
)

echo [OK] Python detectado. Versao:
%PYCMD% --version
echo.

REM Atualiza pip e instala dependencias
echo [1/2] Atualizando pip...
%PYCMD% -m pip install --upgrade pip
if errorlevel 1 (
    echo [ERRO] Falha ao atualizar o pip. Verifique sua conexao com a internet.
    pause
    exit /b 1
)
echo.

echo [2/2] Instalando dependencias do app (pode demorar 10-15 min)...
echo       Sera baixado cerca de 2 GB de bibliotecas (PyTorch, etc.)
echo.
%PYCMD% -m pip install -r "%~dp0backend\requirements.txt"
if errorlevel 1 (
    echo.
    echo [ERRO] Falha ao instalar dependencias. Possiveis causas:
    echo   - Sem conexao com a internet
    echo   - Pouco espaco em disco (precisa ~3 GB livres)
    echo   - Antivirus bloqueando o pip
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   PASSO 1 CONCLUIDO!
echo   Agora rode o arquivo: 2-INSTALAR-OLLAMA.bat
echo ============================================================
pause
