# First USB hookup checklist

Physical validation is intentionally deferred until the Waveshare
ESP32-S3-Touch-LCD-7B board is available. Do not flash from this checklist until
deploy-runner/owner coordination confirms the board, cable, and COM port.

## Before plugging in

1. Install ESP-IDF 5.5 and open its configured shell using the
   [official Windows setup guide](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32s3/get-started/windows-setup.html).
2. Run the commands below from the FlightView repository root.
3. Create the local Wi-Fi/API header:

   ```powershell
   Copy-Item firmware\flightview-7b\components\flightview_network\include\flightview_config_example.h `
     firmware\flightview-7b\components\flightview_network\include\flightview_config_local.h
   ```

4. Edit only:
   - `FLIGHTVIEW_WIFI_SSID`
   - `FLIGHTVIEW_WIFI_PASSWORD`
   - `FLIGHTVIEW_API_BASE_URL`

   Do not commit the local header.

## Software-only validation first

From repo root:

```powershell
.\firmware\flightview-7b\tests\run_host_tests.ps1
.\firmware\flightview-7b\scripts\build_idf.ps1
.\firmware\flightview-7b\scripts\build_idf_tests.ps1
```

If a dev/mock FlightView API is live:

```powershell
.\firmware\flightview-7b\tests\probe_live_api.ps1 -Url http://127.0.0.1:5051/api/v1/display
```

Expected probe output shape:

```text
schema=1 aircraft=<0..32> display=<yes|no> health=<ok|error> source=<rtlsdr|opensky|mock|unknown> stale=<yes|no> initial=<yes|no>
live API probe bytes=<65536-or-less> url=<url>
```

## First physical evidence to capture

1. Enumerate ports after plugging in the USB data cable. Expected: a new non-
   Bluetooth COM port appears.
2. Flash and observe the unmodified
   [official Waveshare LVGL8 7B demo](https://github.com/waveshareteam/ESP32-S3-Touch-LCD-7B/tree/c652c902db607f7ffb376257393cfd7657aa6428/examples/ESP-IDF/13_lvgl_v8_demo)
   first. Use the 7B example, not the original 800x480 board's firmware.
3. Only after that baseline works, flash this firmware:

   ```powershell
   idf.py -C firmware\flightview-7b -p COMx flash monitor
   ```

4. Save serial monitor evidence showing:
   - Wi-Fi connected, without credentials printed.
   - `GET /api/v1/display` HTTP 200.
   - Payload byte count.
   - Parsed returned count and display yes/no.
   - Reconnect/backoff after server or Wi-Fi interruption.
   - Heap/PSRAM startup values.

5. Save photos of the real board screen:
   - Startup/awaiting data.
   - Modern radar/list.
   - Yellow detail view.
   - Stale source warning.
   - Transport offline warning with last valid display retained.

## Still not done until

- ESP-IDF app and test app build in the IDF shell.
- The resolved dependency lockfile is reviewed and preserved if generated.
- The board renders readable 1024x600 LVGL views without clipping critical fields.
- No watchdog reset or unbounded heap decline appears during repeated max-payload
  parsing and reconnect cycles.
