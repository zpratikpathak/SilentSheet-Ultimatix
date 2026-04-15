Write-Host "=== SilentSheet Uninstall ==="

$scriptDir = $PSScriptRoot
if (-not $scriptDir) { $scriptDir = (Get-Item .).FullName }

Write-Host "Stopping background processes..."
$processes = Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -match "^pythonw?\.exe$" -and $_.ExecutablePath -like "$scriptDir\*") -or
    ($_.Name -eq "wscript.exe" -and $_.CommandLine -like "*$scriptDir\*")
}
foreach ($p in $processes) {
    Write-Host "Stopping process $($p.Name) (PID: $($p.ProcessId))..."
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
}

# Check for uv
$UseUv = $false
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    $UseUv = $true
}

# Remove from Windows Startup and Task Scheduler
Write-Host "Removing auto-run entries..."
if (Test-Path ".venv") {
    if ($UseUv) {
        uv run --no-sync python setup_startup.py uninstall-all
    } else {
        .\.venv\Scripts\python.exe setup_startup.py uninstall-all
    }
}
# Direct cleanup in case the Python env is missing or broken
$startupVbs = "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\launch_silentsheet.vbs"
if (Test-Path $startupVbs) {
    Remove-Item $startupVbs -Force
    Write-Host "[x] Removed startup VBS entry."
}
schtasks /delete /tn "SilentSheet" /f 2>$null | Out-Null

# Remove generated files and packages
$filesToRemove = @("config.toml", ".silentsheet_state.json", ".timesheet_done", "silentsheet.log", "silentsheet_launcher.vbs", "silentsheet_retry.vbs")
foreach ($f in $filesToRemove) {
    if (Test-Path $f) {
        Remove-Item $f -Recurse -Force
        Write-Host "[x] Removed $f"
    }
}

# Remove virtual environment
if (Test-Path ".venv") {
    Remove-Item ".venv" -Recurse -Force
    Write-Host "[x] Removed .venv/"
}

# Remove AppUserModelId registry key
$aumidPath = "HKCU:\Software\Classes\AppUserModelId\SilentSheet"
if (Test-Path $aumidPath) {
    try {
        Remove-Item $aumidPath -Recurse -Force -ErrorAction Stop
        Write-Host "[x] Removed AppUserModelId registry key."
    } catch {
        # Silently ignore registry/permission errors
    }
}

Write-Host ""
Write-Host "[+] SilentSheet has been uninstalled." -ForegroundColor Green
Write-Host "You can safely delete this folder now."
Write-Host ""
Read-Host "Press Enter to exit"
 