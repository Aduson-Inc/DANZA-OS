[CmdletBinding()]
param(
    [switch]$Yes,
    [switch]$NoOpen,
    [string]$Target = (Get-Location).Path
)

$ErrorActionPreference = "Stop"
$Repository = "https://github.com/Aduson-Inc/DANZA-OS"
$Branch = "codex/production-danzaboss-install-flow"
$RawBase = "https://raw.githubusercontent.com/Aduson-Inc/DANZA-OS/$Branch"

function Fail([string]$Message) {
    Write-Error "[DANZABOSS] $Message"
    exit 2
}

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Fail "Python 3.10+ is required. Install Python, then rerun this command."
}
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "Git is required. Install Git, then rerun this command."
}
$version = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
$parts = $version.Trim().Split('.')
if ([int]$parts[0] -lt 3 -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -lt 10)) {
    Fail "Python 3.10+ is required; found $version."
}

Write-Host "[DANZABOSS] Source: $Repository@$Branch"
Write-Host "[DANZABOSS] Mandatory dependencies: Python 3.10+, Git."
Write-Host "[DANZABOSS] Optional: tmux is not required or auto-installed."
Write-Host "[DANZABOSS] The installer will create a project-local runtime, install"
Write-Host "[DANZABOSS] DANZABOSS, activate CORTEX, verify the UI, and open port 33000."
if (-not $Yes -and $env:DANZA_APPROVE -ne "1") {
    $answer = Read-Host "Approve installation in this folder? [y/N]"
    if ($answer -notmatch '^(?i:y|yes)$') { Fail "Installation cancelled before changes were made." }
}

$temp = Join-Path ([System.IO.Path]::GetTempPath()) ("danza-install-" + [guid]::NewGuid() + ".py")
try {
    Invoke-WebRequest -UseBasicParsing -Uri "$RawBase/install.py" -OutFile $temp
    $args = @($temp, "--target", $Target, "--branch", $Branch)
    if ($NoOpen) { $args += "--no-open" }
    & python @args
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    Remove-Item -Force -ErrorAction SilentlyContinue $temp
}
