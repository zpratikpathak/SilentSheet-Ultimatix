function Select-TimesheetOption {
    param(
        [Parameter(Mandatory = $true)][string]$Prompt,
        [Parameter(Mandatory = $true)][string[]]$Options,
        [int]$Default = 0
    )

    $originalCursorVisible = [System.Console]::CursorVisible
    try {
        [System.Console]::CursorVisible = $false
        Write-Host "`n $Prompt" -ForegroundColor Cyan
        Write-Host " (Use Up/Down arrows to move, Enter to select)`n" -ForegroundColor DarkGray
        $selected = $Default
        $escape = [char]27
        for ($index = 0; $index -lt $Options.Count; $index++) {
            if ($index -eq $selected) {
                Write-Host "  > $($Options[$index])" -ForegroundColor Cyan
            } else {
                Write-Host "    $($Options[$index])" -ForegroundColor DarkGray
            }
        }
        while ($true) {
            $key = [System.Console]::ReadKey($true)
            if ($key.Key -eq [System.ConsoleKey]::UpArrow -and $selected -gt 0) {
                $selected--
            } elseif ($key.Key -eq [System.ConsoleKey]::DownArrow -and $selected -lt ($Options.Count - 1)) {
                $selected++
            } elseif ($key.Key -eq [System.ConsoleKey]::Enter) {
                return $selected
            } else {
                continue
            }
            Write-Host "$escape[$($Options.Count)A" -NoNewline
            for ($index = 0; $index -lt $Options.Count; $index++) {
                Write-Host "$escape[2K" -NoNewline
                if ($index -eq $selected) {
                    Write-Host "  > $($Options[$index])" -ForegroundColor Cyan
                } else {
                    Write-Host "    $($Options[$index])" -ForegroundColor DarkGray
                }
            }
        }
    } finally {
        [System.Console]::CursorVisible = $originalCursorVisible
    }
}

function Invoke-TimesheetTaskScrape {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$EmployeeId
    )

    $job = $null
    $originalCursorVisible = [System.Console]::CursorVisible
    try {
        $job = Start-Job -ScriptBlock {
            param($Python, $Root, $Employee)
            Set-Location -LiteralPath $Root
            & $Python (Join-Path 'src' 'scrape_tasks.py') $Employee 2>&1 | Out-String
        } -ArgumentList $PythonExe, $ProjectRoot, $EmployeeId

        [System.Console]::CursorVisible = $false
        $spinner = @('-', '\', '|', '/')
        $spinIndex = 0
        while ($job.State -eq 'Running') {
            Write-Host "`r  [$($spinner[$spinIndex % 4])] Fetching tasks from timesheet..." -NoNewline -ForegroundColor Cyan
            $spinIndex++
            Start-Sleep -Milliseconds 100
        }
        Write-Host "`r                                                            `r" -NoNewline
        $output = Receive-Job -Job $job
        $resultLine = ($output -split "`n") |
            Where-Object { $_ -match '^SCRAPE_RESULT:' } |
            Select-Object -Last 1
        if (-not $resultLine) {
            throw "Couldn't find SCRAPE_RESULT in the scraper output."
        }
        $payload = ($resultLine -replace '^SCRAPE_RESULT:', '').Trim()
        return @($payload | ConvertFrom-Json)
    } finally {
        [System.Console]::CursorVisible = $originalCursorVisible
        if ($null -ne $job) {
            Remove-Job -Job $job -Force -ErrorAction SilentlyContinue
        }
    }
}

function Select-TimesheetTask {
    param([Parameter(Mandatory = $true)][object[]]$Tasks)

    $options = @($Tasks | ForEach-Object { "$($_.task_name) [$($_.charge_type)]" })
    $selectedIndex = Select-TimesheetOption -Prompt 'Select Task and Charge Type' -Options $options
    return $Tasks[$selectedIndex]
}

function Get-SilentSheetEmployeeId {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$ProjectRoot
    )
    $configManager = Join-Path $ProjectRoot 'src\config_manager.py'
    $configPath = Join-Path $ProjectRoot 'config.toml'
    $employeeId = & $PythonExe $configManager --config $configPath read-employee
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not read employee ID from config.toml.'
    }
    return ($employeeId | Out-String).Trim()
}

function Set-SilentSheetConfig {
    param(
        [Parameter(Mandatory = $true)][string]$PythonExe,
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [string]$EmployeeId,
        [Parameter(Mandatory = $true)][string]$TaskName,
        [Parameter(Mandatory = $true)][string]$ChargeType
    )
    $configManager = Join-Path $ProjectRoot 'src\config_manager.py'
    $configPath = Join-Path $ProjectRoot 'config.toml'
    if ([string]::IsNullOrWhiteSpace($EmployeeId)) {
        & $PythonExe $configManager --config $configPath update-task $TaskName $ChargeType
    } else {
        & $PythonExe $configManager --config $configPath write $EmployeeId $TaskName $ChargeType
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Could not update config.toml.'
    }
}