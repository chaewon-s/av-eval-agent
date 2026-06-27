$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$RequestJson = Join-Path $Root "examples\scenario2_request_api.json"

$run = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8010/run/start" `
  -ContentType "application/json; charset=utf-8" `
  -InFile $RequestJson

$prepareBody = @{
  include_kpis = $true
  apply_ml = $false
  record = $false
} | ConvertTo-Json -Depth 10

$prepared = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8010/run/prepare/$($run.run_id)" `
  -ContentType "application/json; charset=utf-8" `
  -Body $prepareBody

$executeBody = @{
  execute_simulation = $false
  run_kpis = $false
  apply_ml = $false
  record = $false
} | ConvertTo-Json -Depth 10

$dryRun = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8010/run/execute/$($run.run_id)" `
  -ContentType "application/json; charset=utf-8" `
  -Body $executeBody

[PSCustomObject]@{
  run_id = $run.run_id
  prepare_status = $prepared.status
  dry_run_status = $dryRun.status
  execution_plan = $prepared.execution_plan_path
}
