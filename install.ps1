# Bootstrap only: trusted home archive into an empty destination, then Python setup.
$ErrorActionPreference = 'Stop'
function Find-Python {
    $candidates = @('python.exe', 'python3.exe', 'py.exe')
    $candidates += @(Get-ChildItem "$env:LOCALAPPDATA\Programs\Python\Python*\python.exe" -ErrorAction SilentlyContinue | ForEach-Object FullName)
    foreach ($candidate in $candidates) {
        if (-not (Get-Command $candidate -ErrorAction SilentlyContinue)) { continue }
        try {
            $result = & $candidate -c 'import sys; print(sys.executable) if sys.version_info >= (3,12) else sys.exit(1)' 2>$null
            if ($LASTEXITCODE -eq 0 -and $result -and (Test-Path -LiteralPath "$result" -PathType Leaf)) { return "$result" }
        } catch { continue }
    }
    return $null
}
$destination = $PWD.Path
if (Get-ChildItem -LiteralPath $destination -Force) { throw 'Destination must be empty.' }
for ($item = Get-Item -LiteralPath $destination; $null -ne $item; $item = $item.Parent) {
    if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Linked destination refused.' }
}
$python = Find-Python
if (-not $python) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw 'Install Python >=3.12, then rerun.' }
    if ((Read-Host 'Install Python 3.12 using winget? Type YES') -cne 'YES') { throw 'Cancelled.' }
    & winget install --id Python.Python.3.12 --exact --scope user
    if ($LASTEXITCODE -ne 0) { throw 'Python installation failed.' }
    $python = Find-Python
    if (-not $python) { throw 'Python >=3.12 not found. Open a new terminal and retry.' }
}
$zipPath = [IO.Path]::GetTempFileName()
try {
    Invoke-WebRequest -UseBasicParsing -MaximumRedirection 0 -Uri 'https://codeload.github.com/zpratikpathak/SilentSheet-Ultimatix/zip/refs/heads/home' -OutFile $zipPath
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip = [IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $seen = @{}
        $files = @()
        $total = 0L
        if ($zip.Entries.Count -gt 20000) { throw 'Too many archive entries.' }
        foreach ($entry in $zip.Entries) {
            $parts = $entry.FullName.TrimEnd('/').Split('/')
            if ($parts[0] -cne 'SilentSheet-Ultimatix-home') { throw 'Unexpected archive root.' }
            foreach ($part in $parts) {
                if (-not $part -or $part -in '.', '..' -or $part -match '[\\:\x00-\x1f<>"|?*]' -or $part -match '[ .]$' -or $part -match '^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)') { throw 'Unsafe archive path.' }
            }
            $kind = ($entry.ExternalAttributes -shr 16) -band 61440
            if ($kind -notin 0, 32768, 16384) { throw 'Archive links/special files refused.' }
            $key = $entry.FullName.TrimEnd('/')
            if ($seen.ContainsKey($key)) { throw 'Duplicate archive path.' }
            $seen[$key] = $true
            $total += $entry.Length
            if ($total -gt 268435456) { throw 'Archive exceeds expanded size limit.' }
            if ($parts.Count -eq 1 -or $entry.FullName.EndsWith('/')) { continue }
            $relative = ($parts[1..($parts.Count - 1)] -join '/')
            $files += @{ Entry = $entry; Relative = $relative }
        }
        foreach ($required in 'manage.py', 'src/setup_workflow.py', 'src/installation.py', 'requirements.txt', 'fill_timesheet.py') {
            if ($required -cnotin $files.Relative) { throw "Archive missing $required" }
        }
        if (Get-ChildItem -LiteralPath $destination -Force) { throw 'Destination no longer empty.' }
        foreach ($file in $files) {
            $target = Join-Path $destination $file.Relative
            [IO.Directory]::CreateDirectory([IO.Path]::GetDirectoryName($target)) | Out-Null
            [IO.Compression.ZipFileExtensions]::ExtractToFile($file.Entry, $target, $false)
        }
    } finally { $zip.Dispose() }
} finally { Remove-Item -LiteralPath $zipPath -Force }
& $python (Join-Path $destination 'manage.py') setup
if ($LASTEXITCODE -ne 0) { throw "Setup failed ($LASTEXITCODE). Files retained; rerun manage.py setup after fixing cause." }
