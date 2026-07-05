# Keep the current repo's Topilot process running.
param(
    [int]$CheckIntervalSeconds = 20,
    [int]$TelegramPendingRestartThreshold = 2,
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

function Stop-ManagedTopilot {
    param([array]$Processes)

    foreach ($proc in $Processes) {
        Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    }
}

function Start-ManagedTopilot {
    Start-Process -FilePath $topilotExe -ArgumentList "start" -WorkingDirectory $repoRoot -WindowStyle Hidden | Out-Null
    Write-GuardLog "Topilot was not running. Started a new instance."
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

    $uri = "https://api.telegram.org/bot$token/getWebhookInfo"
    $params = @{
        Uri = $uri
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
    Write-GuardLog "Topilot executable not found: $topilotExe"
    throw "Topilot executable not found: $topilotExe"
}

if (-not (Test-Path $configPath)) {
    Write-GuardLog "Topilot config not found: $configPath"
    throw "Topilot config not found: $configPath"
}

$lastState = ""
$telegramPendingStreak = 0

while ($true) {
    try {
        $proc = @(Get-ManagedTopilotProcess)
        if ($proc.Count -eq 0) {
            Start-ManagedTopilot
            $lastState = "restarted"
            $telegramPendingStreak = 0
        }
        else {
            try {
                $pendingCount = Get-TelegramPendingUpdateCount
                if ($null -ne $pendingCount -and $pendingCount -gt 0) {
                    $telegramPendingStreak += 1
                    Write-GuardLog "Telegram pending updates detected. pending=$pendingCount streak=$telegramPendingStreak"
                    if ($telegramPendingStreak -ge $TelegramPendingRestartThreshold) {
                        Write-GuardLog "Telegram polling appears stuck. Restarting Topilot. pending=$pendingCount"
                        Stop-ManagedTopilot -Processes $proc
                        Start-Sleep -Seconds 2
                        Start-ManagedTopilot
                        $lastState = "restarted"
                        $telegramPendingStreak = 0
                    }
                }
                else {
                    $telegramPendingStreak = 0
                }
            }
            catch {
                Write-GuardLog "Telegram health check skipped: $($_.Exception.Message)"
            }

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
