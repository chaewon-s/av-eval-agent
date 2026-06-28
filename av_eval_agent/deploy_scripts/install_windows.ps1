$ErrorActionPreference = "Stop"

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $PackageRoot ".venv\Scripts\python.exe"
$Req = Join-Path $PackageRoot "requirements.txt"

Write-Host "[1/3] Checking Python..."
$Python = (Get-Command python -ErrorAction SilentlyContinue)
if (-not $Python) {
  throw "Python is not available in PATH. Install Python 3.10+ first."
}

Write-Host "[2/3] Creating virtual environment..."
if (-not (Test-Path $VenvPython)) {
  & python -m venv (Join-Path $PackageRoot ".venv")
}

Write-Host "[3/3] Installing Python dependencies..."
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -r $Req

Write-Host ""
Write-Host "Install complete."
Write-Host "Next: powershell -ExecutionPolicy Bypass -File .\deploy_scripts\start_backend.ps1"
