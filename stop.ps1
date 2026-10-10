$ErrorActionPreference = 'Stop'
$crawlerPython = Join-Path $PSScriptRoot 'MediaCrawler/.venv/Scripts/python.exe'
$crawlerPidFile = Join-Path $PSScriptRoot '.runtime/web.pid'
if (-not (Test-Path -LiteralPath $crawlerPidFile)) { Write-Host 'No recorded Web process.'; return }
$crawlerPid = [int](Get-Content -LiteralPath $crawlerPidFile)
$crawlerExisting = Get-CimInstance Win32_Process -Filter "ProcessId=$crawlerPid" -ErrorAction SilentlyContinue | Where-Object {
    $_.ExecutablePath -eq $crawlerPython -and $_.CommandLine -like '*uvicorn api.main:app*'
}
if ($crawlerExisting) {
    $crawlerStatus = Invoke-RestMethod 'http://127.0.0.1:8080/api/crawler/status'
    if ($crawlerStatus.status -in @('running', 'stopping')) { throw 'Stop the active crawl from the WebUI before stopping the server.' }
    $crawlerChildren = Get-CimInstance Win32_Process -Filter "ParentProcessId=$crawlerPid" | Where-Object { $_.CommandLine -like '*uvicorn api.main:app*' }
    foreach ($crawlerChild in $crawlerChildren) { Stop-Process -Id $crawlerChild.ProcessId -ErrorAction SilentlyContinue }
    Stop-Process -Id $crawlerPid
} else {
    $crawlerWrapper = Get-Process -Id $crawlerPid -ErrorAction SilentlyContinue
    if ($crawlerWrapper -and $crawlerWrapper.Path -eq $crawlerPython) {
        $crawlerStatus = Invoke-RestMethod 'http://127.0.0.1:8080/api/crawler/status'
        if ($crawlerStatus.status -in @('running', 'stopping')) { throw 'Stop the active crawl from the WebUI before stopping the server.' }
        $crawlerLine = netstat -ano -p TCP | Select-String '^\s*TCP\s+127\.0\.0\.1:8080\s+.*LISTENING\s+\d+\s*$' | Select-Object -First 1
        if (-not $crawlerLine) { throw 'Cannot verify the Web listener; no process was stopped.' }
        $crawlerServerPid = [int](($crawlerLine.ToString().Trim() -split '\s+')[-1])
        $crawlerLog = Get-Content -Raw -Encoding UTF8 (Join-Path $PSScriptRoot '.runtime/web.err.log')
        if ($crawlerLog -notmatch "Started server process \[$crawlerServerPid\]") { throw 'Cannot verify the Web process; no process was stopped.' }
        Stop-Process -Id $crawlerServerPid
        Stop-Process -Id $crawlerPid -ErrorAction SilentlyContinue
    }
}
Remove-Item -LiteralPath $crawlerPidFile
Write-Host 'MediaCrawler Web stopped.'
