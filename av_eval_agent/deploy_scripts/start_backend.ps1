$ErrorActionPreference = "Stop"

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$VenvPython = Join-Path $PackageRoot ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }
$LogDir = Join-Path $PackageRoot "data\logs"
$PidFile = Join-Path $PackageRoot "data\backend.pid"
$OutLog = Join-Path $LogDir "backend_stdout.log"
$ErrLog = Join-Path $LogDir "backend_stderr.log"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$existing = @()
try {
  $existing = Get-NetTCPConnection -LocalPort 8010 -ErrorAction Stop |
    Select-Object -ExpandProperty OwningProcess -Unique
} catch {
  $existing = netstat -ano |
    Select-String ":8010" |
    ForEach-Object { ($_ -split "\s+")[-1] } |
    Where-Object { $_ -match "^\d+$" } |
    Select-Object -Unique
}
foreach ($pidText in $existing) {
  if ([int]$pidText -ne $PID) {
    Stop-Process -Id ([int]$pidText) -Force -ErrorAction SilentlyContinue
  }
}

$Args = @("-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010")
$Process = Start-Process -FilePath $Python -ArgumentList $Args -WorkingDirectory $PackageRoot -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru -WindowStyle Hidden
Set-Content -LiteralPath $PidFile -Value $Process.Id -Encoding ASCII

Write-Host "Backend started. PID=$($Process.Id)"
Write-Host "Logs:"
Write-Host "  $OutLog"
Write-Host "  $ErrLog"

Start-Sleep -Seconds 3
try {
  Invoke-RestMethod -Uri "http://127.0.0.1:8010/health" -TimeoutSec 10 | ConvertTo-Json -Depth 5
} catch {
  Write-Host "Backend health check failed. Last stderr:"
  if (Test-Path $ErrLog) { Get-Content $ErrLog -Tail 80 }
  throw
}
