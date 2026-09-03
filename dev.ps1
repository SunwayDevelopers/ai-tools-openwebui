# dev.ps1 - Open WebUI native dev mode with hot reload (single terminal)
#
#   First run (or -Rebuild): creates .venv, pip install, npm install automatically.
#   Subsequent runs:         skips setup, starts infrastructure straight away.
#
#   postgres / qdrant / minio / redis -> Docker (detached, volumes persist)
#   (docling and searxng are NOT started -- dev uses the team's GPU docling-serve and
#    self-hosted SearXNG on the AI server; see the CONTENT_EXTRACTION_ENGINE and
#    web-search blocks below to run either one locally again)
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

# Keys that came from .env. Set-EnvDefault yields to these, so .env is the single
# source of truth for any value a developer wants to override -- the same file that
# backend/start.sh, backend/dev.sh and bare uvicorn read. See .env.example.
$script:DotEnvKeys = @{}

function Import-DotEnv([string]$path) {
    foreach ($line in (Get-Content $path)) {
        if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
        $k, $v = $line -split '=', 2
        $v = $v -replace "^'(.*)'$", '$1' -replace '^"(.*)"$', '$1'
        $key = $k.Trim()
        $script:DotEnvKeys[$key] = $true
        [System.Environment]::SetEnvironmentVariable($key, $v.Trim(), 'Process')
    }
}

# Wipe every var .env.example ever documents, BEFORE each Import-DotEnv call.
#
# SetEnvironmentVariable(..., 'Process') persists for the life of the calling PowerShell
# terminal -- not just this script's child processes. Ctrl+C only kills uvicorn/vite, never
# the terminal itself, and $script:DotEnvKeys resets on every re-run (it is script-scoped,
# not process-scoped) so it cannot remember what an EARLIER invocation set. Import-DotEnv
# only ever ADDS/overwrites keys it finds in .env; it has no way to notice a key that WAS
# in .env on a previous run in this same terminal and has since been removed or commented
# out -- that value then lingers indefinitely, silently overriding a now-absent .env line
# and any Set-EnvDefault fallback below, until the terminal is closed.
#
# .env.example is treated as the authoritative list of every var this system ever loads
# from .env (per its own header comment) -- clearing exactly that set, right before every
# reload, guarantees a var absent from .env TODAY is genuinely unset today, regardless of
# what a previous run in this terminal left behind. Vars outside that list (e.g. anything
# a developer exports by hand for unrelated purposes) are deliberately left alone.
#
# Unlike .env, a leading '#' in .env.example does NOT mean "not a real key" -- most
# optional/PersistentConfig/dev-only vars are deliberately documented there commented out
# (e.g. "# ENABLE_NOTES='true'") as examples, not omissions. So a line is only skipped
# here if what remains AFTER stripping one leading '#' still isn't a VAR_NAME=... shape
# (i.e. genuine prose, section banners) -- every documented key, commented or not, gets
# cleared.
function Clear-KnownDotEnvKeys([string]$examplePath) {
    if (-not (Test-Path $examplePath)) { return }
    foreach ($line in (Get-Content $examplePath)) {
        $stripped = $line -replace '^\s*#\s*', ''
        # Restricted to the ALL-CAPS shape real env var names use (not just any
        # identifier=...) so prose that happens to contain "word=value" (e.g. a comment
        # mentioning a Python kwarg like allow_credentials=True) isn't mistaken for one.
        # -cmatch, not -match: PowerShell's -match is case-INSENSITIVE by default, which
        # would let a lowercase word through the [A-Z] class anyway.
        if ($stripped -cmatch '^([A-Z_][A-Z0-9_]*)\s*=') {
            [System.Environment]::SetEnvironmentVariable($matches[1], $null, 'Process')
        }
    }
}

# Seed a backend env var UNLESS .env already defines it.
#
# Deliberately keyed on "came from .env" rather than "is already set in the process":
# this script's own assignments persist in the calling PowerShell session, so a plain
# "if not set" test would make a SECOND run in the same terminal silently ignore edits
# to this file. Consequence: a var exported by hand in your shell is still overridden
# here -- put it in .env instead.
function Set-EnvDefault([string]$name, [string]$value) {
    if ($script:DotEnvKeys.ContainsKey($name)) { return }
    [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
}

# -- stop ----------------------------------------------------------------------

if ($Stop) {
    Write-Host "Stopping Docker infra (postgres, qdrant, searxng, minio, redis)..." -ForegroundColor Yellow
    # docling is still named here so a locally-started container gets stopped too.
    docker compose -f "$root\docker-compose.dev.yml" stop postgres qdrant docling searxng minio redis
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

Clear-KnownDotEnvKeys "$root\.env.example"
Import-DotEnv "$root\.env"

# -- Docker infrastructure -----------------------------------------------------

Write-Host "[1/2] Starting Docker infra (postgres, qdrant, minio, redis)..." -ForegroundColor Yellow
# 'docling' is deliberately absent: dev extracts via the team's GPU docling-serve on the
# AI server, so the local CPU container (7GB image) was idle waste. To run it locally
# again: docker compose -f docker-compose.dev.yml up -d docling  AND point
# Admin Settings -> Documents -> Docling URL back at http://localhost:5001.
# 'searxng' is deliberately absent for the same reason: dev searches via the team's
# self-hosted SearXNG on the AI server. To run it locally again:
# docker compose -f docker-compose.dev.yml up -d searxng  AND point
# Admin Settings -> Web Search -> SearXNG Query URL back at http://localhost:8888/search.
docker compose -f "$root\docker-compose.dev.yml" up -d postgres qdrant minio redis createbuckets
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

# Document extraction via Docling: layout-aware extraction + OCR (scanned PDFs,
# embedded text in PNG/JPEG), unlike Tika which has no OCR.
#
# NOTE: both CONTENT_EXTRACTION_ENGINE and DOCLING_SERVER_URL are PersistentConfig --
# these envs only SEEDED the DB on first boot and are IGNORED now. The live values are
# in Admin Settings -> Documents, which points at the team's GPU docling-serve on the
# AI server (https://docling.mymswgl-ai-application.sunway.com). That is why the local
# CPU docling container is no longer started (see the compose block above).
# The localhost URL below is kept only as the seed value for a fresh DB; if you wipe
# the DB and want the GPU server, set it in Admin Settings after first boot.
#
# TIKA_SERVER_URL is deliberately NOT seeded (removed 2026-07-31). `_get_loader` is an
# if/elif chain on the ENGINE, not a cascade, so the tika branch is unreachable while the
# engine is docling -- the value was inert, and carrying it implied a fallback that does
# not exist. Nothing falls back across engines: if docling is down the upload RAISES
# (retrieval/loaders/main.py, "Error calling Docling"), which is what we want. Set the URL
# in Admin Settings if anyone ever deliberately selects Tika.
Set-EnvDefault CONTENT_EXTRACTION_ENGINE     'docling'
Set-EnvDefault DOCLING_SERVER_URL            'http://localhost:5001'
# OCR-quality tuning (forwarded as-is to docling-serve /v1/convert/file):
#   do_ocr       -> enable OCR, applied SELECTIVELY: born-digital pages use their
#                   text layer (fast), only pages without one get OCR'd
#   ocr_engine   -> 'easyocr' (torch-based: uses the GPU on the CUDA image, and
#                   avoids the RapidOCR CPU/Chinese-default pitfall)
#   images_scale -> upscale pages so small text is legible to OCR
#   table_mode   -> 'fast' (TableFormer ACCURATE is dramatically slower)
# force_ocr is intentionally omitted (defaults false) so the selective path stays.
# Re-add '"force_ocr": true' ONLY if your PDFs have unreliable text layers -- it
# OCRs every page incl. digital = much slower.
# ocr_lang is "en" ONLY. It used to be "ch_sim,en" (Sunway EN/ZH/MS: Malay is Latin so
# the English recognizer reads it). BUT the GPU docling-serve on the AI server
# (https://docling.mymswgl-ai-application.sunway.com) has NO Chinese EasyOCR model:
# requesting ch_sim/chi_sim crashes the convert task server-side and returns
# 404 "Task result not found" in ~2s (verified 2026-07-21). "en" works; dropping
# ocr_lang also works (server default == en output) but we pin it explicitly (no drift).
# To restore Chinese OCR: teammate must bake the EasyOCR ch_sim model into the
# docling-serve image, THEN re-test the multi-lang join format before setting it back.
# All tunable live in Admin Settings -> Documents.
Set-EnvDefault DOCLING_PARAMS                '{"do_ocr": true, "ocr_engine": "easyocr", "ocr_lang": "en", "images_scale": 2, "table_mode": "fast"}'
# Sunway: use docling-serve's ASYNC API (submit -> long-poll -> fetch result) instead of the
# blocking sync convert. The sync endpoint is capped by docling-serve's DOCLING_SERVE_MAX_SYNC_WAIT
# (default 120s) and 504s large/OCR-heavy PDFs mid-convert regardless of our client timeout; async
# holds no single request open, so that failure class disappears (and it scales better under
# concurrent uploads). ON by default — DoclingLoader retries synchronously whenever the async path
# gives no verdict (no async endpoint / connection error / contract mismatch), so a server without
# a matching async API degrades gracefully. Set 'false' as a kill-switch to force the sync path.
Set-EnvDefault DOCLING_ASYNC                 'true'
# Web search via the team's self-hosted SearXNG on the AI server (no local container).
# These only seed the DB on first boot; after that, Admin Settings -> Web Search wins.
# NOTE: use the external ingress hostname here, NOT the in-cluster service DNS name
# (http://searxng-http.project-user-zackczc.svc.cluster.local:8080) -- that only
# resolves from inside the K8s cluster and belongs in the Helm manifest, not dev.
# The bare base URL is fine: SearXNG 308-redirects '/' to '/search' preserving the
# query string, and searxng.py appends q/format/etc as params itself.
Set-EnvDefault ENABLE_WEB_SEARCH             'true'
Set-EnvDefault WEB_SEARCH_ENGINE             'searxng'
Set-EnvDefault SEARXNG_QUERY_URL             'https://searxng.mymswgl-ai-application.sunway.com/search'
Set-EnvDefault AIOHTTP_CLIENT_SESSION_SSL    'false'
Set-EnvDefault REQUESTS_VERIFY               'false'
# Uncomment if corporate TLS interception breaks cert verification when connecting
# external MCP/OpenAPI tool servers (e.g. staging Sdeck /mcp). Prod default stays on.
Set-EnvDefault AIOHTTP_CLIENT_SESSION_TOOL_SERVER_SSL 'false'
# RAG embedding: BAAI/bge-m3 (1024-dim, multilingual; ~2.3GB HF download on first
# use). Seeds the DB on first boot only; after that, Admin Settings -> Documents
# wins. Switching from MiniLM (384-dim) requires resetting the vector DB
# (POST /api/v1/retrieval/reset/db as admin) and re-adding knowledge files.
Set-EnvDefault RAG_EMBEDDING_MODEL           'BAAI/bge-m3'
Set-EnvDefault RAG_EMBEDDING_BATCH_SIZE      '32'
# Sunway: skip embedding for SMALL chat attachments (<= RAG_FULL_CONTEXT_MAX_CHARS) and
# inject them full-context instead — makes those uploads extraction-only (instant, no embed
# wait). KB adds + larger files still embed + RAG. OFF until an inference-concurrency stress
# test confirms the fleet handles re-sending full docs each turn (KV-cache/window load).
# Flip to 'true' to test in dev; enable prod only after that test + prefix-caching is on.
Set-EnvDefault RAG_CHAT_ATTACHMENT_FULL_CONTEXT 'true'
# File storage via the minio container (docker-compose.dev.yml). These are plain
# startup env reads (not PersistentConfig), so they take effect on restart
# regardless of existing DB. The bucket is auto-created by the 'createbuckets'
# one-shot service (S3 provider won't auto-create it). Files saved to local disk
# before this switch are NOT migrated.
Set-EnvDefault STORAGE_PROVIDER              's3'
Set-EnvDefault S3_ENDPOINT_URL               'http://localhost:9000'
Set-EnvDefault S3_ACCESS_KEY_ID              'minioadmin'   # MINIO_ROOT_USER (compose default)
Set-EnvDefault S3_SECRET_ACCESS_KEY          'minioadmin'   # MINIO_ROOT_PASSWORD (compose default)
Set-EnvDefault S3_BUCKET_NAME                'open-webui'
Set-EnvDefault S3_REGION_NAME                'us-east-1'     # any value; MinIO ignores it
# Cache + websocket manager via the redis container. Without this,
# sessions/websocket/task state live in process memory and don't survive a
# restart or scale past one replica.
Set-EnvDefault REDIS_URL                     'redis://localhost:6379/0'
Set-EnvDefault ENABLE_WEBSOCKET_SUPPORT      'true'
Set-EnvDefault WEBSOCKET_MANAGER             'redis'
Set-EnvDefault WEBSOCKET_REDIS_URL           'redis://localhost:6379/0'
# Store Qdrant vectors memory-mapped from disk instead of holding them all in
# RAM. Trades a small search-latency hit for a much lower RAM footprint -- the
# right default at 10k-user scale. NOTE: applied at COLLECTION CREATION only;
# existing collections keep their original setting until recreated/reindexed.
Set-EnvDefault QDRANT_ON_DISK                'true'
Set-EnvDefault STATIC_DIR                    "$root\static"
# Force line-buffered stdout so uvicorn / Python logs appear in real time
# (without this, log lines sit in the pipe buffer until the browser hits the backend).
Set-EnvDefault PYTHONUNBUFFERED              '1'
# Force UTF-8 for stdout/stderr so emoji / non-ASCII in log lines don't crash
# loguru with UnicodeEncodeError on the default Windows cp1252 console encoding.
Set-EnvDefault PYTHONIOENCODING              'utf-8'
# Windows can't make symlinks without admin or Developer Mode; HF falls back to copies anyway.
Set-EnvDefault HF_HUB_DISABLE_SYMLINKS_WARNING '1'
# Retention & limits (schat policy) are CODE DEFAULTS as of 2026-07-31 -- 30 chats / 30
# days in env.py, no longer seeded here (they were '0'/'0' in code before, i.e. the policy
# was silently OFF for anyone who forgot the env). Override in .env to change them.
# NOTE: CHAT_RETENTION_DAYS>0 arms the background sweep, which DELETES chats (+ their
# files/vectors) inactive >N days. Actively-used dev chats are safe (recent updated_at);
# only long-abandoned ones get swept.
# FINALIZED 2026-07-23 (A/B closed): pdf -> DOCLING, fast-path OFF. Live tests on GPU-Docling:
# small digital pdf pypdf ~2s (NO table structure, bold lost) vs markitdown ~3s (some structure)
# vs docling ~4s (full tables + bold); large digital docling ~14s (full fidelity) vs pypdf ~1s
# (plain text only). pypdf is a plain char dump — loses table structure, inline bold/emphasis,
# and image-baked text — so Docling wins outright once GPU removes the CPU-timeout reason pypdf
# existed for. The pypdf/markitdown fast-path CODE + A/B harness are KEPT (hide-not-delete): flip
# this back 'true' as a CPU-only-deployment timeout guard if GPU-Docling isn't serving prod yet.
Set-EnvDefault RAG_PDF_FAST_PATH             'false'
# PDF fast-path engine (only used if the fast-path is flipped back ON): 'pypdf' or 'markitdown'.
Set-EnvDefault RAG_PDF_FAST_PATH_ENGINE      'pypdf'
# NB: RAG_PDF_IMAGE_ROUTE_ENABLED is intentionally NOT seeded here — it uses its env.py default
# ('true'). Since 2026-07-21 the reroute routes image-bearing born-digital PDFs to Docling with
# SELECTIVE OCR (it no longer forces OCR — the A/B showed force degraded the native text without
# reading more image text), so leaving it on is beneficial and harmless.
# Office fast-path (Sunway A/B): lightweight loaders for born-digital docx/xlsx/pptx vs
# Docling. DECIDED 2026-07-21: docx/xlsx/pptx -> DOCLING (fast-path OFF) — Docling's TableFormer
# beats text-layer loaders on complex tables, and embedded-image OCR is Docling regardless of
# engine (so the fast-path saves ~nothing on image-heavy office). CSV is pinned to MarkItDown by
# a code carve-out (loaders/main.py), independent of this toggle. The toggle is KEPT (seeds the
# runtime A/B store; flip live in Admin Settings -> Documents) for the post-GPU re-test. ENGINE =
# 'unstructured' or 'markitdown' (only used if you flip the fast-path back ON to A/B).
Set-EnvDefault RAG_OFFICE_FAST_PATH          'false'
Set-EnvDefault RAG_OFFICE_FAST_PATH_ENGINE   'unstructured'
# File-upload allow-list (Sunway SECURITY): which extensions may be uploaded. EMPTY
# (upstream default) = ALLOW-ALL -> .exe/.bat/.tiff/.svg etc. are accepted. This curated
# list = document + safe-image types the app can actually extract. Enforced server-side
# for the UI AND direct API/MCP callers (no ?process=false bypass); frontend accept= is
# cosmetic only. PersistentConfig -> seeds a FRESH DB only; on an existing DB set it in
# Admin Settings -> Documents -> Allowed File Extensions. Add code exts (py,js,ts,...) if
# you want code upload; do NOT add exe/bat/ps1/cmd/sh/env (scripts/secrets).
Set-EnvDefault RAG_ALLOWED_FILE_EXTENSIONS   'pdf,docx,xlsx,pptx,csv,txt,md,png,jpg,jpeg'
Set-EnvDefault RAG_FILE_MAX_COUNT            '10'
Set-EnvDefault RAG_FILE_MAX_SIZE             '30'
# Item 7 local seed (Sunway, 2026-08-24): with ENABLE_PERSISTENT_CONFIG=false (.env),
# env is authoritative instead of the DB, so every one of these needs a value here or
# it silently falls back to its raw code/upstream default. Values verified against
# staging in docs/item7-seed-block.md §2/§5/§6 -- see that file for the two settings
# deliberately NOT copied from it (RAG_ALLOWED_FILE_EXTENSIONS above and
# SEARXNG_QUERY_URL below already have correct values here; the doc's captures for
# both are in the wrong format/missing a required path segment).
Set-EnvDefault OPENAI_API_CONFIGS            '{"0":{"enable":true,"tags":[],"prefix_id":"","model_ids":[],"connection_type":"external","auth_type":"bearer"}}'
Set-EnvDefault CHUNK_SIZE                    '1024'
Set-EnvDefault CHUNK_OVERLAP                 '200'
Set-EnvDefault CHUNK_MIN_SIZE_TARGET         '256'
Set-EnvDefault RAG_TEXT_SPLITTER             'token'
Set-EnvDefault RAG_TOP_K                     '20'
Set-EnvDefault RAG_TOP_K_RERANKER            '10'
Set-EnvDefault WEB_SEARCH_RESULT_COUNT       '5'
Set-EnvDefault WEB_SEARCH_CONCURRENT_REQUESTS '10'
Set-EnvDefault WEB_LOADER_CONCURRENT_REQUESTS '20'
Set-EnvDefault BYPASS_WEB_SEARCH_EMBEDDING_AND_RETRIEVAL 'true'
# Tier ordering + which preset a brand-new chat opens on -- BAAI/bge-m3 deliberately
# dropped from the order list, that MLIS deployment was paused 2026-08-16.
Set-EnvDefault DEFAULT_MODELS                'schat-quick'
Set-EnvDefault MODEL_ORDER_LIST              '["deepseek-ai/DeepSeek-V4-Flash-0731","google/gemma-4-E4B-it","Qwen/Qwen-Image","Qwen/Qwen3.6-35B-A3B","schat-coding","schat-deepthink","schat-quick"]'
# Curated safety nets -- without these, the flip reverts both to upstream's raw
# permissive defaults (terminal/code_interpreter/notes all "on" for every model and
# user), silently re-arming everything the global flags currently suppress.
Set-EnvDefault DEFAULT_MODEL_METADATA        '{"capabilities":{"file_context":true,"vision":true,"file_upload":true,"web_search":true,"image_generation":true,"citations":true,"status_updates":true,"builtin_tools":true,"code_interpreter":false,"terminal":false}}'
Set-EnvDefault USER_PERMISSIONS              '{"features":{"channels":false,"notes":false,"folders":false,"memories":false,"calendar":false,"code_interpreter":false},"chat":{"stt":false,"tts":false,"call":false,"valves":false,"rate_response":false,"temporary":false}}'
# Image generation: enable + model id only. The endpoint URL and its ServiceAccount
# key are NOT here -- like RAG_IMAGE_VISION_LLM_* above, they live in .env only
# (ISO 27001, no committed creds) as IMAGES_OPENAI_API_BASE_URL / IMAGES_OPENAI_API_KEY.
# Enabling this without those two set in .env leaves the feature on but unauthenticated.
Set-EnvDefault ENABLE_IMAGE_GENERATION       'true'
Set-EnvDefault IMAGE_GENERATION_MODEL        'Qwen/Qwen-Image'
# Image vision LLM (Sunway): route uploaded IMAGES to a small vision model (Gemma via
# vLLM/LiteLLM) so text-only models (DeepSeek) get non-text visual understanding OCR
# can't provide. COMBINE_OCR keeps Docling authoritative for text in text-embedded
# images; the vision LLM then only describes visuals. Only images are affected --
# PDFs/documents still go to Docling. Active only when BASE_URL + MODEL are set.
# Plain env reads -> take effect on restart.
# BASE_URL + API_KEY come from .env (ISO 27001 -- no committed creds), loaded by the
# Import-DotEnv call above. Do NOT assign them here: this block runs AFTER Import-DotEnv,
# so an assignment here would silently overwrite the .env values (that's the bug that made
# setting them in .env "not work" before). Set them in .env; see .env.example.
Set-EnvDefault RAG_IMAGE_VISION_LLM_MODEL    'google/gemma-4-E4B-it'   # e.g. 'gemma-4-e2b-it'
# Disable reasoning at request time so chain-of-thought never lands in extracted text
# (the loader also strips leaked reasoning as a fallback). Exact kwarg depends on the
# model's chat template; confirm by curling the vLLM endpoint directly.
# $env:RAG_IMAGE_VISION_LLM_EXTRA_BODY = '{"chat_template_kwargs": {"enable_thinking": false}}'

# -- security response headers: ONE dev-only override ---------------------------
#
# The seven baseline headers are defaulted in code (env.py, "Sunway: security
# response header defaults") and are left alone here on purpose -- dev should test
# what deploys.
#
# CROSS_ORIGIN_RESOURCE_POLICY is the exception, and it is a DEV ARTIFACT, not a
# disagreement with the deployed value. Prod serves the SPA and the API from ONE
# origin, so 'same-origin' is correct there. Dev does not: vite serves the page on
# :5173 while FastAPI serves the API on :8080, and different ports are different
# ORIGINS -- so 'same-origin' makes the browser refuse every image the backend
# sends. Measured 2026-08-11: the schat wordmark, the user avatar and all five
# model avatars failed with net::ERR_BLOCKED_BY_RESPONSE.NotSameOrigin.
#
# 'same-site' fixes it because ports are NOT part of a site, so :5173 and :8080 are
# the same site. It is still tighter than 'cross-origin'.
#
# WHY NOT AN EMPTY VALUE: on Windows `$env:X = ''` DELETES the variable rather than
# emptying it, so os.environ.setdefault re-applies the code default and nothing
# changes. The same trap exists in the Helm chart for a different reason —
# templates/configmap.yaml:68 skips any key whose value is "" — so "set it to empty
# to disable one header" does not work in EITHER place. Override with a real value
# (as here) or change the default in env.py.
Set-EnvDefault CROSS_ORIGIN_RESOURCE_POLICY 'same-site'

# -- deferred / hidden feature flags: NOT SET HERE ANY MORE (2026-07-31) -------
#
# ENABLE_VOICE, ENABLE_TEMPORARY_CHAT, ENABLE_CHAT_ARCHIVE, ENABLE_VERSION_UPDATE_CHECK,
# RAG_IMAGE_VISION_LLM_COMBINE_OCR (env.py) and ENABLE_NOTES, ENABLE_MEMORIES,
# ENABLE_FOLDERS, ENABLE_CODE_INTERPRETER, ENABLE_CALENDAR, ENABLE_AUTOMATIONS,
# ENABLE_MESSAGE_RATING, USER_PERMISSIONS_SETTINGS_INTERFACE (config.py) now default to
# FALSE IN CODE. Seeding them here as well would be pure duplication -- worse, it would
# be a drift trap: change a code default later and this script would keep forcing the old
# value, so local dev would silently test something different from what deploys.
#
# The per-flag rationale lives in the deferred-features table in CLAUDE.md; the code
# defaults live in backend/open_webui/env.py + config.py. To re-enable one for a pilot,
# put it in .env (which now WINS over this script -- see Set-EnvDefault above).
#
# STILL TRUE and unchanged by the above: the config.py ones are PersistentConfig, so on
# an existing dev DB (the postgres volume persists across restarts) the code default only
# applies to a FRESH database -- flip them in Admin Settings to change an existing one.
if (-not $env:WEBUI_SECRET_KEY) { $env:WEBUI_SECRET_KEY = 'dev-secret-key-change-in-prod-not-for-real-use' }
if (-not $env:DEFAULT_MODELS)   { $env:DEFAULT_MODELS   = 'deepseek-ai/DeepSeek-V4-Flash-0731' }

# -- run backend + frontend in this terminal -----------------------------------

Write-Host ""
Write-Host "[2/2] Starting backend (:8080) and frontend (:5173)..." -ForegroundColor Yellow
Write-Host "      Logs are prefixed [BE] and [FE]. Press Ctrl+C to stop both." -ForegroundColor DarkGray
Write-Host "      Note: first browser load can take 30-60s (Vite bundles on demand)." -ForegroundColor DarkGray
Write-Host ""

Set-Location $root

# --ws wsproto: serve WebSockets via wsproto instead of the deprecated `websockets`
# legacy impl, whose transport-level keepalive_ping has a concurrency bug
# (AssertionError in _drain_helper) that drops the socket during long/idle tool
# calls (e.g. Sdeck MCP slide generation). wsproto has no redundant transport ping,
# so Socket.IO's own heartbeat is the single liveness signal. Fixes the chat spinner
# that hangs after a long MCP run even though the response already completed + persisted.
$beCmd = ".venv\Scripts\uvicorn.exe open_webui.main:app --host 0.0.0.0 --port 8080 --reload --app-dir backend --ws wsproto"
$feCmd = "npm run dev"

& "$root\node_modules\.bin\concurrently.cmd" `
    --kill-others `
    --names "BE,FE" `
    --prefix-colors "cyan,magenta" `
    $beCmd $feCmd

exit $LASTEXITCODE
