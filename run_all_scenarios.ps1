<#
=====================================================================
 run_all_scenarios.ps1
 Run all four OpenCDA experiments from a single file.
   1. Scenario 1 - No V2X   (scenario_1_no_v2x)
   2. Scenario 1 - V2X      (scenario_1_v2x)
   3. Scenario 2 - No V2X   (scenario2)
   4. Scenario 2 - V2X      (scenario2_v2x)
---------------------------------------------------------------------
 Each run is: python opencda.py -t <name> -v 0.9.14
   opencda.py loads opencda/scenario_testing/<name>.py (run_scenario)
   and          opencda/scenario_testing/config_yaml/<name>.yaml

 PREREQUISITE: CARLA 0.9.14 must already be running in another window.
   e.g.  cd "C:\CARLA_0.9.14\WindowsNoEditor"; .\CarlaUE4.exe

 Usage (run from the folder this script sits in):
   All four, recommended order:
     powershell -ExecutionPolicy Bypass -File .\run_all_scenarios.ps1
   A subset / custom order:
     powershell -ExecutionPolicy Bypass -File .\run_all_scenarios.ps1 -Scenarios scenario2,scenario2_v2x
   Don't pause for the CARLA reminder (assume it's already up):
     powershell -ExecutionPolicy Bypass -File .\run_all_scenarios.ps1 -NoPrompt
   Keep going even if one scenario fails:
     powershell -ExecutionPolicy Bypass -File .\run_all_scenarios.ps1 -ContinueOnError
   Extra opencda flags:
     ... -ApplyMl -Record
=====================================================================
#>

[CmdletBinding()]
param(
    [string[]]$Scenarios = @("scenario_1_no_v2x","scenario_1_v2x","scenario2","scenario2_v2x"),
    [string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python38\python.exe",
    [string]$CarlaVersion = "0.9.14",
    [switch]$ApplyMl,
    [switch]$Record,
    [switch]$ContinueOnError,
    [switch]$SkipCarlaCheck,
    [switch]$NoPrompt
)

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $RepoRoot

$stamp   = Get-Date -Format "yyyyMMdd_HHmmss"
$logDir  = Join-Path $RepoRoot "run_logs"
if (-not (Test-Path -LiteralPath $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$masterLog = Join-Path $logDir ("run_all_{0}.log" -f $stamp)

function Log($msg, $color = "Gray") {
    Write-Host $msg -ForegroundColor $color
    Add-Content -LiteralPath $masterLog -Value $msg
}

Log ""
Log ("OpenCDA run-all  ({0})" -f $stamp) "Cyan"
Log ("Repo root : {0}" -f $RepoRoot) "Cyan"
Log ("Python    : {0}" -f $Python) "Cyan"
Log ("Scenarios : {0}" -f ($Scenarios -join ", ")) "Cyan"
Log ""

# ---------------------------------------------------------------------
# 0) Sanity checks
# ---------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $Python)) {
    Log "ERROR: Python not found at '$Python'. Pass -Python <path> if it lives elsewhere." "Red"
    return
}
if (-not (Test-Path -LiteralPath (Join-Path $RepoRoot "opencda.py"))) {
    Log "ERROR: opencda.py not found in this folder. Run this script from the OpenCDA folder." "Red"
    return
}

if (-not $SkipCarlaCheck) {
    try {
        $found = & $Python -c "import importlib.metadata as m; print(m.version('carla'))" 2>$null
        if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($found)) {
            Log "WARNING: could not verify the 'carla' package in this Python. Continuing anyway (use -SkipCarlaCheck to silence)." "Yellow"
        } elseif ($found.Trim() -ne $CarlaVersion) {
            Log ("ERROR: expected carla=={0} but found carla=={1} in this Python." -f $CarlaVersion, $found.Trim()) "Red"
            Log "Fix the Python/env, or pass -SkipCarlaCheck to override." "Red"
            return
        } else {
            Log ("carla package: {0}  OK" -f $found.Trim()) "Green"
        }
    } catch {
        Log ("WARNING: carla check failed ({0}). Continuing." -f $_.Exception.Message) "Yellow"
    }
}

# Validate each scenario's required files up front
$valid = @()
foreach ($name in $Scenarios) {
    $py   = Join-Path $RepoRoot ("opencda\scenario_testing\{0}.py" -f $name)
    $yaml = Join-Path $RepoRoot ("opencda\scenario_testing\config_yaml\{0}.yaml" -f $name)
    if (-not (Test-Path -LiteralPath $py)) {
        Log ("SKIP '{0}': missing {1}" -f $name, $py) "Yellow"; continue
    }
    if (-not (Test-Path -LiteralPath $yaml)) {
        Log ("SKIP '{0}': missing {1}" -f $name, $yaml) "Yellow"; continue
    }
    $valid += $name
}
if ($valid.Count -eq 0) { Log "Nothing to run." "Yellow"; return }

# ---------------------------------------------------------------------
# 1) CARLA reminder
# ---------------------------------------------------------------------
Log ""
Log "PREREQUISITE: CARLA $CarlaVersion must be running in another window." "Yellow"
Log '  e.g.  cd "C:\CARLA_0.9.14\WindowsNoEditor"; .\CarlaUE4.exe' "DarkGray"
if (-not $NoPrompt) {
    Read-Host "Press Enter when CARLA is up and ready (Ctrl+C to cancel)"
}

# ---------------------------------------------------------------------
# 2) Run each scenario in order
# ---------------------------------------------------------------------
$results = @()
$idx = 0
foreach ($name in $valid) {
    $idx++
    $runLog = Join-Path $logDir ("{0}_{1}_{2}.log" -f $stamp, $idx, $name)
    Log ""
    Log ("==================================================================") "White"
    Log ("[{0}/{1}] RUN  {2}" -f $idx, $valid.Count, $name) "White"
    Log ("    log -> {0}" -f $runLog) "DarkGray"
    Log ("==================================================================") "White"

    $argsList = @("opencda.py", "-t", $name, "-v", $CarlaVersion)
    if ($ApplyMl) { $argsList += "--apply_ml" }
    if ($Record)  { $argsList += "--record" }

    $start = Get-Date
    & $Python @argsList 2>&1 | Tee-Object -FilePath $runLog
    $code = $LASTEXITCODE
    $dur  = [int]((Get-Date) - $start).TotalSeconds

    $status = if ($code -eq 0) { "OK" } else { "FAIL(code=$code)" }
    $clr    = if ($code -eq 0) { "Green" } else { "Red" }
    Log ("[{0}/{1}] {2}  {3}  ({4}s)" -f $idx, $valid.Count, $name, $status, $dur) $clr
    $results += [pscustomobject]@{ Order=$idx; Scenario=$name; Status=$status; Seconds=$dur; Log=$runLog }

    if ($code -ne 0 -and -not $ContinueOnError) {
        Log ""
        Log "Stopping: '$name' failed and -ContinueOnError was not set." "Red"
        break
    }
}

# ---------------------------------------------------------------------
# 3) Summary
# ---------------------------------------------------------------------
Log ""
Log "================  SUMMARY  ================" "Cyan"
foreach ($r in $results) {
    $clr = if ($r.Status -eq "OK") { "Green" } else { "Red" }
    Log ("  {0}. {1,-22} {2,-14} {3,5}s" -f $r.Order, $r.Scenario, $r.Status, $r.Seconds) $clr
}
Log ("Master log: {0}" -f $masterLog) "Cyan"
Log ""
Log "Results are saved under data_dumping\<scenario_title>\<run_time>\ (scenario.log, scenario_params.yaml, topview_screen\topview.mp4 ...)." "DarkGray"
