# dev.ps1 - Open WebUI native dev mode with hot reload (single terminal)
#
#   First run (or -Rebuild): creates .venv, pip install, npm install automatically.
#   Subsequent runs:         skips setup, starts infrastructure straight away.
#
#   postgres / qdrant / tika  -> Docker (detached, volumes persist between runs)
#   Backend  uvicorn --reload -> :8080  (prefixed [BE] in this terminal)
#   Frontend vite dev --host  -> :5173  (prefixed [FE] in this terminal)
#
# Prerequisites (must be installed on the machine):
#   Python 3.11 or 3.12, Node.js 20+, Docker Desktop running
#
# Usage:
#   .\dev.ps1            start (auto-setup on first run), then runs both servers
#   .\dev.ps1 -Rebuild   force reinstall pip + npm deps, then start
#   .\dev.ps1 -Stop      stop Docker infra (postgres, qdrant, tika)

[CmdletBinding()]
param(
    [switch]$Rebuild,
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$root        = $PSScriptRoot
$venvPython  = "$root\.venv\Scripts\python.exe"
$venvUvicorn = "$root\.venv\Scripts\uvicorn.exe"

# -- helpers -------------------------------------------------------------------

function Import-DotEnv([string]$path) {
    foreach ($line in (Get-Content $path)) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $k, $v = $line -split '=', 2
        $v = $v -replace "^'(.*)'$", '$1' -replace '^"(.*)"$', '$1'
        [System.Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), 'Process')
    }
}

# -- stop ----------------------------------------------------------------------

if ($Stop) {
    Write-Host "Stopping Docker infra (postgres, qdrant, tika)..." -ForegroundColor Yellow
    docker compose -f "$root\docker-compose.dev.yml" stop postgres qdrant tika
    exit $LASTEXITCODE
}

# -- pre-flight (tools that must already exist on the machine) -----------------

foreach ($cmd in @('docker', 'node', 'npm')) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "'$cmd' not found in PATH."
        exit 1
    }
}
if (-not (Test-Path "$root\.env")) {
    Write-Error ".env not found. Copy .env.example and fill in POSTGRES_PASSWORD."
    exit 1
}
if (-not (Select-String -Path "$root\.env" -Pattern '^POSTGRES_PASSWORD=\S' -Quiet)) {
    Write-Error "POSTGRES_PASSWORD is empty in .env."
    exit 1
}

Write-Host ""
Write-Host "=== Open WebUI - Native Dev Mode ===" -ForegroundColor Cyan
Write-Host ""

# -- setup: Python venv + pip install -----------------------------------------

$needPip = $Rebuild -or (-not (Test-Path $venvUvicorn))

if (-not (Test-Path "$root\.venv")) {
    # packages in requirements.txt require Python <3.13 -- prefer 3.11, then 3.12
    $pyVerArg = $null
    foreach ($ver in @('3.11', '3.12')) {
        try { $null = py "-$ver" --version 2>&1 } catch {}
        if ($LASTEXITCODE -eq 0) { $pyVerArg = "-$ver"; break }
    }
    if (-not $pyVerArg) {
        Write-Error "Python 3.11 or 3.12 required (incompatible with 3.13+). Install from https://python.org and re-run."
        exit 1
    }
    Write-Host "[setup] Creating Python virtual environment (.venv) with py $pyVerArg..." -ForegroundColor Yellow
    py $pyVerArg -m venv "$root\.venv"
    if ($LASTEXITCODE -ne 0) { Write-Error "python -m venv failed."; exit 1 }
    $needPip = $true
}

if ($needPip) {
    Write-Host "[setup] Installing Python dependencies (this may take a few minutes)..." -ForegroundColor Yellow
    & $venvPython -m pip install --quiet --upgrade pip
    & $venvPython -m pip install -r "$root\backend\requirements.txt"
    if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed."; exit 1 }
    Write-Host "        Done." -ForegroundColor Green
}

# -- setup: npm install --------------------------------------------------------
# Also reinstall if concurrently is missing (e.g. first run after this script switched to single-terminal mode).

$needNpm = $Rebuild `
    -or (-not (Test-Path "$root\node_modules")) `
    -or (-not (Test-Path "$root\node_modules\concurrently"))

if ($needNpm) {
    Write-Host "[setup] Running npm install..." -ForegroundColor Yellow
    Push-Location "$root"
    npm install
    $npmExit = $LASTEXITCODE
    Pop-Location
    if ($npmExit -ne 0) { Write-Error "npm install failed."; exit 1 }
    Write-Host "        Done." -ForegroundColor Green
}

Import-DotEnv "$root\.env"

# -- Docker infrastructure -----------------------------------------------------

Write-Host "[1/2] Starting Docker infra (postgres, qdrant, tika)..." -ForegroundColor Yellow
docker compose -f "$root\docker-compose.dev.yml" up -d postgres qdrant tika
if ($LASTEXITCODE -ne 0) { Write-Error "docker compose up failed."; exit 1 }

Write-Host "      Waiting for postgres to be healthy..." -ForegroundColor DarkGray
$deadline = (Get-Date).AddSeconds(60)
do {
    $pgStatus = docker inspect --format "{{.State.Health.Status}}" open-webui-postgres 2>$null
    if ($pgStatus -eq "healthy") { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)
if ($pgStatus -ne "healthy") { Write-Error "Postgres did not become healthy within 60s."; exit 1 }
Write-Host "      Postgres is healthy." -ForegroundColor Green

# -- backend env vars (consumed by uvicorn child below) ------------------------

$env:CONTENT_EXTRACTION_ENGINE     = 'tika'
$env:TIKA_SERVER_URL               = 'http://localhost:9998'
$env:AIOHTTP_CLIENT_SESSION_SSL    = 'false'
$env:REQUESTS_VERIFY               = 'false'
$env:STATIC_DIR                    = "$root\static"
# Force line-buffered stdout so uvicorn / Python logs appear in real time
# (without this, log lines sit in the pipe buffer until the browser hits the backend).
$env:PYTHONUNBUFFERED              = '1'
# Force UTF-8 for stdout/stderr so emoji / non-ASCII in log lines don't crash
# loguru with UnicodeEncodeError on the default Windows cp1252 console encoding.
$env:PYTHONIOENCODING              = 'utf-8'
# Windows can't make symlinks without admin or Developer Mode; HF falls back to copies anyway.
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
if (-not $env:WEBUI_SECRET_KEY) { $env:WEBUI_SECRET_KEY = 'dev-secret-key-change-in-prod-not-for-real-use' }
if (-not $env:DEFAULT_MODELS)   { $env:DEFAULT_MODELS   = 'Qwen/Qwen3.6-35B-A3B' }

# -- run backend + frontend in this terminal -----------------------------------

Write-Host ""
Write-Host "[2/2] Starting backend (:8080) and frontend (:5173)..." -ForegroundColor Yellow
Write-Host "      Logs are prefixed [BE] and [FE]. Press Ctrl+C to stop both." -ForegroundColor DarkGray
Write-Host "      Note: first browser load can take 30-60s (Vite bundles on demand)." -ForegroundColor DarkGray
Write-Host ""

Set-Location $root

$beCmd = ".venv\Scripts\uvicorn.exe open_webui.main:app --host 0.0.0.0 --port 8080 --reload --app-dir backend"
$feCmd = "npm run dev"

& "$root\node_modules\.bin\concurrently.cmd" `
    --kill-others `
    --names "BE,FE" `
    --prefix-colors "cyan,magenta" `
    $beCmd $feCmd

exit $LASTEXITCODE
