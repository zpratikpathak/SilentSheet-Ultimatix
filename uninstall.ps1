Write-Host "=== SilentSheet Uninstall ==="

# Check for uv
$UseUv = $false
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    $UseUv = $true
}

# Remove from Windows Startup and Task Scheduler
Write-Host "Removing auto-run entries..."
if ($UseUv) {
    uv run python setup_startup.py uninstall-all
} else {
    .\.venv\Scripts\python.exe setup_startup.py uninstall-all
}
# Defensive fallback: remove scheduled task directly in case the Python env is broken
schtasks /delete /tn "SilentSheet" /f 2>$null | Out-Null

# Remove generated files
$filesToRemove = @("config.toml", ".timesheet_done", "silentsheet.log")
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
