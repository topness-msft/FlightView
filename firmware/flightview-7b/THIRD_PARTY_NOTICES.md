# Third-party notices

## Waveshare ESP32-S3-Touch-LCD-7B board components

This project vendors the board support components `gpio`, `i2c`, `io_extension`, and
`rgb_lcd_port` from Waveshare's official public repository:

- Repository: <https://github.com/waveshareteam/ESP32-S3-Touch-LCD-7B>
- Commit: `c652c902db607f7ffb376257393cfd7657aa6428`
- Source path: `examples/ESP-IDF/13_lvgl_v8_demo/components/`
- License verified: Apache License 2.0, copied at `third_party/waveshare/LICENSE`

The vendored files are used to preserve the 7B board RGB timings, GT911 touch
startup, I2C expander, and backlight behavior from the official LVGL 8 example.

## Espressif and LVGL components

The ESP-IDF component manager resolves these explicit versions from
`main/idf_component.yml`:

- `lvgl/lvgl` `8.4.0`
- `espressif/esp_lvgl_adapter` `0.5.2`
- `espressif/esp_lcd_touch_gt911` `1.2.1`
- ESP-IDF `>=5.5.0`

No generated lockfile is committed until the first successful ESP-IDF build in an
IDF 5.5+ environment.

