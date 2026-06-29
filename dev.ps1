# dev.ps1 - Open WebUI native dev mode with hot reload (single terminal)
#
#   First run (or -Rebuild): creates .venv, pip install, npm install automatically.
#   Subsequent runs:         skips setup, starts infrastructure straight away.
#
#   postgres / qdrant / tika / searxng / minio / valkey -> Docker (detached, volumes persist)
#   Backend  uvicorn --reload -> :8080  (prefixed [BE] in this terminal)
#   Frontend vite dev --host  -> :5173  (prefixed [FE] in this terminal)
#
# Prerequisites (must be installed on the machine):
#   Python 3.11 or 3.12, Node.js 20+, Docker Desktop running
#
# Usage:
#   .\dev.ps1            start (auto-setup on first run), then runs both servers
#   .\dev.ps1 -Rebuild   force reinstall pip + npm deps, then start
#   .\dev.ps1 -Stop      stop all Docker infra

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
    Write-Host "Stopping Docker infra (postgres, qdrant, tika, searxng, minio, valkey)..." -ForegroundColor Yellow
    docker compose -f "$root\docker-compose.dev.yml" stop postgres qdrant tika docling searxng minio valkey
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

Write-Host "[1/2] Starting Docker infra (postgres, qdrant, tika, searxng, minio, valkey)..." -ForegroundColor Yellow
docker compose -f "$root\docker-compose.dev.yml" up -d postgres qdrant tika docling searxng minio valkey createbuckets
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

# Document extraction via the docling container (docker-compose.dev.yml). Docling
# does layout-aware extraction + OCR (scanned PDFs, embedded text in PNG/JPEG),
# unlike Tika which has no OCR. NOTE: CONTENT_EXTRACTION_ENGINE is PersistentConfig
# -- this env only SEEDS the DB on first boot. To switch an existing DB, set it in
# Admin Settings -> Documents (Engine=Docling, URL, Params). Tika is left running
# as a fallback you can flip back to in the UI.
$env:CONTENT_EXTRACTION_ENGINE     = 'docling'
$env:TIKA_SERVER_URL               = 'http://localhost:9998'
$env:DOCLING_SERVER_URL            = 'http://localhost:5001'
# OCR-quality tuning (forwarded as-is to docling-serve /v1/convert/file):
#   do_ocr       -> enable OCR, applied SELECTIVELY: born-digital pages use their
#                   text layer (fast), only pages without one get OCR'd
#   ocr_engine   -> 'easyocr' (torch-based: uses the GPU on the CUDA image, and
#                   avoids the RapidOCR CPU/Chinese-default pitfall)
#   images_scale -> upscale pages so small text is legible to OCR
#   table_mode   -> 'fast' (TableFormer ACCURATE is dramatically slower)
# force_ocr is intentionally omitted (defaults false) so the selective path stays.
# Re-add '"force_ocr": true' ONLY if your PDFs have unreliable text layers -- it
# OCRs every page incl. digital = much slower. Add "ocr_lang": "en,ch" etc. for
# non-English docs (restricting langs is faster + more accurate). All tunable live
# in Admin Settings -> Documents.
$env:DOCLING_PARAMS                = '{"do_ocr": true, "ocr_engine": "easyocr", "images_scale": 2, "table_mode": "fast"}'
# Web search via the searxng container (docker-compose.dev.yml). These only
# seed the DB on first boot; after that, Admin Settings -> Web Search wins.
$env:ENABLE_WEB_SEARCH             = 'true'
$env:WEB_SEARCH_ENGINE             = 'searxng'
$env:SEARXNG_QUERY_URL             = 'http://localhost:8888/search?q=<query>'
$env:AIOHTTP_CLIENT_SESSION_SSL    = 'false'
$env:REQUESTS_VERIFY               = 'false'
# Uncomment if corporate TLS interception breaks cert verification when connecting
# external MCP/OpenAPI tool servers (e.g. staging Sdeck /mcp). Prod default stays on.
$env:AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL = 'false'
# RAG embedding: BAAI/bge-m3 (1024-dim, multilingual; ~2.3GB HF download on first
# use). Seeds the DB on first boot only; after that, Admin Settings -> Documents
# wins. Switching from MiniLM (384-dim) requires resetting the vector DB
# (POST /api/v1/retrieval/reset/db as admin) and re-adding knowledge files.
$env:RAG_EMBEDDING_MODEL           = 'BAAI/bge-m3'
$env:RAG_EMBEDDING_BATCH_SIZE      = '8'
# File storage via the minio container (docker-compose.dev.yml). These are plain
# startup env reads (not PersistentConfig), so they take effect on restart
# regardless of existing DB. The bucket is auto-created by the 'createbuckets'
# one-shot service (S3 provider won't auto-create it). Files saved to local disk
# before this switch are NOT migrated.
$env:STORAGE_PROVIDER              = 's3'
$env:S3_ENDPOINT_URL               = 'http://localhost:9000'
$env:S3_ACCESS_KEY_ID              = 'minioadmin'   # MINIO_ROOT_USER (compose default)
$env:S3_SECRET_ACCESS_KEY          = 'minioadmin'   # MINIO_ROOT_PASSWORD (compose default)
$env:S3_BUCKET_NAME                = 'open-webui'
$env:S3_REGION_NAME                = 'us-east-1'     # any value; MinIO ignores it
# Cache + websocket manager via the valkey container (Redis-compatible, so the
# redis:// scheme applies). Without this, sessions/websocket/task state live in
# process memory and don't survive a restart or scale past one replica.
$env:REDIS_URL                     = 'redis://localhost:6379/0'
$env:ENABLE_WEBSOCKET_SUPPORT      = 'true'
$env:WEBSOCKET_MANAGER             = 'redis'
$env:WEBSOCKET_REDIS_URL           = 'redis://localhost:6379/0'
# Store Qdrant vectors memory-mapped from disk instead of holding them all in
# RAM. Trades a small search-latency hit for a much lower RAM footprint -- the
# right default at 10k-user scale. NOTE: applied at COLLECTION CREATION only;
# existing collections keep their original setting until recreated/reindexed.
$env:QDRANT_ON_DISK                = 'true'
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
if (-not $env:DEFAULT_MODELS)   { $env:DEFAULT_MODELS   = 'deepseek-ai/DeepSeek-V4-Flash' }

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
