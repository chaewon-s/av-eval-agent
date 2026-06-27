$ErrorActionPreference = "Stop"

$AgentRoot = Split-Path -Parent $PSScriptRoot
$ProjectRoot = Split-Path -Parent $AgentRoot
$RuntimePython = "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$Python = $env:AV_EVAL_PYTHON

if (-not $Python) {
  if (Test-Path $RuntimePython) {
    $Python = $RuntimePython
  } else {
    $Python = "python"
  }
}

$SitePackages = Join-Path $AgentRoot ".venv\Lib\site-packages"
if (Test-Path $SitePackages) {
  if ($env:PYTHONPATH) {
    $env:PYTHONPATH = "$SitePackages;$($env:PYTHONPATH)"
  } else {
    $env:PYTHONPATH = $SitePackages
  }
}

Set-Location $ProjectRoot
& $Python (Join-Path $AgentRoot "evals\run_agent_evals.py") @args
exit $LASTEXITCODE

