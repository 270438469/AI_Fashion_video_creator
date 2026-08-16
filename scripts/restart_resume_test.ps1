$ErrorActionPreference = 'Stop'
$Image = Get-Item -LiteralPath (Join-Path $PSScriptRoot '..\workspace\temp\smoke-product.jpg')
$response = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/generate' -Form @{product_image=$Image; character_id='asian_girl_001'}
$RunId = $response.run_id
Write-Output "RUN=$RunId"
Start-Sleep -Milliseconds 300
docker compose stop backend | Out-Null
$statePath = Join-Path $PSScriptRoot "..\workspace\runs\$RunId\state.json"
$state = Get-Content -LiteralPath $statePath -Raw | ConvertFrom-Json
Write-Output "BEFORE_RESTART=$($state.status)"
docker compose start backend | Out-Null
$deadline = (Get-Date).AddSeconds(45)
$after = $null
do {
    Start-Sleep -Milliseconds 500
    try { $after = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/runs/$RunId" -TimeoutSec 2 } catch { $after = $null }
} while (-not $after -and (Get-Date) -lt $deadline)
Write-Output "AFTER_RESTART=$($after.status)"
if ($after.status -ne 'INTERRUPTED') { throw "Expected INTERRUPTED, got $($after.status)" }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/runs/$RunId/resume" | Out-Null
do {
    Start-Sleep -Milliseconds 700
    $done = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/runs/$RunId"
    Write-Output "$($done.progress)% $($done.status)"
} while ($done.status -notin @('COMPLETED','FAILED') -and (Get-Date) -lt $deadline)
if ($done.status -ne 'COMPLETED') { throw $done.error }
Write-Output 'RESTART_RESUME=PASS'

