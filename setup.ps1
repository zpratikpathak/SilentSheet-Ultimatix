Write-Host "=== SilentSheet Setup ==="
Write-Host "Checking prerequisites..."

# Check for Python
if (!(Get-Command "python" -ErrorAction SilentlyContinue)) {
    Write-Warning "Python is not installed or not in your System PATH."
    Write-Warning "Please install Python from https://www.python.org/downloads/ and run this script again."
    exit 1
}
Write-Host "[x] Python is installed."

# Check for PowerShell (Windows PowerShell) in PATH
$psDir = "C:\Windows\System32\WindowsPowerShell\v1.0"
if ($env:PATH -notlike "*$psDir*") {
    Write-Warning "PowerShell directory ($psDir) is not in your System PATH."
    Write-Warning "This is required for toast notifications."
    $addPs = Read-Host "Add it to your User PATH? (y/n)"
    if ($addPs -match "^y(es)?$") {
        $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
        if ($userPath -notlike "*$psDir*") {
            [Environment]::SetEnvironmentVariable("PATH", "$userPath;$psDir", "User")
            $env:PATH = "$env:PATH;$psDir"
            Write-Host "[x] Added PowerShell to User PATH."
        }
    } else {
        Write-Warning "Skipping. Toast notifications may not work."
    }
} else {
    Write-Host "[x] PowerShell is in PATH."
}

# Check for uv
$UseUv = $false
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Write-Host "[x] uv is installed. Will use uv for package management."
    $UseUv = $true
} else {
    Write-Host "[!] uv is not installed. Falling back to standard pip."
}

Write-Host "`n=== Setting up Virtual Environment and Dependencies ==="
if ($UseUv) {
    Write-Host "Creating virtual environment with uv..."
    uv venv
    Write-Host "Installing dependencies with uv..."
    uv sync
} else {
    Write-Host "Creating virtual environment with python -m venv..."
    python -m venv .venv
    Write-Host "Installing dependencies with pip..."
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\pip.exe install -r requirements.txt
}

Write-Host "`n=== Configuration File Setup (config.toml) ==="
$employeeId = Read-Host "Enter your Employee ID"

$taskName = Read-Host "Enter the Task Name [Default: Development]"
if ([string]::IsNullOrWhiteSpace($taskName)) { $taskName = "Development" }

Write-Host "Select Charge Type (Up/Down to move, Enter to select):"

$chargeOptions = @("Billable", "Non Billable")
$selectedIndex = 0
$esc = [char]27

# Draw menu initially
for ($i = 0; $i -lt $chargeOptions.Count; $i++) {
    if ($i -eq $selectedIndex) {
        Write-Host "  > $($chargeOptions[$i])" -ForegroundColor Cyan
    } else {
        Write-Host "    $($chargeOptions[$i])"
    }
}

while ($true) {
    $key = [System.Console]::ReadKey($true)

    if ($key.Key -eq [System.ConsoleKey]::UpArrow) {
        if ($selectedIndex -gt 0) { $selectedIndex-- }
    } elseif ($key.Key -eq [System.ConsoleKey]::DownArrow) {
        if ($selectedIndex -lt ($chargeOptions.Count - 1)) { $selectedIndex++ }
    } elseif ($key.Key -eq [System.ConsoleKey]::Enter) {
        break
    } else {
        continue
    }

    # Move cursor up by the number of options and redraw
    Write-Host "$esc[$($chargeOptions.Count)A" -NoNewline
    for ($i = 0; $i -lt $chargeOptions.Count; $i++) {
        Write-Host "$esc[2K" -NoNewline
        if ($i -eq $selectedIndex) {
            Write-Host "  > $($chargeOptions[$i])" -ForegroundColor Cyan
        } else {
            Write-Host "    $($chargeOptions[$i])"
        }
    }
}

$chargeType = $chargeOptions[$selectedIndex]
Write-Host ("Selected: " + $chargeType)

# Build the TOML content
$configContent = @"
[employee]
EMPLOYEE_ID = "$employeeId"

[timesheet]
task_name = "$taskName"
charge_type = "$chargeType"
"@

# Write the TOML file ensuring UTF-8 without BOM so Python's tomllib can read it cleanly
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText("$PWD\config.toml", $configContent.Trim(), $utf8NoBom)

Write-Host "`n[+] Setup complete! 'config.toml' has been generated."

$enableAuto = Read-Host "`nDo you want to enable auto fill timesheet on Windows startup? (y/n)"
if ($enableAuto -match "^y(es)?$") {
    Write-Host "Installing startup script..."
    if ($UseUv) {
        uv run python setup_startup.py install
    } else {
        .\.venv\Scripts\python.exe setup_startup.py install
    }
}

$runNow = Read-Host "`nDo you want to run SilentSheet now in the background? (y/n)"
if ($runNow -match "^y(es)?$") {
    Write-Host "Starting SilentSheet in the background..."
    if ($UseUv) {
        Start-Process -FilePath "uv" -ArgumentList "run", "pythonw", "fill_timesheet.py", "--headless" -WindowStyle Hidden
    } else {
        Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList "fill_timesheet.py", "--headless" -WindowStyle Hidden
    }
    Write-Host "SilentSheet is now running in the background! You will get a notification when it requires input or completes."
}
