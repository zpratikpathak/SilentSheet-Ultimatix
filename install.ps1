<#
.SYNOPSIS
    SilentSheet one-line installer.

.DESCRIPTION
    Downloads the latest setup.ps1 from GitHub into the CURRENT folder and
    runs it in -Install mode. setup.ps1 then downloads the rest of the
    project archive, extracts it into the same folder, runs the full setup
    wizard, and opens the GitHub page when finished.

    Important: the install destination is whatever folder you are sitting
    in when you run this script. Always cd into an empty folder first.

.EXAMPLE
    # cd into an empty folder first, then paste:
    powershell -ExecutionPolicy Bypass -c "irm https://raw.githubusercontent.com/zpratikpathak/SilentSheet-Ultimatix/home/install.ps1 | iex"
#>

$ErrorActionPreference = 'Stop'
$ProgressPreference    = 'SilentlyContinue'

$setupUrl = 'https://raw.githubusercontent.com/zpratikpathak/SilentSheet-Ultimatix/home/setup.ps1'

# Save the bootstrap setup.ps1 to the USER'S current directory (not %TEMP%)
# so that $PSScriptRoot inside setup.ps1 resolves to the intended install
# folder. Use a unique filename so it doesn't collide with the real
# setup.ps1 that gets extracted from the project zip a moment later.
$installDir = $PWD.Path
$tmpSetup   = Join-Path $installDir '_silentsheet_installer.ps1'

Write-Host ""
Write-Host " Installing SilentSheet into: $installDir" -ForegroundColor Cyan
Write-Host ""

try {
    Invoke-WebRequest -Uri $setupUrl -OutFile $tmpSetup -UseBasicParsing
} catch {
    Write-Host " [X] Couldn't download the SilentSheet installer." -ForegroundColor Red
    Write-Host "     $($_.Exception.Message)" -ForegroundColor DarkGray
    exit 1
}

try {
    & $tmpSetup -Install
} finally {
    Remove-Item $tmpSetup -Force -ErrorAction SilentlyContinue
}
