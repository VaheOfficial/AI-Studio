# Turns Grom AI Studio on or off (the desktop shortcut runs this through studio-toggle.vbs, hidden).
# Off -> starts the server (8765) and the web app (5173) in the background, then opens the browser.
# On  -> stops both, with everything they started (model workers, llama-server, Ollama).
param([switch]$Install)

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$logs = Join-Path $root 'data\logs'
$ports = @{ server = 8765; web = 5173 }
$url = 'http://localhost:5173'
$shell = New-Object -ComObject WScript.Shell

function Show([string]$text, [int]$seconds = 3, [int]$icon = 64) {
    [void]$shell.Popup($text, $seconds, 'Grom AI Studio', $icon)
}

function Get-Listener([int]$port) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
}

# Desktop shortcut: pwsh .\scripts\studio-toggle.ps1 -Install
if ($Install) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnk = $shell.CreateShortcut((Join-Path $desktop 'AI Studio.lnk'))
    $lnk.TargetPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
    $lnk.Arguments = '"' + (Join-Path $PSScriptRoot 'studio-toggle.vbs') + '"'
    $lnk.WorkingDirectory = $root
    $lnk.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',27'
    $lnk.Description = 'Turn Grom AI Studio on or off'
    $lnk.Save()
    Write-Host "Created $(Join-Path $desktop 'AI Studio.lnk')"
    exit 0
}

$running = $ports.Values | Where-Object { Get-Listener $_ }
if ($running) {
    foreach ($port in $ports.Values) {
        $conn = Get-Listener $port
        if ($conn) {
            # The whole tree: the server's workers and the processes it started go with it
            & taskkill.exe /PID $conn.OwningProcess /T /F *> $null
        }
    }
    Get-CimInstance Win32_Process -Filter "Name = 'pwsh.exe'" |
        Where-Object { $_.CommandLine -like '*AI Studio*server\run.ps1*' -or $_.CommandLine -like '*studio-toggle-web*' } |
        ForEach-Object { & taskkill.exe /PID $_.ProcessId /T /F *> $null }
    Show 'Grom AI Studio is off.'
    exit 0
}

New-Item -ItemType Directory -Force -Path $logs | Out-Null
$pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $pwsh) { $pwsh = (Get-Process -Id $PID).Path }
Start-Process $pwsh -WindowStyle Hidden -WorkingDirectory $root -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "& '$root\server\run.ps1' *> '$logs\server.log'")
Start-Process $pwsh -WindowStyle Hidden -WorkingDirectory $root -ArgumentList @(
    '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Command',
    "`$host.UI.RawUI.WindowTitle = 'studio-toggle-web'; pnpm --filter studio dev *> '$logs\web.log' # studio-toggle-web")
Show 'Starting Grom AI Studio… the browser opens when it is ready.' 3

$deadline = (Get-Date).AddMinutes(5)  # the first start may install server dependencies
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 1
    if ((Get-Listener $ports.server) -and (Get-Listener $ports.web)) {
        Start-Process $url
        exit 0
    }
}
Show "Grom AI Studio didn't start within 5 minutes. See the logs in $logs (server.log, web.log)." 0 48
exit 1
