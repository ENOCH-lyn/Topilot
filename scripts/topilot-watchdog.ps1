# Keep the current repo's Topilot process running.
param(
    [int]$CheckIntervalSeconds = 20,
    [switch]$RunOnce
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$topilotExe = Join-Path $repoRoot ".venv\Scripts\topilot.exe"
$configPath = Join-Path $HOME ".topilot\config.json"
$logDir = Join-Path $HOME ".topilot\logs"
$logPath = Join-Path $logDir "watchdog.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-GuardLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path $logPath -Value "$timestamp [watchdog] $Message"
}

function Get-ManagedTopilotProcess {
    Get-Process topilot -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -eq $topilotExe }
}

function Start-ManagedTopilot {
    Start-Process -FilePath $topilotExe -ArgumentList "start" -WorkingDirectory $repoRoot -WindowStyle Hidden | Out-Null
    Write-GuardLog "Topilot was not running. Started a new instance."
}

if (-not (Test-Path $topilotExe)) {
    Write-GuardLog "Topilot executable not found: $topilotExe"
    throw "Topilot executable not found: $topilotExe"
}

if (-not (Test-Path $configPath)) {
    Write-GuardLog "Topilot config not found: $configPath"
    throw "Topilot config not found: $configPath"
}

$lastState = ""

while ($true) {
    try {
        $proc = @(Get-ManagedTopilotProcess)
        if ($proc.Count -eq 0) {
            Start-ManagedTopilot
            $lastState = "restarted"
        }
        else {
            if ($lastState -ne "running") {
                Write-GuardLog "Topilot is healthy. pid=$($proc[0].Id)"
                $lastState = "running"
            }
        }
    }
    catch {
        Write-GuardLog "Watchdog check failed: $($_.Exception.Message)"
        $lastState = "error"
    }

    if ($RunOnce) {
        break
    }

    Start-Sleep -Seconds $CheckIntervalSeconds
}
