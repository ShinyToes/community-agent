$ErrorActionPreference = 'Stop'
$communityRoot = Split-Path -Parent $PSScriptRoot
$communityPython = (Resolve-Path (Join-Path $communityRoot '.venv-dev/Scripts/python.exe')).Path
$communityRun = (Resolve-Path (Join-Path $communityRoot 'run_community.py')).Path
$communityRuntime = Join-Path $communityRoot 'instance/community'
New-Item -ItemType Directory -Force -Path $communityRuntime | Out-Null
Push-Location $communityRoot
try {
    & $communityPython tools/setup_community.py
    if ($LASTEXITCODE -ne 0) { throw 'Community configuration failed.' }
    & docker --context desktop-linux compose --env-file .env.community -f compose.community.yaml up -d --wait --wait-timeout 120
    if ($LASTEXITCODE -ne 0) { throw 'Start Docker Desktop and retry. Community MySQL is not ready.' }
    & $communityPython -m community db-upgrade
    if ($LASTEXITCODE -ne 0) { throw 'Community migration failed.' }
    $communityExisting = Get-CimInstance Win32_Process | Where-Object {
        $_.ExecutablePath -eq $communityPython -and $_.CommandLine -like "*$communityRun*"
    }
    if ($communityExisting) {
        Write-Host 'Community web is already running at http://127.0.0.1:5001/'
        return
    }
    if (Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue) {
        throw 'Port 5001 is occupied; stop its owner before starting Community.'
    }
    $communityProcess = Start-Process -FilePath $communityPython -ArgumentList @('-u', ('"' + $communityRun + '"')) -WorkingDirectory $communityRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $communityRuntime 'web.out.log') -RedirectStandardError (Join-Path $communityRuntime 'web.err.log')
    $communityProcess.Id | Set-Content -LiteralPath (Join-Path $communityRuntime 'web.pid')
    Write-Host 'Open http://127.0.0.1:5001/ ; register your own account.'
} finally {
    Pop-Location
}
