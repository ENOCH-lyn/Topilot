# Install a login-time watchdog for the current repo's Topilot process.
param(
    [string]$TaskName = "TopilotGuard",
    [switch]$StartNow
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$watchdogScript = Join-Path $repoRoot "scripts\topilot-watchdog.ps1"
$powershellExe = Join-Path $PSHOME "powershell.exe"
$userId = if ($env:USERDOMAIN) { "$($env:USERDOMAIN)\$($env:USERNAME)" } else { $env:USERNAME }

if (-not (Test-Path $watchdogScript)) {
    throw "Watchdog script not found: $watchdogScript"
}

# Remove any older copy of the task before replacing it.
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$actionArgs = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$watchdogScript`""
$action = New-ScheduledTaskAction -Execute $powershellExe -Argument $actionArgs
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $userId
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)
$principal = New-ScheduledTaskPrincipal -UserId $userId -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

if ($StartNow) {
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.Name -eq "powershell.exe" -and
            $_.CommandLine -like "*topilot-watchdog.ps1*"
        } |
        ForEach-Object {
            if ($_.CommandLine -notlike "*install-topilot-guard.ps1*") {
                Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            }
        }

    Start-Process -FilePath $powershellExe -ArgumentList $actionArgs -WorkingDirectory $repoRoot -WindowStyle Hidden | Out-Null
}

Write-Output "Installed scheduled task: $TaskName"
Write-Output "Watchdog script: $watchdogScript"
if ($StartNow) {
    Write-Output "Watchdog started in background."
}
