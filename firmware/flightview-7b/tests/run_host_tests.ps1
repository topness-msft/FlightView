$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$build = Join-Path $root "build-host"
New-Item -ItemType Directory -Force -Path $build | Out-Null
$exe = Join-Path $build "flightview_host_tests.exe"
gcc -std=c11 -Wall -Wextra -Werror `
    -I (Join-Path $root "components\flightview_protocol\include") `
    (Join-Path $root "components\flightview_protocol\flightview_protocol.c") `
    (Join-Path $root "components\flightview_protocol\flightview_radar.c") `
    (Join-Path $root "tests\host\test_protocol.c") `
    -lm -o $exe
if ($LASTEXITCODE -ne 0) { throw "Host test compilation failed" }
& $exe
if ($LASTEXITCODE -ne 0) { throw "Host protocol tests failed" }
