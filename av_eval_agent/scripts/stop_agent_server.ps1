$Existing = Get-NetTCPConnection -LocalPort 8010 -ErrorAction SilentlyContinue
if ($Existing) {
  $Existing | Select-Object OwningProcess -Unique | ForEach-Object {
    Stop-Process -Id $_.OwningProcess -Force
  }
  "AV Evaluation Agent 서버를 종료했습니다."
} else {
  "실행 중인 AV Evaluation Agent 서버가 없습니다."
}
