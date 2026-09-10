param(
    [switch]$SkipSetTarget
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$idf = Get-Command idf.py -ErrorAction SilentlyContinue
if (-not $idf) {
    throw "idf.py not found. Open an ESP-IDF 5.5+ PowerShell/CMD environment before building."
}

if (-not $SkipSetTarget) {
    idf.py -C $root set-target esp32s3
    if ($LASTEXITCODE -ne 0) { throw "ESP-IDF target configuration failed" }
}

idf.py -C $root build
if ($LASTEXITCODE -ne 0) { throw "ESP-IDF firmware build failed" }
