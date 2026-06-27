$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
$VenvSitePackages = Join-Path $Root ".venv\Lib\site-packages"
$BundledPython = "C:\Users\User\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

function Test-AgentPython {
  param([string]$PythonPath)

  $command = Get-Command $PythonPath -ErrorAction SilentlyContinue
  if (-not $command) {
    return $false
  }

  try {
    $previousPythonPath = $env:PYTHONPATH
    if (Test-Path $VenvSitePackages) {
      $env:PYTHONPATH = $VenvSitePackages
    }
    & $PythonPath -c "import fastapi, langgraph, pydantic, uvicorn" 2>$null | Out-Null
    $exitCode = $LASTEXITCODE
    $env:PYTHONPATH = $previousPythonPath
    return $exitCode -eq 0
  }
  catch {
    $env:PYTHONPATH = $previousPythonPath
    return $false
  }
}

# Prefer the bundled runtime because the copied .venv launcher can point to a
# stale Windows Python install on another machine. The bundled runtime still
# uses .venv\Lib\site-packages for FastAPI/LangGraph dependencies.
if (Test-AgentPython $BundledPython) {
  $Python = $BundledPython
  $env:PYTHONPATH = $VenvSitePackages
}
elseif (Test-AgentPython $VenvPython) {
  $Python = $VenvPython
  $env:PYTHONPATH = ""
}
elseif (Test-AgentPython "python") {
  $Python = "python"
  if (Test-Path $VenvSitePackages) {
    $env:PYTHONPATH = $VenvSitePackages
  }
}
else {
  throw "Agent 실행용 Python을 찾지 못했습니다. av_eval_agent\.venv를 재생성하거나 requirements.txt를 설치해야 합니다."
}

$existingPids = @()
try {
  $existingPids = Get-NetTCPConnection -LocalPort 8010 -ErrorAction Stop |
    Select-Object -ExpandProperty OwningProcess -Unique
}
catch {
  $existingPids = netstat -ano |
    Select-String ":8010" |
    ForEach-Object { ($_ -split "\s+")[-1] } |
    Where-Object { $_ -match "^\d+$" } |
    Select-Object -Unique
}

foreach ($pidText in $existingPids) {
  if ([int]$pidText -ne $PID) {
    Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
  }
}
Start-Sleep -Seconds 1

$StdoutLog = Join-Path $Root "data\agent_server_stdout.log"
$StderrLog = Join-Path $Root "data\agent_server_stderr.log"
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $StdoutLog) | Out-Null

$CmdPythonPath = $env:PYTHONPATH
$ServerCommand = "set ""PYTHONPATH=$CmdPythonPath"" && cd /d ""$Root"" && ""$Python"" -m uvicorn app.main:app --host 0.0.0.0 --port 8010 > ""$StdoutLog"" 2> ""$StderrLog"""

Start-Process `
  -FilePath "cmd.exe" `
  -ArgumentList @("/c", $ServerCommand) `
  -WorkingDirectory $Root `
  -WindowStyle Hidden

Start-Sleep -Seconds 2
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8010/health" -TimeoutSec 10
}
catch {
  Write-Host $_.Exception.Message
  if (Test-Path $StderrLog) {
    Get-Content $StderrLog -Tail 80
  }
  throw
}
