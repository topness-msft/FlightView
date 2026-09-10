param(
    [string]$Url = "http://127.0.0.1:5051/api/v1/display"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$build = Join-Path $root "build-host"
New-Item -ItemType Directory -Force -Path $build | Out-Null
$json = Join-Path $build "display.json"
$exe = Join-Path $build "flightview_probe.exe"

$response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
$bytes = [Text.Encoding]::UTF8.GetByteCount($response.Content)
if ($bytes -gt 65536) {
    throw "Display payload exceeds firmware body cap: $bytes bytes"
}
[IO.File]::WriteAllText($json, $response.Content, [Text.UTF8Encoding]::new($false))

gcc -std=c11 -Wall -Wextra -Werror `
    -I (Join-Path $root "components\flightview_protocol\include") `
    (Join-Path $root "components\flightview_protocol\flightview_protocol.c") `
    (Join-Path $root "tests\host\probe_display_payload.c") `
    -lm -o $exe
if ($LASTEXITCODE -ne 0) { throw "Host probe compilation failed" }
& $exe $json
if ($LASTEXITCODE -ne 0) {
    throw "Firmware parser rejected live API payload"
}
Write-Host "live API probe bytes=$bytes url=$Url"
