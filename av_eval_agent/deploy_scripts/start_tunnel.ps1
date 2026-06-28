$ErrorActionPreference = "Stop"

$PackageRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ToolDir = Join-Path $PackageRoot "tools"
$Cloudflared = Join-Path $ToolDir "cloudflared.exe"
$LogDir = Join-Path $PackageRoot "data\logs"
$OutLog = Join-Path $LogDir "cloudflared_stdout.log"
$ErrLog = Join-Path $LogDir "cloudflared_stderr.log"

New-Item -ItemType Directory -Force -Path $ToolDir,$LogDir | Out-Null

if (-not (Test-Path $Cloudflared)) {
  Write-Host "Downloading cloudflared..."
  Invoke-WebRequest -Uri "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe" -OutFile $Cloudflared
}

Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue

$Process = Start-Process -FilePath $Cloudflared -ArgumentList @("tunnel", "--url", "http://127.0.0.1:5678", "--no-autoupdate") -RedirectStandardOutput $OutLog -RedirectStandardError $ErrLog -PassThru -WindowStyle Hidden
Write-Host "cloudflared started. PID=$($Process.Id)"

for ($i = 0; $i -lt 40; $i++) {
  Start-Sleep -Seconds 1
  $text = ""
  if (Test-Path $ErrLog) { $text += (Get-Content $ErrLog -Raw -ErrorAction SilentlyContinue) }
  if (Test-Path $OutLog) { $text += (Get-Content $OutLog -Raw -ErrorAction SilentlyContinue) }
  $match = [regex]::Match($text, "https://[a-zA-Z0-9-]+\.trycloudflare\.com")
  if ($match.Success) {
    Write-Host ""
    Write-Host "Tunnel URL:"
    Write-Host "  $($match.Value)"
    Write-Host ""
    Write-Host "Open n8n via:"
    Write-Host "  $($match.Value)"
    exit 0
  }
}

Write-Host "Could not parse tunnel URL. Check logs:"
Write-Host "  $ErrLog"
Write-Host "  $OutLog"
