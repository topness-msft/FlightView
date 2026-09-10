idf_component_register(
    SRCS "flightview_board.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_lvgl_adapter rgb_lcd_port
)

