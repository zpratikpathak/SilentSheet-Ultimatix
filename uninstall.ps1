Write-Host "=== SilentSheet Uninstall ==="

# Check for uv
$UseUv = $false
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    $UseUv = $true
}

# Remove from Windows Startup
Write-Host "Removing from Windows Startup..."
if ($UseUv) {
    uv run python setup_startup.py uninstall
} else {
    .\.venv\Scripts\python.exe setup_startup.py uninstall
}

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
