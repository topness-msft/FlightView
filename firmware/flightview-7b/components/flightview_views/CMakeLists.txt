idf_component_register(
    SRCS "flightview_views.c"
         "fonts/fv_outfit_88.c" "fonts/fv_outfit_64.c" "fonts/fv_outfit_28.c"
         "fonts/fv_mono_80.c" "fonts/fv_mono_96.c" "fonts/fv_mono_40.c"
    INCLUDE_DIRS "include" "fonts"
    REQUIRES lvgl esp_lvgl_adapter flightview_protocol freertos esp_timer
)
