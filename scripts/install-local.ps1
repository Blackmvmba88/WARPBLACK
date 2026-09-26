param(
  [string]$ControlRepo = $env:WARPBLACK_CONTROL_REPO,
  [string]$Workspace = $env:WARPBLACK_WORKSPACE
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
if (-not $Workspace) { $Workspace = $HOME }
$Venv = if ($env:WARPBLACK_VENV) { $env:WARPBLACK_VENV } else { Join-Path $Root ".venv" }

$Python = Get-Command python -ErrorAction SilentlyContinue
if (-not $Python) { throw "Python 3.11+ is required" }

& python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 2)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ is required" }

if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
  Write-Host "[WARPBLACK] creating virtual environment"
  & python -m venv $Venv
}

$VenvPython = Join-Path $Venv "Scripts\python.exe"
$Warpblack = Join-Path $Venv "Scripts\warpblack.exe"

Write-Host "[WARPBLACK] installing local package"
& $VenvPython -m pip install --upgrade pip | Out-Null
& $VenvPython -m pip install -e $Root

$Doctor = @("doctor", "--workspace", $Workspace)
if ($ControlRepo) { $Doctor += @("--repo", $ControlRepo) }
& $Warpblack @Doctor
if ($LASTEXITCODE -ne 0) { throw "WARPBLACK doctor found blocking problems" }

if (-not $ControlRepo) {
  Write-Host ""
  Write-Host "WARPBLACK is installed."
  Write-Host "Set WARPBLACK_CONTROL_REPO and run this script again to start the observer."
  exit 0
}

if (-not $env:WARPBLACK_GITHUB_TOKEN) {
  $Gh = Get-Command gh -ErrorAction SilentlyContinue
  if (-not $Gh) { throw "Install GitHub CLI or set WARPBLACK_GITHUB_TOKEN" }
  $env:WARPBLACK_GITHUB_TOKEN = (& gh auth token).Trim()
}

if (-not $env:WARPBLACK_ACTOR) {
  $env:WARPBLACK_ACTOR = (& gh api user --jq .login).Trim()
}

Write-Host "[WARPBLACK] bootstrapping control repo"
& $Warpblack github-bootstrap --repo $ControlRepo --actor $env:WARPBLACK_ACTOR --workspace $Workspace
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "[WARPBLACK] observer online"
& $Warpblack github-watch --repo $ControlRepo --actor $env:WARPBLACK_ACTOR --workspace $Workspace --poll 5
