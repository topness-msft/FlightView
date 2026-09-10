param(
    [switch]$SkipSetTarget,
    [string]$BuildDir
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$repoRoot = Split-Path -Parent (Split-Path -Parent $root)

if (-not $BuildDir) {
    $BuildDir = Join-Path $repoRoot "b\app"
} elseif (-not [System.IO.Path]::IsPathRooted($BuildDir)) {
    $BuildDir = Join-Path (Get-Location) $BuildDir
}

$idf = Get-Command idf.py -ErrorAction SilentlyContinue
if (-not $idf) {
    throw "idf.py not found. Open an ESP-IDF 5.5+ PowerShell/CMD environment before building."
}

if (-not $SkipSetTarget) {
    idf.py -C $root -B $BuildDir set-target esp32s3
    if ($LASTEXITCODE -ne 0) { throw "ESP-IDF target configuration failed" }
}

idf.py -C $root -B $BuildDir build
if ($LASTEXITCODE -ne 0) { throw "ESP-IDF firmware build failed" }
