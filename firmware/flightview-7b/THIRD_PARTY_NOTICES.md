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
The companion's RGB startup explicitly selects USB on EXIO5 before toggling
touch reset, instead of leaving the vendor's all-high output shadow to select
the alternate interface. The remaining board initialization is unchanged.

## Espressif and LVGL components

The ESP-IDF component manager resolves these explicit versions from
`main/idf_component.yml`:

- `lvgl/lvgl` `8.4.0`
- `espressif/esp_lvgl_adapter` `0.5.2`
- `espressif/esp_lcd_touch_gt911` `1.2.1`
- ESP-IDF `>=5.5.0`

The resolved versions from the successful ESP-IDF 5.5.1 build are committed in
`dependencies.lock`.

## Detail-view font assets

The native 7B detail view vendors static TTFs and generated LVGL 8 C font assets
under `components/flightview_views/fonts/`. The generated assets are rebuilt by
the pinned local npm tooling in `tools/fonts/`; no runtime font download or
runtime font engine is used.

### Outfit

- Repository: <https://github.com/Outfitio/Outfit-Fonts>
- Commit: `902773808eb372f70fb34e8946dd1ffe604efc79`
- Source files: `fonts/ttf/Outfit-ExtraBold.ttf`,
  `fonts/ttf/Outfit-Bold.ttf`
- Bundled files: `components/flightview_views/fonts/source_ttf/Outfit-ExtraBold.ttf`,
  `components/flightview_views/fonts/source_ttf/Outfit-Bold.ttf`
- Generated assets: `fv_outfit_88.c`, `fv_outfit_64.c`, and the justified
  secondary text asset `fv_outfit_28.c` for cities, full aircraft names, and
  header secondary text that need Latin-1 coverage such as `São Paulo` and
  `München`
- License: SIL Open Font License 1.1, copied at
  `components/flightview_views/fonts/licenses/Outfit-OFL.txt`
- Source hashes:
  - `Outfit-ExtraBold.ttf`:
    `0f028cbdc61a588bc44fef911e8d2bcfc0bc05b241a9b797686024d269d964b6`
  - `Outfit-Bold.ttf`:
    `f620b69582e06d7e1b3bbde74ed8c5876eadabb038390780db2a3414a1490197`

### JetBrains Mono

- Repository: <https://github.com/JetBrains/JetBrainsMono>
- Commit: `19371302b95d218af43299bce79ddbddd0bc364d`
- Source file: `fonts/ttf/JetBrainsMono-Bold.ttf`
- Bundled file:
  `components/flightview_views/fonts/source_ttf/JetBrainsMono-Bold.ttf`
- Generated assets: `fv_mono_80.c`, `fv_mono_96.c`, `fv_mono_40.c`
- License: SIL Open Font License 1.1, copied at
  `components/flightview_views/fonts/licenses/JetBrainsMono-OFL.txt`
- Source hash:
  - `JetBrainsMono-Bold.ttf`:
    `d22c4f3821d725eb01210d278d95dfcfcaadc34699a06658d47c8a5cc5830ada`

The font generator is `lv_font_conv` `1.5.3`, pinned in
`tools/fonts/package.json` and `tools/fonts/package-lock.json`.
