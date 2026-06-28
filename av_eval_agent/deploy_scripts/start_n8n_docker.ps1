$ErrorActionPreference = "Stop"

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$EnvFile = Join-Path $PackageRoot ".env"
$EnvExample = Join-Path $PackageRoot ".env.example"

if (-not (Test-Path $EnvFile) -and (Test-Path $EnvExample)) {
  Copy-Item -LiteralPath $EnvExample -Destination $EnvFile
  Write-Host "Created .env from .env.example. Edit .env if ports or URLs need to change."
}

Write-Host "Starting n8n with Docker Compose..."
docker compose --env-file $EnvFile -f (Join-Path $PackageRoot "docker-compose.yml") up -d

Write-Host "Waiting for n8n health..."
for ($i = 0; $i -lt 30; $i++) {
  try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:5678/healthz" -TimeoutSec 3
    $health | ConvertTo-Json -Depth 5
    Write-Host "n8n is ready: http://127.0.0.1:5678"
    exit 0
  } catch {
    Start-Sleep -Seconds 2
  }
}
throw "n8n did not become healthy within 60 seconds."
