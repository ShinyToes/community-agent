$ErrorActionPreference = 'Stop'
$crawlerRoot = Join-Path $PSScriptRoot 'MediaCrawler'
$crawlerPython = Join-Path $crawlerRoot '.venv/Scripts/python.exe'
$crawlerRuntime = Join-Path $PSScriptRoot '.runtime'
if (-not (Test-Path -LiteralPath $crawlerPython)) { throw 'Install dependencies first: cd MediaCrawler; uv sync --locked' }
& $crawlerPython -c 'import community_research.api.router' 2>$null
if ($LASTEXITCODE -ne 0) { throw 'Install research package from project root: uv pip install --python MediaCrawler/.venv/Scripts/python.exe -e .' }
if (-not (Test-Path -LiteralPath (Join-Path $crawlerRoot 'api/webui/index.html'))) { throw 'Build the UI first: cd MediaCrawler/webui; npm.cmd ci; npm.cmd run build' }
New-Item -ItemType Directory -Force -Path $crawlerRuntime | Out-Null
$crawlerPidFile = Join-Path $crawlerRuntime 'web.pid'
if (Test-Path -LiteralPath $crawlerPidFile) {
    $crawlerPid = [int](Get-Content -LiteralPath $crawlerPidFile)
    $crawlerExisting = Get-CimInstance Win32_Process -Filter "ProcessId=$crawlerPid" -ErrorAction SilentlyContinue | Where-Object {
        $_.ExecutablePath -eq $crawlerPython -and $_.CommandLine -like '*uvicorn api.main:app*'
    }
    if ($crawlerExisting) { Write-Host 'MediaCrawler is already running: http://127.0.0.1:8080'; return }
}
$crawlerPortBusy = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if (-not $crawlerPortBusy) {
    # Some restricted Windows sessions deny the PowerShell TCP provider while netstat remains readable.
    $crawlerPortBusy = netstat -ano -p TCP | Select-String '^\s*TCP\s+(?:127\.0\.0\.1|0\.0\.0\.0|\[::\]):8080\s+.*LISTENING\s+\d+\s*$'
}
if ($crawlerPortBusy) { throw 'Port 8080 is occupied; no existing process was stopped.' }
$env:PYTHONUTF8 = '1'
$crawlerProcess = Start-Process -FilePath $crawlerPython -ArgumentList @('-m', 'uvicorn', 'api.main:app', '--host', '127.0.0.1', '--port', '8080') -WorkingDirectory $crawlerRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $crawlerRuntime 'web.out.log') -RedirectStandardError (Join-Path $crawlerRuntime 'web.err.log')
$crawlerProcess.Id | Set-Content -LiteralPath $crawlerPidFile
Write-Host 'MediaCrawler started: http://127.0.0.1:8080'
