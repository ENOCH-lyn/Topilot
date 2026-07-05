# Restart Topilot from this repository and re-arm the watchdog.
param(
    [int]$StartupWaitSeconds = 8,
    [switch]$SkipWatchdog
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$topilotExe = Join-Path $repoRoot ".venv\Scripts\topilot.exe"
$installGuardScript = Join-Path $repoRoot "scripts\install-topilot-guard.ps1"
$configPath = Join-Path $HOME ".topilot\config.json"
$logDir = Join-Path $HOME ".topilot\logs"
$logPath = Join-Path $logDir "restart.log"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function Write-RestartLog {
    param([string]$Message)

    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "$timestamp [restart] $Message"
    Add-Content -Path $logPath -Value $line
    Write-Output $line
}

function Get-ChildProcessIds {
    param(
        [int]$ParentProcessId,
        [array]$AllProcesses
    )

    $children = @($AllProcesses | Where-Object { $_.ParentProcessId -eq $ParentProcessId })
    foreach ($child in $children) {
        $child.ProcessId
        Get-ChildProcessIds -ParentProcessId $child.ProcessId -AllProcesses $AllProcesses
    }
}

function Stop-ProcessTree {
    param([int]$RootProcessId)

    $allProcesses = @(Get-CimInstance Win32_Process)
    $processIds = @(Get-ChildProcessIds -ParentProcessId $RootProcessId -AllProcesses $allProcesses) + $RootProcessId
    foreach ($processId in ($processIds | Select-Object -Unique)) {
        Stop-Process -Id $processId -Force -ErrorAction SilentlyContinue
    }
}

function Get-ManagedTopilotRoots {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -eq "topilot.exe" -and
            $_.CommandLine -like "*copilot-in-telegram*" -and
            $_.CommandLine -like "* start*"
        }
}

function Stop-WatchdogProcesses {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -in @("powershell.exe", "pwsh.exe") -and
            $_.CommandLine -like "*topilot-watchdog.ps1*"
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        }
}

function Get-TelegramPendingUpdateCount {
    if (-not (Test-Path $configPath)) {
        return $null
    }

    $config = Get-Content -Path $configPath -Raw | ConvertFrom-Json
    if (-not $config.telegram -or $config.telegram.enabled -eq $false) {
        return $null
    }

    $token = [string]$config.telegram.bot_token
    if ([string]::IsNullOrWhiteSpace($token)) {
        return $null
    }

    $params = @{
        Uri = "https://api.telegram.org/bot$token/getWebhookInfo"
        TimeoutSec = 15
    }
    if ($config.telegram.proxy_url) {
        $params.Proxy = [string]$config.telegram.proxy_url
    }

    $response = Invoke-RestMethod @params
    if (-not $response.ok) {
        throw "Telegram getWebhookInfo returned ok=false"
    }
    return [int]$response.result.pending_update_count
}

if (-not (Test-Path $topilotExe)) {
    throw "Topilot executable not found: $topilotExe"
}

if (-not (Test-Path $configPath)) {
    throw "Topilot config not found: $configPath"
}

Write-RestartLog "Restart requested."

if (-not $SkipWatchdog) {
    Stop-WatchdogProcesses
    Write-RestartLog "Stopped watchdog processes."
}

$topilotRoots = @(Get-ManagedTopilotRoots)
foreach ($process in $topilotRoots) {
    Stop-ProcessTree -RootProcessId $process.ProcessId
}
Write-RestartLog "Stopped Topilot process trees. count=$($topilotRoots.Count)"

Start-Process -FilePath $topilotExe -ArgumentList "start" -WorkingDirectory $repoRoot -WindowStyle Hidden | Out-Null
Write-RestartLog "Started Topilot."

Start-Sleep -Seconds $StartupWaitSeconds

& $topilotExe doctor
if ($LASTEXITCODE -ne 0) {
    throw "topilot doctor failed with exit code $LASTEXITCODE"
}

try {
    $pending = Get-TelegramPendingUpdateCount
    if ($null -ne $pending) {
        Write-RestartLog "Telegram pending_update_count=$pending"
    }
}
catch {
    Write-RestartLog "Telegram health check failed: $($_.Exception.Message)"
}

if (-not $SkipWatchdog) {
    if (-not (Test-Path $installGuardScript)) {
        throw "Watchdog installer not found: $installGuardScript"
    }
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $installGuardScript -StartNow
    if ($LASTEXITCODE -ne 0) {
        throw "install-topilot-guard failed with exit code $LASTEXITCODE"
    }
    Write-RestartLog "Watchdog installed and started."
}

Write-RestartLog "Restart completed."
