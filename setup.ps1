param(
    [switch]$Update,
    [switch]$Install
)

# Treat Install and Update as the same internal "bootstrap" mode (download
# the latest archive, extract over the project root, then run normal setup).
# The two flags only differ in the banner text shown to the user.
$bootstrapMode = $Update -or $Install

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

function Select-YesNo {
    param(
        [string]$Prompt,
        [int]$Default = 0
    )
    $idx = Select-Option -Prompt $Prompt -Options @("Yes", "No") -Default $Default
    return $idx -eq 0
}

# --- NEW BOLD HEADER SYSTEM ---
$global:stepCounter = 1

function Write-Header {
    param([string]$Title)
    
    # ADDED: 1.5 second pause before jumping to the next section
    Start-Sleep -Milliseconds 1500 
    
    Write-Host "`n"
    Write-Host "======================================================================" -ForegroundColor Blue
    Write-Host "  STEP $global:stepCounter | $($Title.ToUpper())" -ForegroundColor Cyan
    Write-Host "======================================================================" -ForegroundColor Blue
    Write-Host ""
    $global:stepCounter++
}
# ------------------------------

function Invoke-LoadingAnimation {
    param(
        [string]$Message,
        [int]$DurationSeconds = 2
    )
    [System.Console]::CursorVisible = $false
    $spinner = @('-', '\', '|', '/')
    $iterations = $DurationSeconds * 10
    
    for ($i = 0; $i -lt $iterations; $i++) {
        Write-Host "`r  [$($spinner[$i % 4])] $Message..." -NoNewline -ForegroundColor Cyan
        Start-Sleep -Milliseconds 100
    }
    
    Write-Host "`r                                                            `r" -NoNewline
    [System.Console]::CursorVisible = $true
}

function Write-ErrorReport {
    param(
        [string]$Context,
        [string]$Message,
        [string]$Details = ""
    )
    try {
        $logsDir = Join-Path $PWD.Path "logs"
        if (-not (Test-Path $logsDir)) {
            New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
        }
        $ts = Get-Date -Format "yyyy-MM-dd_HH-mm-ss"
        $md = Join-Path $logsDir "${ts}_error.md"

        $fence = [string]::new('`', 3)
        $when  = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        $lines = @(
            "# SilentSheet error report",
            "",
            "**When:** $when",
            "**Where:** $Context (setup.ps1)",
            "",
            "## Error",
            "",
            $Message,
            ""
        )
        if ($Details) {
            $lines += @(
                "## Details",
                "",
                "${fence}text",
                $Details,
                $fence,
                ""
            )
        }
        Set-Content -Path $md -Value ($lines -join "`r`n") -Encoding UTF8
        Write-Host " [i] Diagnostic report saved to $md" -ForegroundColor DarkGray
    } catch {
        # Last-resort: never let logging itself crash the script.
    }
}

# --- Setup Start ---
Clear-Host

# Always run from the script's own directory so cwd-relative paths
# (.\.venv\Scripts\..., .\setup.ps1, .\config.toml, etc.) and the
# update-flow extraction target resolve to the install folder no
# matter how the script was launched.
if ($PSScriptRoot) { Set-Location -LiteralPath $PSScriptRoot }

$banner = @"
  ____  _ _            _   ____  _               _   
 / ___|(_) | ___ _ __ | |_/ ___|| |__   ___  ___| |_ 
 \___ \| | |/ _ \ '_ \| __\___ \| '_ \ / _ \/ _ \ __|
  ___) | | |  __/ | | | |_ ___) | | | |  __/  __/ |_ 
 |____/|_|_|\___|_| |_|\__|____/|_| |_|\___|\___|\__|
"@

Write-Host $banner -ForegroundColor Cyan
$bannerSubtitle = if ($Install) {
    "INSTALLING SILENTSHEET"
} elseif ($Update) {
    "UPDATING TO LATEST VERSION"
} else {
    "SETUP CONFIGURATION"
}
Write-Host "                                   $bannerSubtitle`n" -ForegroundColor DarkGray

# Simulate a brief loading sequence for premium feel
$initMessage = if ($Install) {
    "Preparing Installation Environment"
} elseif ($Update) {
    "Preparing Update Environment"
} else {
    "Initializing Setup Environment"
}
Invoke-LoadingAnimation -Message $initMessage -DurationSeconds 3
Write-Host " [+] Environment Initialized." -ForegroundColor Green


if ($bootstrapMode) {
    # ==========================================
    $bootstrapHeader = if ($Install) { "Downloading SilentSheet" } else { "Downloading Update" }
    Write-Header $bootstrapHeader
    # ==========================================

    # Prefer $PSScriptRoot (always the folder containing this .ps1) so the
    # extraction can never accidentally land in the wrong directory if the
    # script is invoked from a different cwd. Falls back to $PWD only if
    # $PSScriptRoot isn't set (e.g. piped via stdin).
    $projectRoot = if ($PSScriptRoot) { $PSScriptRoot } else { $PWD.Path }
    $zipUrl  = "https://github.com/zpratikpathak/SilentSheet-Ultimatix/archive/refs/heads/home.zip"
    $tmpZip  = Join-Path $env:TEMP "silentsheet_update.zip"
    $tmpDir  = Join-Path $env:TEMP "silentsheet_update"

    # Step 1: Stop any running SilentSheet processes so we can overwrite locked
    # files (.venv\Scripts\python*.exe, favicon.ico, etc.). Mirrors uninstall.ps1.
    Write-Host " Stopping running SilentSheet processes..." -ForegroundColor Cyan
    try {
        $running = Get-CimInstance Win32_Process -ErrorAction Stop | Where-Object {
            ($_.Name -match "^pythonw?\.exe$" -and $_.ExecutablePath -like "$projectRoot\*") -or
            ($_.Name -eq "wscript.exe" -and $_.CommandLine -like "*$projectRoot\*")
        }
        $stoppedCount = 0
        foreach ($p in $running) {
            Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
            $stoppedCount++
        }
        if ($stoppedCount -gt 0) {
            Write-Host " [+] Stopped $stoppedCount background process(es)." -ForegroundColor Green
            # Give the OS a moment to release file handles
            Start-Sleep -Milliseconds 800
        } else {
            Write-Host " [+] No background processes were running." -ForegroundColor Green
        }
    } catch {
        Write-Host " [!] Could not enumerate processes: $_" -ForegroundColor Yellow
    }

    # Step 2: Download the latest archive from GitHub
    Write-Host " Downloading latest release from GitHub..." -ForegroundColor Cyan
    if (Test-Path $tmpZip) { Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue }
    if (Test-Path $tmpDir) { Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue }

    $downloadJob = Start-Job -ScriptBlock {
        param($url, $out)
        try {
            $ProgressPreference = 'SilentlyContinue'
            Invoke-WebRequest -Uri $url -OutFile $out -UseBasicParsing -ErrorAction Stop
            return @{ Success = $true; Error = $null }
        } catch {
            return @{ Success = $false; Error = $_.Exception.Message }
        }
    } -ArgumentList $zipUrl, $tmpZip

    [System.Console]::CursorVisible = $false
    $spinner = @('-', '\', '|', '/')
    $spinIdx = 0
    while ($downloadJob.State -eq 'Running') {
        Write-Host "`r  [$($spinner[$spinIdx % 4])] Downloading update package..." -NoNewline -ForegroundColor Cyan
        $spinIdx++
        Start-Sleep -Milliseconds 100
    }
    Write-Host "`r                                                            `r" -NoNewline
    [System.Console]::CursorVisible = $true

    $downloadResult = Receive-Job -Job $downloadJob
    Remove-Job -Job $downloadJob

    if (-not $downloadResult.Success -or -not (Test-Path $tmpZip)) {
        Write-ErrorReport -Context "Downloading update package" `
            -Message "Failed to download the update archive from GitHub." `
            -Details $downloadResult.Error
        Write-Host " [X] Couldn't download the update. See logs folder for details." -ForegroundColor Red
        Write-Host "     Check your internet connection and try again." -ForegroundColor DarkGray
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host " [+] Update package downloaded." -ForegroundColor Green

    # Step 3: Extract the archive to a temp folder
    Write-Host " Extracting update package..." -ForegroundColor Cyan
    try {
        Expand-Archive -Path $tmpZip -DestinationPath $tmpDir -Force -ErrorAction Stop
    } catch {
        Write-ErrorReport -Context "Extracting update package" `
            -Message "Failed to extract the downloaded update archive." `
            -Details "$_"
        Write-Host " [X] Couldn't extract the update. See logs folder for details." -ForegroundColor Red
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        Read-Host "Press Enter to exit"
        exit 1
    }

    # GitHub archives wrap everything in a single top-level folder
    # (e.g. SilentSheet-Ultimatix-home). Locate it.
    $extractedRoot = Get-ChildItem -Path $tmpDir -Directory | Select-Object -First 1
    if (-not $extractedRoot) {
        Write-ErrorReport -Context "Extracting update package" `
            -Message "The downloaded update archive did not contain the expected top-level folder." `
            -Details "Inspected: $tmpDir"
        Write-Host " [X] The update package looks empty or malformed. See logs folder for details." -ForegroundColor Red
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host " [+] Update package extracted." -ForegroundColor Green

    # Step 4: Copy contents over the project root (overwrite). User-state files
    # (config.toml, .silentsheet_state.json, .venv\, *.log, *.vbs) are gitignored
    # and therefore not in the zip, so they are preserved automatically.
    Write-Host " Applying update files..." -ForegroundColor Cyan
    try {
        Copy-Item -Path (Join-Path $extractedRoot.FullName "*") -Destination $projectRoot -Recurse -Force -ErrorAction Stop
    } catch {
        Write-ErrorReport -Context "Applying update files" `
            -Message "Failed to copy the new files over the project root." `
            -Details "$_"
        Write-Host " [X] Couldn't apply the update. See logs folder for details." -ForegroundColor Red
        Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
        Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host " [+] Files updated successfully." -ForegroundColor Green

    # Step 5: Cleanup
    Remove-Item $tmpZip -Force -ErrorAction SilentlyContinue
    Remove-Item $tmpDir -Recurse -Force -ErrorAction SilentlyContinue
}


# ==========================================
Write-Header "Checking System Prerequisites"
# ==========================================

$missing = @()

# Check for Python
Invoke-LoadingAnimation -Message "Locating Python" -DurationSeconds 2
if (Get-Command "python" -ErrorAction SilentlyContinue) {
    Write-Host " [+] Python is installed." -ForegroundColor Green
} else {
    Write-Host " [X] Python is NOT installed." -ForegroundColor Red
    $missing += @{ Name = "Python"; WingetId = "Python.Python.3.13" }
}

# Check for PowerShell (Windows PowerShell) in PATH
$psDir = "C:\Windows\System32\WindowsPowerShell\v1.0"
Invoke-LoadingAnimation -Message "Checking System PATH" -DurationSeconds 2
if ($env:PATH -notlike "*$psDir*") {
    Write-Host " [!] PowerShell directory ($psDir) is not in your System PATH." -ForegroundColor Yellow
    Write-Host "     This is required for toast notifications." -ForegroundColor DarkGray
    if (Select-YesNo "Add it to your User PATH?") {
        $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
        if ($userPath -notlike "*$psDir*") {
            [Environment]::SetEnvironmentVariable("PATH", "$userPath;$psDir", "User")
            $env:PATH = "$env:PATH;$psDir"
            Write-Host " [+] Added PowerShell to User PATH." -ForegroundColor Green
        }
    } else {
        Write-Host " [!] Skipping. Toast notifications may not work." -ForegroundColor Yellow
    }
} else {
    Write-Host " [+] PowerShell is in PATH." -ForegroundColor Green
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
Invoke-LoadingAnimation -Message "Locating Google Chrome" -DurationSeconds 2
if ($chromeFound) {
    Write-Host " [+] Google Chrome is installed." -ForegroundColor Green
} else {
    Write-Host " [X] Google Chrome is NOT installed." -ForegroundColor Red
    $missing += @{ Name = "Google Chrome"; WingetId = "Google.Chrome" }
}

# Check for uv
Invoke-LoadingAnimation -Message "Checking Package Managers" -DurationSeconds 2
$UseUv = $false
if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Write-Host " [+] uv is installed. Will use uv for package management." -ForegroundColor Green
    $UseUv = $true
} else {
    Write-Host " [!] uv is not installed. Falling back to standard pip." -ForegroundColor Yellow
}

# Offer to install missing software via winget
if ($missing.Count -gt 0) {
    Write-Host "`n The following software is missing:" -ForegroundColor Yellow
    foreach ($m in $missing) {
        Write-Host "  - $($m.Name)" -ForegroundColor Yellow
    }

    if (!(Get-Command "winget" -ErrorAction SilentlyContinue)) {
        Write-ErrorReport -Context "Checking prerequisites" `
            -Message "winget is not available on this system, so SilentSheet cannot auto-install missing software." `
            -Details ("Missing: " + (($missing | ForEach-Object { $_.Name }) -join ', '))
        Write-Host "`n [X] winget is not available on this system. Please install the missing software manually and re-run this script." -ForegroundColor Red
        exit 1
    }

    if (Select-YesNo "Would you like to install them using winget?") {
        foreach ($m in $missing) {
            Write-Host "`n Installing $($m.Name) (winget install $($m.WingetId))...." -ForegroundColor Cyan
            winget install --id $m.WingetId --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -ne 0) {
                Write-Host " [!] Failed to install $($m.Name). You may need to install it manually." -ForegroundColor Red
            } else {
                Write-Host " [+] $($m.Name) installed successfully." -ForegroundColor Green
            }
        }

        # Refresh PATH so newly installed tools are available in this session
        $machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
        $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
        $env:PATH = "$machinePath;$userPath"

        # Re-check critical prerequisites after installation
        if (!(Get-Command "python" -ErrorAction SilentlyContinue)) {
            Write-ErrorReport -Context "Verifying Python after install" `
                -Message "Python was installed via winget but is still not on PATH." `
                -Details "User likely needs to restart the terminal or add Python to PATH manually."
            Write-Host "`n [X] Python is still not found in PATH after installation." -ForegroundColor Red
            Write-Host "     Please restart your terminal or add Python to PATH manually, then re-run this script." -ForegroundColor DarkGray
            exit 1
        }

        $chromeFound = $false
        foreach ($p in $chromePaths) {
            if (Test-Path $p) { $chromeFound = $true; break }
        }
        if (-not $chromeFound) {
            Write-ErrorReport -Context "Verifying Google Chrome after install" `
                -Message "Google Chrome was installed via winget but the executable was not found in any of the expected locations." `
                -Details ("Searched: " + ($chromePaths -join '; '))
            Write-Host "`n [X] Google Chrome is still not found after installation." -ForegroundColor Red
            Write-Host "     Please restart your terminal and re-run this script." -ForegroundColor DarkGray
            exit 1
        }

        Write-Host "`n [+] All prerequisites are now installed." -ForegroundColor Green
    } else {
        $missingNames = ($missing | ForEach-Object { $_.Name }) -join ', '
        Write-ErrorReport -Context "Checking prerequisites" `
            -Message "User declined to install missing prerequisites." `
            -Details "Missing: $missingNames"
        Write-Host "`n [X] Cannot continue without: $missingNames. Exiting." -ForegroundColor Red
        exit 1
    }
}


# ==========================================
Write-Header "Environment & Dependencies"
# ==========================================

if ($UseUv) {
    Write-Host " Creating virtual environment with uv..." -ForegroundColor Cyan
    uv venv | Out-Null
    if (Test-Path "packages") {
        Write-Host " Installing dependencies from local packages..." -ForegroundColor Cyan
        uv pip install --no-index --find-links=packages -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Write-Host " [!] Offline installation failed. Falling back to online installation..." -ForegroundColor Yellow
            uv pip install -r requirements.txt
            if ($LASTEXITCODE -ne 0) {
                Write-ErrorReport -Context "Installing Python dependencies (uv, online fallback)" `
                    -Message "uv failed to install dependencies after falling back to online mode." `
                    -Details "uv pip install -r requirements.txt exited with code $LASTEXITCODE"
                Write-Host " [X] Couldn't install Python dependencies. See logs folder for details." -ForegroundColor Red
                exit 1
            }
        }
    } else {
        Write-Host " Downloading dependencies from the internet with uv..." -ForegroundColor Cyan
        uv pip install -r requirements.txt
        if ($LASTEXITCODE -ne 0) {
            Write-ErrorReport -Context "Installing Python dependencies (uv, online)" `
                -Message "uv failed to install dependencies from the internet." `
                -Details "uv pip install -r requirements.txt exited with code $LASTEXITCODE"
            Write-Host " [X] Couldn't install Python dependencies. See logs folder for details." -ForegroundColor Red
            exit 1
        }
    }
} else {
    Write-Host " Creating virtual environment with python -m venv..." -ForegroundColor Cyan
    python -m venv .venv
    if (Test-Path "packages") {
        Write-Host " Installing dependencies from local packages with pip..." -ForegroundColor Cyan
        .\.venv\Scripts\pip.exe install --no-index --find-links=packages -r requirements.txt | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host " [!] Offline installation failed. Falling back to online installation..." -ForegroundColor Yellow
            .\.venv\Scripts\pip.exe install -r requirements.txt | Out-Null
            if ($LASTEXITCODE -ne 0) {
                Write-ErrorReport -Context "Installing Python dependencies (pip, online fallback)" `
                    -Message "pip failed to install dependencies after falling back to online mode." `
                    -Details ".\.venv\Scripts\pip.exe install -r requirements.txt exited with code $LASTEXITCODE"
                Write-Host " [X] Couldn't install Python dependencies. See logs folder for details." -ForegroundColor Red
                exit 1
            }
        }
    } else {
        Write-Host " Downloading dependencies from the internet with pip..." -ForegroundColor Cyan
        .\.venv\Scripts\pip.exe install -r requirements.txt | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-ErrorReport -Context "Installing Python dependencies (pip, online)" `
                -Message "pip failed to install dependencies from the internet." `
                -Details ".\.venv\Scripts\pip.exe install -r requirements.txt exited with code $LASTEXITCODE"
            Write-Host " [X] Couldn't install Python dependencies. See logs folder for details." -ForegroundColor Red
            exit 1
        }
    }
}
Write-Host " [+] Dependencies configured successfully." -ForegroundColor Green


# ==========================================
Write-Header "Timesheet Configuration"
# ==========================================

if (Test-Path "config.toml") {
    Write-Host " [i] Existing config.toml found." -ForegroundColor Cyan
    if (-not (Select-YesNo "Overwrite existing configuration?" -Default 1)) {
        Write-Host "     Keeping existing config.toml." -ForegroundColor DarkGray
        $skipConfig = $true
    } else {
        $skipConfig = $false
    }
} else {
    $skipConfig = $false
}

if (-not $skipConfig) {
    do {
        Write-Host "`n Employee ID / Username: " -NoNewline -ForegroundColor White
        $employeeId = (Read-Host).Trim()
        if ([string]::IsNullOrWhiteSpace($employeeId)) {
            Write-Host " [!] Employee ID cannot be empty. Please try again." -ForegroundColor Yellow
        }
    } while ([string]::IsNullOrWhiteSpace($employeeId))

    $taskName = "Development"
    $chargeType = "Billable"
    $scrapeSuccess = $false

    # Check internet connectivity before attempting to scrape
    $internetAvailable = $false
    try {
        $null = Test-Connection -ComputerName "www.google.com" -Count 1 -Quiet -ErrorAction Stop
        $internetAvailable = $true
    } catch {
        $internetAvailable = $false
    }
    if (-not $internetAvailable) {
        # Fallback: try a direct TCP connection to port 443
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $tcp.Connect("www.google.com", 443)
            $tcp.Close()
            $internetAvailable = $true
        } catch {
            $internetAvailable = $false
        }
    }

    if ($internetAvailable) {
    Write-Host ""
    Write-Host " [i] Detecting available tasks from the timesheet..." -ForegroundColor Cyan
    Write-Host "     Approve the EasyAuth request on your Authenticator app when prompted." -ForegroundColor DarkGray
    Write-Host ""

        # Run the standalone scrape script in a background job with a loading animation
        if ($UseUv) {
            $scrapeJob = Start-Job -ScriptBlock {
                param($dir, $empId)
                Set-Location $dir
                uv run --no-sync python scrape_tasks.py $empId 2>&1 | Out-String
            } -ArgumentList $PWD, $employeeId
        } else {
            $scrapeJob = Start-Job -ScriptBlock {
                param($dir, $empId)
                Set-Location $dir
                & "$dir\.venv\Scripts\python.exe" scrape_tasks.py $empId 2>&1 | Out-String
            } -ArgumentList $PWD, $employeeId
        }

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

        # Find the SCRAPE_RESULT: line and parse the JSON
        $resultLine = ($scrapeOutput -split "`n") | Where-Object { $_ -match "^SCRAPE_RESULT:" } | Select-Object -Last 1
        if ($resultLine) {
            $jsonStr = $resultLine -replace "^SCRAPE_RESULT:", ""
            try {
                $tasks = $jsonStr | ConvertFrom-Json
                if ($tasks.Count -gt 0) {
                    $scrapeSuccess = $true
                    # Build display strings: "TaskName [ChargeType]"
                    $taskOptions = @()
                    foreach ($t in $tasks) {
                        $taskOptions += "$($t.task_name) [$($t.charge_type)]"
                    }

                    Write-Host ""
                    $selectedTaskIdx = Select-Option -Prompt "Select Task and Charge Type" -Options $taskOptions
                    $taskName = $tasks[$selectedTaskIdx].task_name
                    $chargeType = $tasks[$selectedTaskIdx].charge_type
                    Write-Host ""
                    Write-Host " [+] Selected: $taskName [$chargeType]" -ForegroundColor Green
                } else {
                    Write-Host " [!] No tasks found on the timesheet. Falling back to manual input." -ForegroundColor Yellow
                }
            } catch {
                Write-Host " [!] Failed to parse task data. Falling back to manual input." -ForegroundColor Yellow
            }
        } else {
            Write-Host " [!] Could not retrieve tasks. Falling back to manual input." -ForegroundColor Yellow
        }
    } else {
        Write-Host ""
        Write-Host " [!] No internet connection detected. Skipping task detection." -ForegroundColor Yellow
    }

    if (-not $scrapeSuccess) {
        Write-Host " Task Name [Default: Development]: " -NoNewline -ForegroundColor White
        $manualTaskName = Read-Host
        if (-not [string]::IsNullOrWhiteSpace($manualTaskName)) { $taskName = $manualTaskName }

        $chargeOptions = @("Billable", "Non Billable")
        $selectedIndex = Select-Option -Prompt "Select Charge Type" -Options $chargeOptions
        $chargeType = $chargeOptions[$selectedIndex]
    }
    
    Invoke-LoadingAnimation -Message "Writing Configuration Files" -DurationSeconds 2

    # Build the TOML content
    $configContent = @"
[employee]
EMPLOYEE_ID = "$employeeId"

[timesheet]
task_name = "$taskName"
charge_type = "$chargeType"
"@

    # Write the TOML file
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText("$PWD\config.toml", $configContent.Trim(), $utf8NoBom)
    Write-Host " [+] config.toml generated." -ForegroundColor Green
}


# ==========================================
Write-Header "Automation & Auto-Run Settings"
# ==========================================

$autoRunOptions = @(
    "Windows Startup (Recommended if you shut down daily)", 
    "Windows Login   (Recommended if you close lid / sleep)", 
    "Disable auto-run"
)
$autoRunChoice = Select-Option -Prompt "How should SilentSheet automatically start?" -Options $autoRunOptions
$autoRunLabel = "Disabled"

function Invoke-SetupStartup {
    param([string]$Action)
    if ($UseUv) {
        uv run --no-sync python setup_startup.py $Action | Out-Null
    } else {
        .\.venv\Scripts\python.exe setup_startup.py $Action | Out-Null
    }
}

Invoke-LoadingAnimation -Message "Applying System Settings" -DurationSeconds 2

switch ($autoRunChoice) {
    0 {
        Write-Host " Configuring Windows Startup..." -ForegroundColor Cyan
        Invoke-SetupStartup "install-startup"
        Invoke-SetupStartup "uninstall-logon"
        Write-Host " [+] SilentSheet will now automatically fill your timesheet in the background." -ForegroundColor Green
        $autoRunLabel = "Windows Startup"
    }
    1 {
        Write-Host " Configuring Windows Login..." -ForegroundColor Cyan
        Invoke-SetupStartup "install-logon"
        Invoke-SetupStartup "uninstall-startup"
        Write-Host " [+] SilentSheet will now automatically fill your timesheet in the background." -ForegroundColor Green
        $autoRunLabel = "Windows Login"
    }
    2 {
        Write-Host " Removing auto-run configurations..." -ForegroundColor Cyan
        Invoke-SetupStartup "uninstall-all"
        $autoRunLabel = "Disabled"
    }
}

# Register AppUserModelId
try {
    $aumidPath = "HKCU:\Software\Classes\AppUserModelId\SilentSheet"
    if (-not (Test-Path $aumidPath)) {
        New-Item -Path $aumidPath -Force -ErrorAction Stop | Out-Null
    }
    $iconPath = "$PWD\favicon.ico"
    Set-ItemProperty -Path $aumidPath -Name "DisplayName" -Value "SilentSheet" -ErrorAction Stop
    Set-ItemProperty -Path $aumidPath -Name "IconUri" -Value $iconPath -ErrorAction Stop

    $cachePath = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Notifications\Settings\SilentSheet"
    if (Test-Path $cachePath) {
        Remove-Item $cachePath -Recurse -Force -ErrorAction Stop | Out-Null
    }
} catch {
    # Silently ignore
}

if (Select-YesNo "Launch SilentSheet now in the background?") {
    Invoke-LoadingAnimation -Message "Starting Background Process" -DurationSeconds 2
    if ($UseUv) {
        Start-Process -FilePath "uv" -ArgumentList "run", "--no-sync", "pythonw", "fill_timesheet.py", "--headless" -WindowStyle Hidden
    } else {
        Start-Process -FilePath ".\.venv\Scripts\pythonw.exe" -ArgumentList "fill_timesheet.py", "--headless" -WindowStyle Hidden
    }
    Write-Host " [+] SilentSheet is running! You will be notified when it requires input or finishes." -ForegroundColor Green
}


# ==========================================
Write-Header "Setup Complete"
# ==========================================

# Read back the config for the summary
if (Test-Path "config.toml") {
    $cfgRaw = Get-Content "config.toml" -Raw
    if ($cfgRaw -match 'EMPLOYEE_ID\s*=\s*"([^"]*)"') { $sumId = $Matches[1] } else { $sumId = "?" }
    if ($cfgRaw -match 'task_name\s*=\s*"([^"]*)"')    { $sumTask = $Matches[1] } else { $sumTask = "?" }
    if ($cfgRaw -match 'charge_type\s*=\s*"([^"]*)"')   { $sumCharge = $Matches[1] } else { $sumCharge = "?" }
}

Write-Host "  FINAL SYSTEM CONFIGURATION:" -ForegroundColor White
Write-Host " -----------------------------------" -ForegroundColor DarkGray
Write-Host "  Employee ID   : " -NoNewline; Write-Host $sumId -ForegroundColor Cyan
Write-Host "  Task Name     : " -NoNewline; Write-Host $sumTask -ForegroundColor Cyan
Write-Host "  Charge Type   : " -NoNewline; Write-Host $sumCharge -ForegroundColor Cyan
Write-Host "  Pkg Manager   : " -NoNewline; Write-Host $(if ($UseUv) { 'uv' } else { 'pip' }) -ForegroundColor Cyan
Write-Host "  Auto-Run      : " -NoNewline; Write-Host $autoRunLabel -ForegroundColor Cyan
Write-Host " -----------------------------------" -ForegroundColor DarkGray
Write-Host "`n [+] You are all set to go!" -ForegroundColor Green
Write-Host ""

if ($bootstrapMode) {
    Write-Host " Opening GitHub repository in your browser..." -ForegroundColor Cyan
    Start-Process "https://github.com/zpratikpathak/SilentSheet-Ultimatix"
    Write-Host ""
}

Read-Host "Press Enter to exit"