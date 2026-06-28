$ErrorActionPreference = "Stop"

param(
  [ValidateSet("scenario1", "scenario2")]
  [string]$Scenario = "scenario2",
  [switch]$ExecuteSimulation,
  [switch]$RunKpis
)

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ExampleFile = Join-Path $PackageRoot "examples\$($Scenario)_request.txt"
if (-not (Test-Path $ExampleFile)) {
  throw "Missing example request: $ExampleFile"
}

$UserRequest = Get-Content -LiteralPath $ExampleFile -Raw
$Body = @{
  user_request = $UserRequest
  execute_simulation = [bool]$ExecuteSimulation
  run_kpis = [bool]$RunKpis
  apply_ml = $false
  record = $false
  review_required = $true
  base_url = "http://host.docker.internal:8010"
  n8n_public_url = "http://127.0.0.1:5678"
} | ConvertTo-Json -Depth 20

Write-Host "Submitting sample request to n8n webhook..."
$Response = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:5678/webhook/av-eval-agent" `
  -ContentType "application/json; charset=utf-8" `
  -Body $Body

$Response | ConvertTo-Json -Depth 20
