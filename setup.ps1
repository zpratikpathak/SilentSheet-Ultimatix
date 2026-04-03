Write-Host "=== SilentSheet Setup ==="
Write-Host "Checking prerequisites..."

$missing = @()

# Check for Python
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    Write-Host "[x] Python is installed."
} else {
    Write-Host "[ ] Python is NOT installed." -ForegroundColor Red
    $missing += @{ Name = "Python"; WingetId = "Python.Python.3.13" }
}

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

# Check for Google Chrome
$chromePaths = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chromeFound = $false
foreach ($p in $chromePaths) {
    if (Test-Path $p) { $chromeFound = $true; break }
}
if ($chromeFound) {
    Write-Host "[x] Google Chrome is installed."
} else {
    Write-Host "[ ] Google Chrome is NOT installed." -ForegroundColor Red
    $missing += @{ Name = "Google Chrome"; WingetId = "Google.Chrome" }
}

# Check for uv
$UseUv = $false
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Write-Host "[x] uv is installed. Will use uv for package management."
    $UseUv = $true
} else {
    Write-Host "[!] uv is not installed. Falling back to standard pip."
}

# Offer to install missing software via winget
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "The following software is missing:" -ForegroundColor Yellow
    foreach ($m in $missing) {
        Write-Host "  - $($m.Name)" -ForegroundColor Yellow
    }
    Write-Host ""

    if (!(Get-Command "winget" -ErrorAction SilentlyContinue)) {
        Write-Warning "winget is not available on this system. Please install the missing software manually and re-run this script."
        exit 1
    }

    $installChoice = Read-Host "Would you like to install them using winget? (y/n)"
    if ($installChoice -match "^y(es)?$") {
        foreach ($m in $missing) {
            Write-Host "Installing $($m.Name) (winget install $($m.WingetId))..." -ForegroundColor Cyan
            winget install --id $m.WingetId --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -ne 0) {
                Write-Warning "Failed to install $($m.Name). You may need to install it manually."
            } else {
                Write-Host "[x] $($m.Name) installed successfully." -ForegroundColor Green
            }
        }

        # Refresh PATH so newly installed tools are available in this session
        $machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
        $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
        $env:PATH = "$machinePath;$userPath"

        # Re-check critical prerequisites after installation
        if (!(Get-Command "python" -ErrorAction SilentlyContinue)) {
            Write-Warning "Python is still not found in PATH after installation."
            Write-Warning "Please restart your terminal or add Python to PATH manually, then re-run this script."
            exit 1
        }

        $chromeFound = $false
        foreach ($p in $chromePaths) {
            if (Test-Path $p) { $chromeFound = $true; break }
        }
        if (-not $chromeFound) {
            Write-Warning "Google Chrome is still not found after installation."
            Write-Warning "Please restart your terminal and re-run this script."
            exit 1
        }

        Write-Host "[x] All prerequisites are now installed." -ForegroundColor Green
    } else {
        Write-Warning "Cannot continue without: $(($missing | ForEach-Object { $_.Name }) -join ', '). Exiting."
        exit 1
    }
}

Write-Host "`n=== Setting up Virtual Environment and Dependencies ==="
if ($UseUv) {
    Write-Host "Creating virtual environment with uv..."
    uv venv
    Write-Host "Installing dependencies with uv..."
    uv sync
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Dependency installation failed. Check your network connection and try again."
        exit 1
    }
} else {
    Write-Host "Creating virtual environment with python -m venv..."
    python -m venv .venv
    Write-Host "Installing dependencies with pip..."
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\pip.exe install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Dependency installation failed. Check your network connection and try again."
        exit 1
    }
}
Write-Host "[x] Dependencies installed successfully."

Write-Host "`n=== Configuration File Setup (config.toml) ==="
if (Test-Path "config.toml") {
    Write-Host "Existing config.toml found."
    $overwrite = Read-Host "Overwrite it? (y/n)"
    if ($overwrite -notmatch "^y(es)?$") {
        Write-Host "Keeping existing config.toml."
        $skipConfig = $true
    } else {
        $skipConfig = $false
    }
} else {
    $skipConfig = $false
}

if (-not $skipConfig) {

do {
    $employeeId = (Read-Host "Enter your Employee ID").Trim()
    if ([string]::IsNullOrWhiteSpace($employeeId)) {
        Write-Warning "Employee ID cannot be empty. Please try again."
    }
} while ([string]::IsNullOrWhiteSpace($employeeId))

$taskName = Read-Host "Enter the Task Name [Default: Development]"
if ([string]::IsNullOrWhiteSpace($taskName)) { $taskName = "Development" }

Write-Host "Billable or Non Billable? (Up/Down to move, Enter to select):"

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
Write-Host "[x] config.toml generated."

} # end if (-not $skipConfig)

$startupEnabled = $false
$enableAuto = Read-Host "`nDo you want to enable auto fill timesheet on Windows startup? (y/n)"
if ($enableAuto -match "^y(es)?$") {
    Write-Host "Installing startup script..."
    if ($UseUv) {
        uv run python setup_startup.py install
    } else {
        .\.venv\Scripts\python.exe setup_startup.py install
    }
    $startupEnabled = $true
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

# Read back the config for the summary
Write-Host "`n=== Setup Summary ==="
if (Test-Path "config.toml") {
    $cfgRaw = Get-Content "config.toml" -Raw
    if ($cfgRaw -match 'EMPLOYEE_ID\s*=\s*"([^"]*)"') { $sumId = $Matches[1] } else { $sumId = "?" }
    if ($cfgRaw -match 'task_name\s*=\s*"([^"]*)"')    { $sumTask = $Matches[1] } else { $sumTask = "?" }
    if ($cfgRaw -match 'charge_type\s*=\s*"([^"]*)"')   { $sumCharge = $Matches[1] } else { $sumCharge = "?" }
    Write-Host "  Employee ID  : $sumId"
    Write-Host "  Task Name    : $sumTask"
    Write-Host "  Charge Type  : $sumCharge"
}
Write-Host "  Pkg Manager  : $(if ($UseUv) { 'uv' } else { 'pip' })"
Write-Host "  Auto Startup : $(if ($startupEnabled) { 'Enabled' } else { 'Disabled' })"
Write-Host ""
Write-Host "[+] Setup complete!" -ForegroundColor Green
