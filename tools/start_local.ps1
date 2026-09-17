$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = (Resolve-Path (Join-Path $projectRoot '.venv-dev/Scripts/python.exe')).Path
$runtimeDir = Join-Path $projectRoot 'instance'
New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
& $pythonPath (Join-Path $PSScriptRoot 'local_mysql.py') start
if ($LASTEXITCODE -ne 0) { throw 'MySQL startup failed; check Docker Desktop.' }
$processes = @()
foreach ($entry in @(@{Name='web'; Script='run.py'}, @{Name='worker'; Script='workers/import_worker.py'})) {
    $scriptPath = (Resolve-Path (Join-Path $projectRoot $entry.Script)).Path
    $running = Get-CimInstance Win32_Process | Where-Object { $_.ExecutablePath -eq $pythonPath -and $_.CommandLine -like "*$scriptPath*" }
    if ($running) {
        Write-Host "$($entry.Name) already running"
        foreach ($item in $running) { $processes += @{name=$entry.Name; pid=$item.ProcessId; script=$scriptPath} }
        continue
    }
    if ($entry.Name -eq 'web' -and (Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue)) {
        throw 'Port 5000 is occupied. Stop its owner before starting this project.'
    }
    $process = Start-Process -FilePath $pythonPath -ArgumentList @('-u', ('"' + $scriptPath + '"')) -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDir ($entry.Name + '.out.log')) -RedirectStandardError (Join-Path $runtimeDir ($entry.Name + '.err.log'))
    $processes += @{name=$entry.Name; pid=$process.Id; script=$scriptPath}
}
$processes | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $runtimeDir 'local-processes.json')
Write-Host 'Open http://127.0.0.1:5000/agent ; local credentials: instance/demo-login.txt'
