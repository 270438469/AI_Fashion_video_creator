$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$TempImage = Join-Path $ProjectRoot 'workspace\temp\smoke-product.jpg'
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $TempImage) | Out-Null
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap 480,640
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.Clear([System.Drawing.Color]::FromArgb(232,220,203))
$brush = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(205,174,137))
$graphics.FillRectangle($brush, 110, 90, 260, 470)
$bitmap.Save($TempImage, [System.Drawing.Imaging.ImageFormat]::Jpeg)
$brush.Dispose(); $graphics.Dispose(); $bitmap.Dispose()

$response = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/v1/generate' -Form @{product_image=Get-Item -LiteralPath $TempImage; character_id='asian_girl_001'}
$RunId = $response.run_id
Write-Output "Submitted $RunId"
$deadline = (Get-Date).AddMinutes(3)
do {
    Start-Sleep -Seconds 1
    $run = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/runs/$RunId"
    Write-Output ("{0}% {1}" -f $run.progress,$run.current_step)
    if ($run.status -eq 'FAILED') { throw $run.error }
} while ($run.status -ne 'COMPLETED' -and (Get-Date) -lt $deadline)
if ($run.status -ne 'COMPLETED') { throw 'Smoke test timed out' }
$output = Join-Path $ProjectRoot "workspace\outputs\$RunId\final.mp4"
if (-not (Test-Path -LiteralPath $output)) { throw "Missing $output" }
$duration = docker compose exec -T backend ffprobe -v error -show_entries format=duration -of default=nokey=1:noprint_wrappers=1 "/app/workspace/outputs/$RunId/final.mp4"
if ([double]$duration -lt 17.5 -or [double]$duration -gt 18.5) { throw "Unexpected duration: $duration" }
Write-Output "PASS: $output ($duration seconds)"
