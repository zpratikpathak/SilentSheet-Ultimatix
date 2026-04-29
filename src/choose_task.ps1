# SilentSheet - Interactive task picker (arrow-key navigation).
#
# Launched from the "Update Task" toast button via the silentsheet:choosetask
# URL protocol handler in fill_timesheet.py. Replaces the older Python
# numbered-prompt picker (scrape_tasks.py --choose) so the user can navigate
# tasks with the Up/Down arrow keys instead of typing a number.
#
# Always launched via:
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File src\choose_task.ps1
# so it runs even if the user's CurrentUser execution policy is Restricted.

$ErrorActionPreference = 'Stop'

# Lives in <root>\src\choose_task.ps1, so the project root is one level up.
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot


function Select-Option {
    param(
        [string]$Prompt,
        [string[]]$Options,
        [int]$Default = 0
    )

    [System.Console]::CursorVisible = $false

    Write-Host "`n $Prompt" -ForegroundColor Cyan
    Write-Host " (Use Up/Down arrows to move, Enter to select)`n" -ForegroundColor DarkGray

    $sel = $Default
    $esc = [char]27

    for ($i = 0; $i -lt $Options.Count; $i++) {
        if ($i -eq $sel) {
            Write-Host "  > $($Options[$i])" -ForegroundColor Cyan
        } else {
            Write-Host "    $($Options[$i])" -ForegroundColor DarkGray
        }
    }

    while ($true) {
        $key = [System.Console]::ReadKey($true)
        if ($key.Key -eq [System.ConsoleKey]::UpArrow) {
            if ($sel -gt 0) { $sel-- }
        } elseif ($key.Key -eq [System.ConsoleKey]::DownArrow) {
            if ($sel -lt ($Options.Count - 1)) { $sel++ }
        } elseif ($key.Key -eq [System.ConsoleKey]::Enter) {
            break
        } else { continue }

        Write-Host "$esc[$($Options.Count)A" -NoNewline
        for ($i = 0; $i -lt $Options.Count; $i++) {
            Write-Host "$esc[2K" -NoNewline
            if ($i -eq $sel) {
                Write-Host "  > $($Options[$i])" -ForegroundColor Cyan
            } else {
                Write-Host "    $($Options[$i])" -ForegroundColor DarkGray
            }
        }
    }

    [System.Console]::CursorVisible = $true
    return $sel
}


function Exit-WithPause {
    param([int]$Code = 0)
    Read-Host "`nPress Enter to close"
    exit $Code
}


# Banner
Write-Host ""
Write-Host "  ===========================================" -ForegroundColor Cyan
Write-Host "    SilentSheet - Update Timesheet Task" -ForegroundColor Cyan
Write-Host "  ===========================================" -ForegroundColor Cyan
Write-Host ""


# ------------------------------------------------------------
# Step 1: Read EMPLOYEE_ID from config.toml
# ------------------------------------------------------------
$configPath = Join-Path $projectRoot 'config.toml'
if (-not (Test-Path -LiteralPath $configPath)) {
    Write-Host " [X] config.toml not found at $configPath" -ForegroundColor Red
    Write-Host "     Run setup.ps1 first to create it." -ForegroundColor DarkGray
    Exit-WithPause 1
}

$cfgRaw = Get-Content -Raw -LiteralPath $configPath
if ($cfgRaw -notmatch 'EMPLOYEE_ID\s*=\s*"([^"]+)"') {
    Write-Host " [X] Could not read EMPLOYEE_ID from config.toml" -ForegroundColor Red
    Exit-WithPause 1
}
$empId = $Matches[1]
Write-Host " [+] Employee ID: $empId" -ForegroundColor Green


# ------------------------------------------------------------
# Step 2: Pick Python interpreter (prefer project venv)
# ------------------------------------------------------------
$venvPython  = Join-Path $projectRoot '.venv\Scripts\python.exe'
$venvPythonW = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'

if (Test-Path -LiteralPath $venvPython)  { $pythonExe  = $venvPython }  else { $pythonExe  = 'python.exe' }
if (Test-Path -LiteralPath $venvPythonW) { $pythonwExe = $venvPythonW } else { $pythonwExe = $pythonExe }


# ------------------------------------------------------------
# Step 3: Run scrape_tasks.py in the background while a spinner
#         keeps the foreground clean. All Python stdout/stderr is
#         captured silently and only parsed at the end.
# ------------------------------------------------------------
Write-Host ""
Write-Host " [i] Fetching the list of tasks from your timesheet..." -ForegroundColor Cyan
Write-Host "     Approve the EasyAuth request on your Authenticator app when prompted." -ForegroundColor DarkGray
Write-Host ""

$scrapeJob = Start-Job -ScriptBlock {
    param($py, $cwd, $empId)
    Set-Location -LiteralPath $cwd
    & $py (Join-Path 'src' 'scrape_tasks.py') $empId 2>&1 | Out-String
} -ArgumentList $pythonExe, $projectRoot, $empId

# Show loading spinner while the scrape job runs
[System.Console]::CursorVisible = $false
$spinner = @('-', '\', '|', '/')
$spinIdx = 0
while ($scrapeJob.State -eq 'Running') {
    Write-Host "`r  [$($spinner[$spinIdx % 4])] Fetching tasks from timesheet..." -NoNewline -ForegroundColor Cyan
    $spinIdx++
    Start-Sleep -Milliseconds 100
}
Write-Host "`r                                                            `r" -NoNewline
[System.Console]::CursorVisible = $true

$scrapeOutput = Receive-Job -Job $scrapeJob
Remove-Job -Job $scrapeJob

$resultLine = ($scrapeOutput -split "`n") | Where-Object { $_ -match '^SCRAPE_RESULT:' } | Select-Object -Last 1
if (-not $resultLine) {
    Write-Host " [X] Couldn't find SCRAPE_RESULT in the scraper output." -ForegroundColor Red
    Write-Host "     A diagnostic report may have been saved to the logs\ folder." -ForegroundColor DarkGray
    Exit-WithPause 1
}

$jsonStr = ($resultLine -replace '^SCRAPE_RESULT:', '').Trim()
try {
    $tasks = $jsonStr | ConvertFrom-Json
} catch {
    Write-Host " [X] Failed to parse the task list." -ForegroundColor Red
    Write-Host "     Raw payload: $jsonStr"            -ForegroundColor DarkGray
    Exit-WithPause 1
}

if (-not $tasks -or $tasks.Count -eq 0) {
    Write-Host ""
    Write-Host " [!] No tasks were found on the timesheet page." -ForegroundColor Yellow
    Write-Host "     Nothing to update - the config was left as-is." -ForegroundColor DarkGray
    Exit-WithPause 0
}


# ------------------------------------------------------------
# Step 4: Arrow-key picker
# ------------------------------------------------------------
$taskOptions = @()
foreach ($t in $tasks) {
    $taskOptions += "$($t.task_name) [$($t.charge_type)]"
}

$idx = Select-Option -Prompt "Select Task and Charge Type" -Options $taskOptions
$selected   = $tasks[$idx]
$taskName   = $selected.task_name
$chargeType = $selected.charge_type

Write-Host ""
Write-Host " [+] Selected: $taskName [$chargeType]" -ForegroundColor Green


# ------------------------------------------------------------
# Step 5: Rewrite config.toml (preserve EMPLOYEE_ID)
# ------------------------------------------------------------
$newConfig = @"
[employee]
EMPLOYEE_ID = "$empId"

[timesheet]
task_name = "$taskName"
charge_type = "$chargeType"
"@

# Use UTF8NoBOM so tomllib (the Python parser used in fill_timesheet.py) is
# happy. Set-Content -Encoding UTF8 in Windows PowerShell 5.1 emits a BOM,
# but fill_timesheet.py opens the file with utf-8-sig so either is fine.
Set-Content -LiteralPath $configPath -Value $newConfig -Encoding UTF8
Write-Host " [+] config.toml updated." -ForegroundColor Green


# ------------------------------------------------------------
# Step 6: Spawn fill_timesheet.py --headless in the background
# ------------------------------------------------------------
$fillScript = Join-Path $projectRoot 'fill_timesheet.py'
Start-Process -FilePath $pythonwExe `
    -ArgumentList @($fillScript, '--headless') `
    -WorkingDirectory $projectRoot `
    -WindowStyle Hidden | Out-Null

Write-Host ""
Write-Host " [+] SilentSheet is retrying in the background." -ForegroundColor Green
Write-Host "     You will get a Windows toast when EasyAuth is needed or it finishes." -ForegroundColor DarkGray

Exit-WithPause 0
