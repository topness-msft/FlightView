param(
    [switch]$SkipSetTarget
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$testRoot = Join-Path $root "test"

$idf = Get-Command idf.py -ErrorAction SilentlyContinue
if (-not $idf) {
    throw "idf.py not found. Open an ESP-IDF 5.5+ PowerShell/CMD environment before building."
}

if (-not $SkipSetTarget) {
    idf.py -C $testRoot set-target esp32s3
    if ($LASTEXITCODE -ne 0) { throw "ESP-IDF test target configuration failed" }
}

idf.py -C $testRoot build
if ($LASTEXITCODE -ne 0) { throw "ESP-IDF test app build failed" }
