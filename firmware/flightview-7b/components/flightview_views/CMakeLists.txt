idf_component_register(
    SRCS "flightview_views.c"
    INCLUDE_DIRS "include"
    REQUIRES lvgl esp_lvgl_adapter flightview_protocol freertos esp_timer
)
