$ErrorActionPreference = 'Stop'
$runs = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/v1/runs'
$completed = $runs | Where-Object status -eq 'COMPLETED' | Select-Object -First 1
if (-not $completed) { throw 'No completed run available' }
$RunId = $completed.run_id
$root = Join-Path $PSScriptRoot "..\workspace\runs\$RunId"
$analysisBefore = (Get-Item -LiteralPath (Join-Path $root 'analysis\product_analysis.json')).LastWriteTimeUtc
$s02Before = (Get-Item -LiteralPath (Join-Path $root 'videos\S02.mp4')).LastWriteTimeUtc
$before = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/runs/$RunId"
$attemptBefore = ($before.shots | Where-Object shot_id -eq 'S03').attempts.video
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/runs/$RunId/shots/S03/retry-video" | Out-Null
$deadline = (Get-Date).AddSeconds(45)
Start-Sleep -Milliseconds 500
do {
    Start-Sleep -Milliseconds 500
    $after = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/runs/$RunId"
    $attemptAfter = ($after.shots | Where-Object shot_id -eq 'S03').attempts.video
} while (($after.status -ne 'COMPLETED' -or $attemptAfter -le $attemptBefore) -and (Get-Date) -lt $deadline)
if ($after.status -ne 'COMPLETED') { throw $after.error }
if ($attemptAfter -ne ($attemptBefore + 1)) { throw "S03 attempts changed unexpectedly: $attemptBefore -> $attemptAfter" }
if ((Get-Item -LiteralPath (Join-Path $root 'analysis\product_analysis.json')).LastWriteTimeUtc -ne $analysisBefore) { throw 'Product analysis was rerun' }
if ((Get-Item -LiteralPath (Join-Path $root 'videos\S02.mp4')).LastWriteTimeUtc -ne $s02Before) { throw 'S02 video was regenerated' }
Write-Output "SHOT_RETRY=PASS ($RunId, S03 video $attemptBefore -> $attemptAfter; S02 unchanged)"
