<#
.SYNOPSIS
  Sync Sunway "SChat.ai" brand assets from the canonical brand repo into this OpenWebUI app.

.DESCRIPTION
  Single source of truth = the @sunway/brand-assets repo. Re-run this whenever the brand
  repo is updated to re-apply the SunwaySans fonts, the red-"S" icon, and the SChat.ai
  wordmark. Assets are vendored into static/ (which SvelteKit serves at fixed paths), so
  no private-registry / git auth is required at Docker build time.

  This is the pragmatic source-of-truth model for THIS app. The gold-standard alternative
  is to add @sunway/brand-assets as a pinned git dependency and run a copy step on build
  (postinstall/prebuild) -- see the note printed at the end.

.PARAMETER BrandRepo
  Path to a local clone of the sunway-brand-assets repo.

.PARAMETER Ref
  Optional git tag/commit to pin the brand repo to before syncing (e.g. 'v0.2.0').
  Reproducible builds: pin a tag rather than tracking 'main'.

.EXAMPLE
  ./sync-brand.ps1
  ./sync-brand.ps1 -Ref v0.2.0
  ./sync-brand.ps1 -BrandRepo 'D:\repos\sunway-brand-assets'
#>
[CmdletBinding()]
param(
    [string]$BrandRepo = 'C:\Users\zackczc\Projects\HPE PCAI Server\Brand\sunway-brand-assets',
    [string]$Ref = ''
)

$ErrorActionPreference = 'Stop'

$App          = $PSScriptRoot
$staticStatic = Join-Path $App 'static\static'
$staticRoot   = Join-Path $App 'static'
$fontsDest    = Join-Path $App 'static\assets\fonts'

if (-not (Test-Path $BrandRepo)) { throw "Brand repo not found: $BrandRepo" }
foreach ($d in @('fonts', 'logos', 'favicons')) {
    if (-not (Test-Path (Join-Path $BrandRepo $d))) {
        throw "Brand repo is missing '$d/'. Is the path correct? $BrandRepo"
    }
}

# Optionally pin the brand repo to a specific tag/commit for reproducible builds.
if ($Ref -ne '') {
    Write-Host "Pinning brand repo to '$Ref' ..."
    & git -C $BrandRepo fetch --tags --quiet
    & git -C $BrandRepo checkout $Ref --quiet
}

# Provenance (printed so the synced version is traceable).
$version = (Get-Content (Join-Path $BrandRepo 'package.json') -Raw | ConvertFrom-Json).version
$commit  = (& git -C $BrandRepo rev-parse --short HEAD 2>$null)
if (-not $commit) { $commit = 'no-git' }

# 1) Fonts: SunwaySans woff2 -> served font dir
Copy-Item (Join-Path $BrandRepo 'fonts\*.woff2') $fontsDest -Force
$fontCount = (Get-ChildItem (Join-Path $fontsDest 'sunwaysans-*.woff2')).Count

# 2) Red-"S" mark -> every PNG / ICO icon + splash + manifest slot (referenced by fixed paths)
$fav = Join-Path $BrandRepo 'favicons\favicon.png'
$slots = @(
    'favicon.png', 'favicon-dark.png', 'favicon-96x96.png', 'apple-touch-icon.png', 'logo.png',
    'splash.png', 'splash-dark.png', 'web-app-manifest-192x192.png', 'web-app-manifest-512x512.png', 'favicon.ico'
)
# Copy to BOTH static/static/ (frontend / prod build) and top-level static/ (backend STATIC_DIR,
# which serves /static in dev). In-app <img> tags resolve via WEBUI_BASE_URL -> the backend, so
# every in-app asset must exist in the top-level static/ dir or it 404s in dev.
foreach ($s in $slots) {
    Copy-Item $fav (Join-Path $staticStatic $s) -Force
    Copy-Item $fav (Join-Path $staticRoot $s) -Force
}

# 3) Wordmark (light) + generated dark variant (near-black body -> white; brand red preserved).
#    Written to BOTH static/static/ (SvelteKit serves this at /static in a prod build) AND
#    top-level static/ (the backend STATIC_DIR, which serves /static in dev where the frontend's
#    WEBUI_BASE_URL points at the backend :8080). In-app <img> tags hit the backend, so the
#    wordmark MUST exist in the top-level static/ dir too, or it 404s in dev.
$wordmark = Join-Path $BrandRepo 'logos\schat-ai-logo.svg'
$svg  = Get-Content $wordmark -Raw
$dark = $svg -replace 'rgb\(10\.980225%, 10\.980225%, 10\.980225%\)', 'rgb(100%, 100%, 100%)'
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
foreach ($dir in @($staticStatic, $staticRoot)) {
    Copy-Item $wordmark (Join-Path $dir 'schat-wordmark.svg') -Force
    [System.IO.File]::WriteAllText((Join-Path $dir 'schat-wordmark-dark.svg'), $dark, $utf8NoBom)
}

Write-Host ''
Write-Host "Synced @sunway/brand-assets v$version ($commit)"
Write-Host "  fonts    : $fontCount SunwaySans woff2 -> static/assets/fonts/"
Write-Host "  icons    : $($slots.Count) slots + top-level favicon -> red-'S' mark"
Write-Host "  wordmark : schat-wordmark.svg + schat-wordmark-dark.svg -> static/static/"
Write-Host ''
Write-Host "Note: tab + app icons use the canonical brand favicon.png (red 'S'); the wordmark"
Write-Host "      (schat-wordmark.svg + dark variant) is used on the login + sidebar header."
Write-Host "Upgrade path: add @sunway/brand-assets as a pinned git dependency and call this script"
Write-Host "      from a 'prebuild' npm hook so 'npm run build' always re-syncs."
