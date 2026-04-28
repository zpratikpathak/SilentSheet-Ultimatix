<#
.SYNOPSIS
    SilentSheet one-line installer.

.DESCRIPTION
    Downloads the latest setup.ps1 from GitHub and runs it in -Install mode.
    setup.ps1 then downloads the rest of the project archive, extracts it
    into the current folder, runs the full setup wizard, and opens the
    GitHub page when finished.

.EXAMPLE
    # Paste this into PowerShell from any (preferably empty) folder:
    powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/zpratikpathak/SilentSheet-Ultimatix/home/install.ps1 | iex"
#>

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$setupUrl = 'https://raw.githubusercontent.com/zpratikpathak/SilentSheet-Ultimatix/home/setup.ps1'
$tmpSetup = Join-Path $env:TEMP 'silentsheet_install_setup.ps1'

Write-Host ""
Write-Host " Fetching SilentSheet installer..." -ForegroundColor Cyan
try {
    Invoke-WebRequest -Uri $setupUrl -OutFile $tmpSetup -UseBasicParsing
} catch {
    Write-Host ""
    Write-Host " [X] Couldn't download the SilentSheet installer." -ForegroundColor Red
    Write-Host "     $($_.Exception.Message)" -ForegroundColor DarkGray
    exit 1
}

try {
    & $tmpSetup -Install
} finally {
    Remove-Item $tmpSetup -Force -ErrorAction SilentlyContinue
}
