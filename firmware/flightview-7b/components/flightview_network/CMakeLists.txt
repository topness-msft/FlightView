idf_component_register(
    SRCS "flightview_network.c"
    INCLUDE_DIRS "include"
    REQUIRES esp_wifi esp_http_client esp_timer esp_netif esp_event flightview_protocol
)
