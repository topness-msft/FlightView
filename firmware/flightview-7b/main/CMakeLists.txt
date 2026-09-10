idf_component_register(
    SRCS "main.c"
    REQUIRES nvs_flash flightview_board flightview_network flightview_protocol flightview_views
)
