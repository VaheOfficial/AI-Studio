# Creates server/.venv if needed, installs dependencies when pyproject.toml changes,
# then serves the Studio API on http://127.0.0.1:8765.
param(
    [switch]$Reload
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$venv = Join-Path $root '.venv'
$py = Join-Path $venv 'Scripts\python.exe'

function Invoke-Checked([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed ($LASTEXITCODE): $exe $($arguments -join ' ')" }
}

if (-not (Test-Path $py)) {
    Write-Host 'Creating server virtualenv...'
    Invoke-Checked 'python' @('-m', 'venv', $venv)
    Invoke-Checked $py @('-m', 'pip', 'install', '--quiet', '--upgrade', 'pip', 'uv')
}

$stamp = Join-Path $venv '.deps-stamp'
# .NET, not Get-FileHash: Windows PowerShell started from PowerShell 7 inherits its module path and can't load it
$sha = [System.Security.Cryptography.SHA256]::Create()
$hash = [BitConverter]::ToString($sha.ComputeHash([IO.File]::ReadAllBytes((Join-Path $root 'pyproject.toml')))) -replace '-', ''
$sha.Dispose()
if (-not (Test-Path $stamp) -or (Get-Content $stamp -Raw).Trim() -ne $hash) {
    Write-Host 'Installing server dependencies...'
    Invoke-Checked $py @('-m', 'uv', 'pip', 'install', '--python', $py, '-e', $root)
    Set-Content -Path $stamp -Value $hash
}

Set-Location $root
$uvicornArgs = @('-m', 'uvicorn', 'studio.main:app', '--host', '127.0.0.1', '--port', '8765')
if ($Reload) { $uvicornArgs += @('--reload', '--reload-dir', (Join-Path $root 'studio')) }
& $py @uvicornArgs
exit $LASTEXITCODE
