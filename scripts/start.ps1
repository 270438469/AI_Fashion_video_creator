$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
python "$PSScriptRoot\check_environment.py"
if (-not (Test-Path -LiteralPath '.env')) {
    Copy-Item -LiteralPath '.env.example' -Destination '.env'
}
$env:DOCKER_BUILDKIT = '0'
$env:COMPOSE_DOCKER_CLI_BUILD = '0'
docker compose up --build -d
Write-Output ''
Write-Output 'AI Fashion Video Director started.'
Write-Output ''
Write-Output 'Frontend:  http://127.0.0.1:3000'
Write-Output 'Backend:   http://127.0.0.1:8000'
Write-Output 'API Docs:  http://127.0.0.1:8000/docs'
Write-Output ''
Write-Output 'Logs: docker compose logs -f'
