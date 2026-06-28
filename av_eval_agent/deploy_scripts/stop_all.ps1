$ErrorActionPreference = "Continue"

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$PidFile = Join-Path $PackageRoot "data\backend.pid"

if (Test-Path $PidFile) {
  $pidText = Get-Content $PidFile -Raw
  if ($pidText -match "^\s*\d+\s*$") {
    Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
  }
  Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
}

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$EnvFile = Join-Path $PackageRoot ".env"
docker compose --env-file $EnvFile -f (Join-Path $PackageRoot "docker-compose.yml") down

Write-Host "Stopped backend, cloudflared, and n8n container."
