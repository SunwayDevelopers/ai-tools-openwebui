# Start Open WebUI in DEVELOPMENT mode with hot reload.
#
# All services start together via docker-compose.dev.yml:
#   - Frontend: Vite HMR (browser auto-refreshes on save) at http://localhost:5173
#   - Backend:  uvicorn --reload (Python process restarts on save) at http://localhost:8080
#   - Postgres: persistent via Docker volume
#   - Qdrant:   persistent via Docker volume
#
# Usage:
#   .\dev.ps1              # start all services
#   .\dev.ps1 -Rebuild     # force image rebuild (after changing Dockerfiles or dependencies)

[CmdletBinding()]
param(
    [switch]$Rebuild
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Write-Error ".env file not found. Copy .env.example and fill in POSTGRES_PASSWORD before starting."
    exit 1
}
if (-not (Select-String -Path ".env" -Pattern "^POSTGRES_PASSWORD=\S" -Quiet)) {
    Write-Error "POSTGRES_PASSWORD is not set in .env. The database will fail to start."
    exit 1
}

# Override any machine-level env vars with values from .env so Docker Compose
# always uses the correct keys regardless of what's set system-wide.
foreach ($line in (Get-Content ".env")) {
    if ($line -match "^\s*#" -or $line -notmatch "=") { continue }
    $key, $val = $line -split "=", 2
    $val = $val -replace "^'(.*)'$", '$1' -replace '^"(.*)"$', '$1'
    [System.Environment]::SetEnvironmentVariable($key.Trim(), $val.Trim(), "Process")
}

Write-Host "=== Open WebUI Dev Mode (hot reload) ===" -ForegroundColor Cyan

$composeArgs = @("-f", "docker-compose.dev.yml", "up")
if ($Rebuild) { $composeArgs += "--build" }

Write-Host ""
Write-Host "  Frontend:  http://localhost:5173" -ForegroundColor Cyan
Write-Host "  Backend:   http://localhost:8080" -ForegroundColor Cyan
Write-Host "  Vite HMR:  edits under src/ refresh the browser automatically" -ForegroundColor Cyan
Write-Host "  Py reload: edits under backend/ restart the Python process" -ForegroundColor Cyan
Write-Host "  Stop:      Ctrl+C" -ForegroundColor Yellow
Write-Host "  Tip:       first run takes a while (image build + pip install inside container)." -ForegroundColor DarkGray
Write-Host ""

docker compose @composeArgs
exit $LASTEXITCODE
