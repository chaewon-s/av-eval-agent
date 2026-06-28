$ErrorActionPreference = "Continue"

Write-Host "Backend health:"
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8010/health" -TimeoutSec 5 | ConvertTo-Json -Depth 5
} catch {
  Write-Host "  Backend not reachable: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "n8n health:"
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:5678/healthz" -TimeoutSec 5 | ConvertTo-Json -Depth 5
} catch {
  Write-Host "  n8n not reachable: $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Docker containers:"
docker ps --filter "name=av-eval-n8n" --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
