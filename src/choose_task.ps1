# SilentSheet interactive task picker, launched by silentsheet:choosetask.

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
. (Join-Path $PSScriptRoot 'task_workflow.ps1')

function Exit-WithPause {
    param([int]$Code = 0)
    Read-Host "`nPress Enter to close"
    exit $Code
}
Write-Host ""
Write-Host "  ===========================================" -ForegroundColor Cyan
Write-Host "    SilentSheet - Update Timesheet Task" -ForegroundColor Cyan
Write-Host "  ===========================================" -ForegroundColor Cyan
Write-Host ""
$configPath = Join-Path $projectRoot 'config.toml'
if (-not (Test-Path -LiteralPath $configPath)) {
    Write-Host " [X] config.toml not found at $configPath" -ForegroundColor Red
    Write-Host "     Run setup.ps1 first to create it." -ForegroundColor DarkGray
    Exit-WithPause 1
}

$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$venvPythonW = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$pythonExe = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { 'python.exe' }
$pythonwExe = if (Test-Path -LiteralPath $venvPythonW) { $venvPythonW } else { $pythonExe }

try {
    $employeeId = Get-SilentSheetEmployeeId -PythonExe $pythonExe -ProjectRoot $projectRoot
    Write-Host " [+] Employee ID: $employeeId" -ForegroundColor Green
    Write-Host ""
    Write-Host " [i] Fetching the list of tasks from your timesheet..." -ForegroundColor Cyan
    Write-Host "     Approve the EasyAuth request on your Authenticator app when prompted." -ForegroundColor DarkGray
    Write-Host ""

    $tasks = @(Invoke-TimesheetTaskScrape -PythonExe $pythonExe -ProjectRoot $projectRoot -EmployeeId $employeeId)
    $tasks = @($tasks | ForEach-Object { $_ })
    if ($tasks.Count -eq 0) {
        Write-Host " [!] No tasks were found. The config was left as-is." -ForegroundColor Yellow
        Exit-WithPause 0
    }

    $selected = Select-TimesheetTask -Tasks $tasks
    Write-Host ""
    Write-Host " [+] Selected: $($selected.task_name) [$($selected.charge_type)]" -ForegroundColor Green
    Set-SilentSheetConfig `
        -PythonExe $pythonExe `
        -ProjectRoot $projectRoot `
        -TaskName $selected.task_name `
        -ChargeType $selected.charge_type
    Write-Host " [+] config.toml updated." -ForegroundColor Green

    $fillScript = Join-Path $projectRoot 'fill_timesheet.py'
    Start-Process -FilePath $pythonwExe `
        -ArgumentList @("`"$fillScript`"") `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden | Out-Null
    Write-Host ""
    Write-Host " [+] SilentSheet is retrying in the background." -ForegroundColor Green
    Write-Host "     You will get a Windows toast when EasyAuth is needed or it finishes." -ForegroundColor DarkGray
    Exit-WithPause 0
} catch {
    Write-Host " [X] $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "     A diagnostic report may have been saved to the logs\ folder." -ForegroundColor DarkGray
    Exit-WithPause 1
}
