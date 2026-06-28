$ErrorActionPreference = "Stop"

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$WorkflowDir = Join-Path $PackageRoot "n8n"
$Workflows = @(
  "av_eval_agent_workflow.submission_sanitized.json",
  "av_eval_agent_async_submit.workflow.json"
)

foreach ($wf in $Workflows) {
  $hostPath = Join-Path $WorkflowDir $wf
  if (-not (Test-Path $hostPath)) {
    throw "Missing workflow file: $hostPath"
  }
  $containerPath = "/import/n8n/$wf"
  Write-Host "Importing $wf ..."
  docker exec av-eval-n8n n8n import:workflow --input=$containerPath
}

Write-Host ""
Write-Host "Import complete. Open http://127.0.0.1:5678 and check:"
Write-Host "  AV_EVALUATION_AGENT_ORCHESTRATION_LAYER"
Write-Host "  async workflow path: /webhook/av-eval-agent-async"
