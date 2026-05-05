@echo off
title Search+ - Passo 2 de 3: Ollama e Modelos de IA
setlocal

echo ============================================================
echo   SEARCH+ - PASSO 2 DE 3: OLLAMA E MODELOS DE IA
echo ============================================================
echo.

REM Verifica se Ollama esta instalado
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERRO] Ollama nao foi encontrado nesta maquina.
    echo.
    echo Voce precisa instalar o Ollama antes de continuar.
    echo Abrindo a pagina oficial de download no navegador...
    echo.
    start https://ollama.com/download/windows
    echo.
    echo Apos instalar, FECHE este terminal e rode este script novamente.
    pause
    exit /b 1
)

echo [OK] Ollama detectado:
ollama --version
echo.

REM Garante que o servico do Ollama esta rodando
echo [1/3] Iniciando servico Ollama em segundo plano...
start /b "" ollama serve >nul 2>&1
timeout /t 5 /nobreak > nul
echo.

REM Baixa modelo de visao (LLaVA 13B, ~8 GB)
echo [2/3] Baixando modelo de visao (llava:13b, ~8 GB)...
echo       Isso pode demorar 15-30 min dependendo da sua internet.
echo.
ollama pull llava:13b
if errorlevel 1 (
    echo [ERRO] Falha ao baixar llava:13b. Verifique sua conexao.
    pause
    exit /b 1
)
echo.

REM Baixa modelo de texto (Llama 3.2, ~2 GB)
echo [3/3] Baixando modelo de texto (llama3.2, ~2 GB)...
echo       Mais 5-10 min de download.
echo.
ollama pull llama3.2
if errorlevel 1 (
    echo [ERRO] Falha ao baixar llama3.2. Verifique sua conexao.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   PASSO 2 CONCLUIDO!
echo   Agora rode o arquivo: INICIAR.bat
echo ============================================================
pause
