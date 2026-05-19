# Empacotador do Search+ Portátil
# Gera dist/SearchPlus_Portatil.zip pronto para distribuir

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.Encoding]::UTF8

$Root    = Resolve-Path (Join-Path $PSScriptRoot '..')
$OutDir  = Join-Path $Root 'dist'
$PkgDir  = Join-Path $OutDir 'SearchPlus_Portatil'
$ZipPath = Join-Path $OutDir 'SearchPlus_Portatil.zip'

Write-Host "============================================================"
Write-Host "  EMPACOTANDO SEARCH+ PORTATIL"
Write-Host "============================================================"
Write-Host ""

# Limpa pasta de saida anterior
if (Test-Path $PkgDir)  { Remove-Item -Recurse -Force $PkgDir }
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
New-Item -ItemType Directory -Force -Path $PkgDir | Out-Null

Write-Host "[1/3] Copiando arquivos do app..."

# Backend (sem db, cache, logs, .env com credenciais)
$excludeBackend = @('*.db', '*.db-shm', '*.db-wal', '*.log', '*.pyc', '.env')
Copy-Item -Path (Join-Path $Root 'backend') -Destination $PkgDir -Recurse -Force `
    -Exclude $excludeBackend

# Remove __pycache__ recursivamente (Copy-Item -Exclude nao pega diretorios)
Get-ChildItem -Path (Join-Path $PkgDir 'backend') -Recurse -Force -Directory `
    -Filter '__pycache__' | Remove-Item -Recurse -Force

# Garante que .env NUNCA vai pro ZIP (segunda camada de defesa)
$envInPkg = Join-Path $PkgDir 'backend\.env'
if (Test-Path $envInPkg) {
    Remove-Item -Force $envInPkg
    Write-Host "[AVISO] .env removido do pacote (continha credenciais)" -ForegroundColor Yellow
}

# Front estatico
foreach ($f in 'index.html', 'script.js', 'style.css') {
    Copy-Item -Path (Join-Path $Root $f) -Destination $PkgDir -Force
}
Copy-Item -Path (Join-Path $Root 'fonts') -Destination $PkgDir -Recurse -Force

Write-Host "[2/3] Copiando scripts de instalacao..."

foreach ($f in '1-INSTALAR-DEPENDENCIAS.bat', '2-INSTALAR-OLLAMA.bat', 'INICIAR.bat', 'INSTRUTIVO.txt') {
    Copy-Item -Path (Join-Path $PSScriptRoot $f) -Destination $PkgDir -Force
}

Write-Host "[3/3] Compactando em ZIP..."

Compress-Archive -Path (Join-Path $PkgDir '*') -DestinationPath $ZipPath -Force

if (-not (Test-Path $ZipPath)) {
    Write-Host "[ERRO] ZIP nao foi criado." -ForegroundColor Red
    exit 1
}

$sizeMB = [Math]::Round((Get-Item $ZipPath).Length / 1MB, 2)

Write-Host ""
Write-Host "============================================================" -ForegroundColor Green
Write-Host "  CONCLUIDO" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Green
Write-Host ""
Write-Host "Arquivo gerado:"
Write-Host "  $ZipPath"
Write-Host ""
Write-Host "Tamanho: $sizeMB MB"
Write-Host ""
Write-Host "Voce pode enviar esse ZIP para qualquer maquina Windows."
Write-Host "Quem receber so precisa descompactar e seguir o INSTRUTIVO.txt"
