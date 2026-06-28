param(
    [Parameter(Mandatory = $true)]
    [Alias("t")]
    [string]$TestScenario,

    [switch]$ApplyMl,
    [switch]$Record,

    [string]$Config,

    [string]$Python = "$env:LOCALAPPDATA\Programs\Python\Python38\python.exe"
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python 3.8 was not found at '$Python'."
}

$CarlaVersion = & $Python -c "import importlib.metadata as m; print(m.version('carla'))"
if ($CarlaVersion -ne "0.9.14") {
    throw "Expected carla==0.9.14 in Python 3.8, but found carla==$CarlaVersion."
}

$ArgsList = @("opencda.py", "-t", $TestScenario, "-v", "0.9.14")
if ($ApplyMl) {
    $ArgsList += "--apply_ml"
}
if ($Record) {
    $ArgsList += "--record"
}
if ($Config) {
    $ArgsList += @("--config", $Config)
}

& $Python @ArgsList
exit $LASTEXITCODE
