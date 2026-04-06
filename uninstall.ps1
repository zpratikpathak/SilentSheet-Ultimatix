Write-Host "=== SilentSheet Uninstall ==="

# Check for uv
$UseUv = $false
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    $UseUv = $true
}

# Remove from Windows Startup and Task Scheduler
Write-Host "Removing auto-run entries..."
if (Test-Path ".venv") {
    if ($UseUv) {
        uv run python setup_startup.py uninstall-all
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

# Remove generated files
$filesToRemove = @("config.toml", ".silentsheet_state.json", ".timesheet_done", "silentsheet.log", "silentsheet_launcher.vbs")
foreach ($f in $filesToRemove) {
    if (Test-Path $f) {
        Remove-Item $f
        Write-Host "[x] Removed $f"
    }
}

# Remove virtual environment
if (Test-Path ".venv") {
    Remove-Item ".venv" -Recurse -Force
    Write-Host "[x] Removed .venv/"
}

Write-Host ""
Write-Host "[+] SilentSheet has been uninstalled." -ForegroundColor Green
Write-Host "You can safely delete this folder now."
Write-Host ""
Read-Host "Press Enter to exit"
