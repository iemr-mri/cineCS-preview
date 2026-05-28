# Builds the standalone cine-preview.exe from source.
#
# Run from the repo root in PowerShell:
#     .\build-exe.ps1
#
# Produces dist\cine-preview.exe: a single self-contained file that runs the
# GUI with no Python, virtual environment, or admin rights required.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$venvPython = ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Error "No .venv found. Create it first: py -3.10 -m venv .venv ; then .venv\Scripts\python.exe -m pip install -e .[build]"
}

Write-Host "Installing build dependencies (pyinstaller)..." -ForegroundColor Cyan
& $venvPython -m pip install -e ".[build]"
if ($LASTEXITCODE -ne 0) { Write-Error "Failed to install build dependencies." }

Write-Host "Cleaning previous build output..." -ForegroundColor Cyan
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

Write-Host "Building cine-preview.exe with PyInstaller..." -ForegroundColor Cyan
& $venvPython -m PyInstaller cine-preview.spec --noconfirm
if ($LASTEXITCODE -ne 0) { Write-Error "PyInstaller build failed." }

$exePath = Join-Path $PSScriptRoot "dist\cine-preview.exe"
if (Test-Path $exePath) {
    $sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 1)
    Write-Host ""
    Write-Host "Build complete: dist\cine-preview.exe ($sizeMB MB)" -ForegroundColor Green
    Write-Host "Distribute that single file. Double-click to run, no install needed." -ForegroundColor Green
} else {
    Write-Error "Build reported success but dist\cine-preview.exe is missing."
}
