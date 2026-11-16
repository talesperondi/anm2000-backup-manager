# Compila a GUI (onedir), a CLI (onefile) e o instalador Inno Setup.
# Uso: powershell -ExecutionPolicy Bypass -File installer\build.ps1

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$isccCandidates = @(
    "${env:LOCALAPPDATA}\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
)
$iscc = $isccCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    throw "ISCC.exe (Inno Setup 6) não encontrado. Instale com: winget install JRSoftware.InnoSetup"
}

Write-Host "==> Limpando build/dist" -ForegroundColor Cyan
Remove-Item build, dist -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "==> Compilando interface (onedir)" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean installer\anm2000-gui.spec
if ($LASTEXITCODE -ne 0) { throw "Falha no build da GUI" }

Write-Host "==> Compilando CLI (onefile)" -ForegroundColor Cyan
python -m PyInstaller --noconfirm --clean installer\anm2000-cli.spec
if ($LASTEXITCODE -ne 0) { throw "Falha no build da CLI" }

Write-Host "==> Gerando instalador" -ForegroundColor Cyan
& $iscc installer\ANM2000BackupManager.iss
if ($LASTEXITCODE -ne 0) { throw "Falha ao gerar o instalador" }

Write-Host ""
Write-Host "Pronto:" -ForegroundColor Green
Get-ChildItem dist -Filter "*Setup*.exe" |
    ForEach-Object { Write-Host ("  " + $_.FullName + "  (" + [math]::Round($_.Length / 1MB, 1) + " MB)") }
Write-Host ""
Write-Host "SHA-256:" -ForegroundColor Green
Get-ChildItem dist -Filter "*Setup*.exe" | Get-FileHash -Algorithm SHA256 |
    ForEach-Object { Write-Host ("  " + $_.Hash) }
