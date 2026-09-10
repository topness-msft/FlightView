#include "esp_err.h"
#include "esp_log.h"
#include "nvs_flash.h"

#include "flightview_board.h"
#include "flightview_network.h"
#include "flightview_views.h"

static const char *TAG = "flightview";

void app_main(void)
{
    esp_err_t nvs_err = nvs_flash_init();
    if (nvs_err == ESP_ERR_NVS_NO_FREE_PAGES || nvs_err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        nvs_err = nvs_flash_init();
    }
    ESP_ERROR_CHECK(nvs_err);

    ESP_LOGI(TAG, "Starting FlightView 7B native companion");
    ESP_ERROR_CHECK(flightview_board_init());

    QueueHandle_t ui_queue = flightview_views_start();
    ESP_ERROR_CHECK(ui_queue == NULL ? ESP_FAIL : ESP_OK);
    ESP_ERROR_CHECK(flightview_network_start(ui_queue));
}

