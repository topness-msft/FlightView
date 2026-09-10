# FlightView ESP32-S3 7B companion firmware

Native read-only companion for the Waveshare ESP32-S3-Touch-LCD-7B. It renders
FlightView's modern radar/list or yellow overhead detail view from:

`GET http://configured-host:5000/api/v1/display`

This firmware does not fetch aircraft data, enrich routes, select aircraft, save
settings, run OTA, handle touch input, or flash/deploy itself. Flashing physical
boards is gated by deploy-runner.

## Hardware and SDK

- Board: Waveshare ESP32-S3-Touch-LCD-7B, 1024x600, 16 MB flash, 8 MB PSRAM.
- ESP-IDF: `>=5.5.0`.
- Component versions pinned in `main/idf_component.yml`:
  - `lvgl/lvgl` `8.4.0`
  - `espressif/esp_lvgl_adapter` `0.5.2`
  - `espressif/esp_lcd_touch_gt911` `1.2.1`
- Vendored official Waveshare board components are from commit
  `c652c902db607f7ffb376257393cfd7657aa6428`; license is Apache-2.0.

The touchscreen 7B has been brought up with the native modern UI, live LAN feed,
and the larger detail typography. The reproducible Windows build uses official
ESP-IDF `v5.5.1` installed under
`%USERPROFILE%\.espressif\frameworks\esp-idf-v5.5.1`; Docker CLI was present,
but the Docker Desktop Linux daemon was unavailable. The application, SDK test
application, and unmodified vendor baseline compile with that toolchain.

The reproducible user-scope SDK setup used for the software build gate was:

```powershell
$env:IDF_TOOLS_PATH = "$env:USERPROFILE\.espressif"
git clone --branch v5.5.1 --recursive --depth 1 https://github.com/espressif/esp-idf.git `
  "$env:USERPROFILE\.espressif\frameworks\esp-idf-v5.5.1"
& "$env:USERPROFILE\.espressif\frameworks\esp-idf-v5.5.1\install.ps1" esp32s3
& "$env:USERPROFILE\.espressif\frameworks\esp-idf-v5.5.1\export.ps1"
python "$env:USERPROFILE\.espressif\frameworks\esp-idf-v5.5.1\tools\idf.py" --version
```

## Local configuration

Copy the example header and edit it locally:

```powershell
Copy-Item firmware\flightview-7b\components\flightview_network\include\flightview_config_example.h `
  firmware\flightview-7b\components\flightview_network\include\flightview_config_local.h
```

Set:

- `FLIGHTVIEW_WIFI_SSID`: 2.4 GHz Wi-Fi SSID.
- `FLIGHTVIEW_WIFI_PASSWORD`: Wi-Fi password.
- `FLIGHTVIEW_API_BASE_URL`: Pi/dev FlightView base URL, for example
  `http://192.168.1.50:5000`.

`components\flightview_network\include\flightview_config_local.h` is ignored by
this subtree's `.gitignore`. Do not log or commit Wi-Fi credentials.

## Build

From an ESP-IDF 5.5+ shell:

```powershell
idf.py -C firmware\flightview-7b -B b\app set-target esp32s3
idf.py -C firmware\flightview-7b -B b\app build
idf.py -C firmware\flightview-7b -B b\app size
```

Convenience build wrapper, which never flashes:

```powershell
.\firmware\flightview-7b\scripts\build_idf.ps1
```

The wrapper defaults to the repository-local `b\app` build directory. This keeps
Windows object/dependency paths shorter than `firmware\flightview-7b\build`,
which can exceed path limits in managed LVGL adapter sources in long worktrees.
The generated app lockfile is preserved at `firmware\flightview-7b\dependencies.lock`.

Do not flash without deploy-runner/owner coordination:

```powershell
idf.py -C firmware\flightview-7b -B b\app -p COMx flash monitor
```

## Host protocol tests

When a host C compiler is available, run:

```powershell
.\firmware\flightview-7b\tests\run_host_tests.ps1
```

These tests validate the bounded parser/model/radar logic without hardware:

- Body cap rejects payloads over 64 KiB.
- Unsupported schema and required metadata corruption are rejected.
- Aircraft array is capped at 32 and list rendering is capped at 10.
- Firmware string byte caps mirror the server `TEXT_LIMITS` export for the v1
  contract.
- Unknown numerics remain invalid for dash rendering rather than becoming zero.
- Source age and local monotonic timing use 64-bit milliseconds.
- `health.data_source` accepts `rtlsdr`, `opensky`, `mock`, and the server's safe
  fallback value `unknown`.
- Server `display` is authoritative; the firmware does not pick nearest locally.
- UTF-8 `\u` strings decode into fixed buffers without splitting.
- State age advances with monotonic time through old successful responses and
  transport failures.
- Cardinal radar projection maps 0° top, 90° right, 180° bottom, 270° left.

An ESP-IDF Unity test app is also provided under `test\` for SDK environments:

```powershell
idf.py -C firmware\flightview-7b\test -B b\test set-target esp32s3
idf.py -C firmware\flightview-7b\test -B b\test build
idf.py -C firmware\flightview-7b\test -B b\test size
```

Hardware flash/monitor of the test app also waits for deploy-runner.

Convenience test-app build wrapper, which never flashes:

```powershell
.\firmware\flightview-7b\scripts\build_idf_tests.ps1
```

The test wrapper defaults to `b\test` for the same Windows path-length reason.
The SDK test app uses `test\sdkconfig.defaults` so its generated image matches
the board class used by the main app: ESP32-S3, 16 MB flash, and PSRAM enabled.
Its primary console is native USB Serial/JTAG. Tests run once after a short
startup delay, then repeat their final counts every two seconds so reconnecting
the serial monitor cannot lose the result. The diagnostic image intentionally
does not initialize the LCD.

To check parser compatibility against a running FlightView server without
hardware:

```powershell
.\firmware\flightview-7b\tests\probe_live_api.ps1 -Url http://127.0.0.1:5051/api/v1/display
```

The probe downloads one bounded response into ignored `build-host\`, compiles the
host parser probe, verifies the v1 payload, and prints parsed counts/status.

## Runtime behavior

- One HTTP worker task, one outstanding request at a time.
- 1 second normal cadence; 2 second HTTP timeout.
- Backoff starts at 1 second, caps at 15 seconds, and includes jitter.
- Full response body is capped at 64 KiB, including chunked responses.
- Fully validated fixed-size models are sent through a one-slot overwrite queue
  to the LVGL owner.
- Transport heartbeat messages are sent separately from model updates.
- Last valid model remains visible on Wi-Fi/HTTP/parse failures with a warning.
- Source freshness age comes from the server plus request duration and local
  64-bit monotonic elapsed time; repeated old successful responses do not reset
  age. The stale threshold itself is server-owned.

## UI notes

The native UI references the modern browser colors in `src\static\style.css`:
navy/blue radar/list plus `#FECB00` and `#1A1A1A` detail signage. Detail typography
uses bundled, licensed Outfit and JetBrains Mono subsets: 88 px carrier text
(64 px for longer names), 80 px aircraft codes, and 96 px airport codes.
This prioritizes carrier, airframe, and route readability on the smaller panel.
Secondary labels retain the lightweight builtin Montserrat fonts.

Missing routes collapse and recenter the remaining content. Repeated type codes
and registrations are suppressed. Telemetry uses comma-separated values with
units on separate lines. Screen visibility and unchanged labels remain stable
between updates; the status timer does not repaint the entire detail view.

Font C assets are committed, so normal ESP-IDF builds do not require Node.js or
network font downloads. To reproduce them from the bundled, hash-checked TTFs:

```powershell
npm ci --prefix firmware\flightview-7b\tools\fonts --no-audit --no-fund
npm --prefix firmware\flightview-7b\tools\fonts test
```

The generator checks glyph coverage, text widths, and the added-data budget.
Carrier/city fonts include ASCII and Latin-1; they are not full-Unicode fonts.
`CONFIG_LV_USE_FONT_COMPRESSED=y` is required and guarded at compile time.
See `components\flightview_views\fonts\SOURCE_FONTS.md` for source revisions,
licenses, and coverage.

The radar draws up to 32 blips with heading indicators. The side list shows up to
10 rows, with explicit list/radar/total counts. Aircraft without a known position
remain in the list but are not plotted at a made-up radar position. Detail view
shows route, cities, airframe, registration, the modern four-column
altitude/speed/distance/vertical-speed row, heading, compass, direction, and
nearby count. Unknown values render as dashes.

The parser rejects invalid UTF-8, non-JSON number syntax, contradictory
metadata, and nesting beyond 16 containers. It uses fixed model buffers and does
not require a null-terminated response. The network task is the sole producer of
UI messages; Wi-Fi event callbacks only update connectivity flags. Both tasks
use the same 64-bit `esp_timer` clock, and the stale warning advances between
responses rather than relying only on the server's last stale flag.

## Bringing up another board

See `FIRST_USB_HOOKUP.md` for the exact first-board checklist.

1. Flash the unmodified Waveshare 7B LVGL8 example already built under the
   ignored `temp\ws8` / `b\ws8` software baseline, or rebuild it from
   `FIRST_USB_HOOKUP.md`.
2. Flash this firmware only after deploy-runner confirms COM port and board
   access.
3. Capture serial logs for Wi-Fi, HTTP 200, payload size, parsed counts,
   reconnect/backoff, and memory stability.
4. Capture real board photos for radar/list, detail, startup, stale, and offline
   states.
