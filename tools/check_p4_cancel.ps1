$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$api = 'http://127.0.0.1:8080/api/research'
$session = Invoke-RestMethod -Method Post -Uri "$api/sessions" -ContentType 'application/json' -Body '{}'
$job = Invoke-RestMethod -Method Post -Uri "$api/sessions/$($session.id)/collections" -ContentType 'application/json' -Body '{"text":"P4 process cancellation verification: donk","queries":["donk"]}'
$job.plan.posts_per_query = 1
$job.plan.seconds = 60
try {
    Invoke-RestMethod -Method Post -Uri "$api/collections/$($job.id)/execute" -ContentType 'application/json' -Body (@{plan=$job.plan} | ConvertTo-Json -Depth 5) | Out-Null
    Start-Sleep -Seconds 5
    $current = (Invoke-RestMethod "$api/sessions/$($session.id)/collections") | Where-Object { $_.id -eq $job.id }
    $taskId = $current.progress.branches[0].task_id
    $taskBefore = Get-Content -Encoding UTF8 -LiteralPath (Join-Path $projectRoot "MediaCrawler/data/tasks/$taskId/task.json") | ConvertFrom-Json
    if (-not $taskBefore.pid -or [int]$taskBefore.pid -le 0) { throw 'Crawler already finished; no live PID available to test' }
    $allProcesses = Get-CimInstance Win32_Process
    $ownedIds = [System.Collections.Generic.HashSet[int]]::new()
    [void]$ownedIds.Add([int]$taskBefore.pid)
    do {
        $added = $false
        foreach ($processRow in $allProcesses) {
            if ($ownedIds.Contains([int]$processRow.ParentProcessId) -and $ownedIds.Add([int]$processRow.ProcessId)) { $added = $true }
        }
    } while ($added)
    $cancelled = Invoke-RestMethod -Method Post -Uri "$api/collections/$($job.id)/cancel" -ContentType 'application/json' -Body '{}'
    # Windows browser descendants may take a short time to finish OS teardown.
    Start-Sleep -Seconds 2
    $stillAlive = @(Get-CimInstance Win32_Process | Where-Object { $ownedIds.Contains([int]$_.ProcessId) })
    $result = @{status=$cancelled.status; previous_status=$current.status; task_id=$taskId; captured_processes=$ownedIds.Count; remaining_processes=$stillAlive.Count; remaining_ids=@($stillAlive | ForEach-Object { $_.ProcessId }); crawler_status=(Invoke-RestMethod 'http://127.0.0.1:8080/api/crawler/status').status}
    $result | ConvertTo-Json | Set-Content -Encoding UTF8 (Join-Path $projectRoot 'docs/p4/live-cancel-validation.json')
    $result | ConvertTo-Json
    if ($cancelled.status -ne 'cancelled' -or $stillAlive.Count -gt 0) { throw 'Cancel verification failed' }
} finally {
    Invoke-RestMethod -Method Post -Uri "$api/collections/$($job.id)/cancel" -ContentType 'application/json' -Body '{}' | Out-Null
    Invoke-RestMethod -Method Delete -Uri "$api/sessions/$($session.id)" | Out-Null
}
