#include "flightview_network.h"

#include <stdio.h>
#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "flightview_config.h"
#include "flightview_protocol.h"
#include "freertos/event_groups.h"

#define FV_WIFI_CONNECTED_BIT BIT0
#define FV_HTTP_TIMEOUT_MS 2000
#define FV_POLL_INTERVAL_MS 1000
#define FV_BACKOFF_MAX_MS 15000
#define FV_NET_TASK_STACK 8192

static const char *TAG = "fv_net";
static EventGroupHandle_t g_wifi_events;
static QueueHandle_t g_ui_queue;
static char g_url[192];
static flightview_ui_message_t g_model_msg;
static flightview_ui_message_t g_transport_msg;

static uint64_t monotonic_ms(void)
{
    return (uint64_t)(esp_timer_get_time() / 1000ULL);
}

static void post_transport(flightview_transport_status_t status, const char *message)
{
    memset(&g_transport_msg, 0, sizeof(g_transport_msg));
    g_transport_msg.type = FV_UI_MSG_TRANSPORT;
    g_transport_msg.transport_status = status;
    g_transport_msg.monotonic_ms = monotonic_ms();
    snprintf(g_transport_msg.transport_message, sizeof(g_transport_msg.transport_message), "%s", message != NULL ? message : "");
    xQueueOverwrite(g_ui_queue, &g_transport_msg);
}

static void post_model(const flightview_model_t *model)
{
    memset(&g_model_msg, 0, sizeof(g_model_msg));
    g_model_msg.type = FV_UI_MSG_MODEL;
    g_model_msg.model = *model;
    xQueueOverwrite(g_ui_queue, &g_model_msg);
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base, int32_t event_id, void *event_data)
{
    (void)arg;
    (void)event_data;
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        xEventGroupClearBits(g_wifi_events, FV_WIFI_CONNECTED_BIT);
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        xEventGroupClearBits(g_wifi_events, FV_WIFI_CONNECTED_BIT);
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        xEventGroupSetBits(g_wifi_events, FV_WIFI_CONNECTED_BIT);
    }
}

static esp_err_t wifi_start(void)
{
    g_wifi_events = xEventGroupCreate();
    if (g_wifi_events == NULL) {
        return ESP_ERR_NO_MEM;
    }

    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init failed");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop failed");
    if (esp_netif_create_default_wifi_sta() == NULL) return ESP_ERR_NO_MEM;

    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&cfg), TAG, "wifi init failed");

    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(WIFI_EVENT, ESP_EVENT_ANY_ID, wifi_event_handler, NULL, NULL),
                        TAG, "wifi handler failed");
    ESP_RETURN_ON_ERROR(esp_event_handler_instance_register(IP_EVENT, IP_EVENT_STA_GOT_IP, wifi_event_handler, NULL, NULL),
                        TAG, "ip handler failed");

    wifi_config_t wifi_config = {0};
    size_t ssid_len = strlen(FLIGHTVIEW_WIFI_SSID);
    size_t password_len = strlen(FLIGHTVIEW_WIFI_PASSWORD);
    if (ssid_len == 0 || ssid_len > sizeof(wifi_config.sta.ssid) ||
        password_len >= sizeof(wifi_config.sta.password)) {
        ESP_LOGE(TAG, "Invalid local Wi-Fi credential lengths");
        return ESP_ERR_INVALID_ARG;
    }
    memcpy(wifi_config.sta.ssid, FLIGHTVIEW_WIFI_SSID, ssid_len);
    memcpy(wifi_config.sta.password, FLIGHTVIEW_WIFI_PASSWORD, password_len);
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_config.sta.sae_pwe_h2e = WPA3_SAE_PWE_BOTH;

    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "set wifi mode failed");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &wifi_config), TAG, "set wifi config failed");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "wifi start failed");
    ESP_LOGI(TAG, "Wi-Fi started; credentials are intentionally not logged");
    return ESP_OK;
}

static esp_err_t fetch_once(void)
{
    char *body = heap_caps_malloc(FV_HTTP_BODY_MAX_BYTES + 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (body == NULL) {
        body = heap_caps_malloc(FV_HTTP_BODY_MAX_BYTES + 2, MALLOC_CAP_8BIT);
    }
    if (body == NULL) {
        post_transport(FV_TRANSPORT_HTTP_ERROR, "No buffer memory");
        return ESP_ERR_NO_MEM;
    }

    const uint64_t start_ms = monotonic_ms();
    esp_http_client_config_t config = {
        .url = g_url,
        .method = HTTP_METHOD_GET,
        .timeout_ms = FV_HTTP_TIMEOUT_MS,
        .buffer_size = 1024,
        .disable_auto_redirect = true,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (client == NULL) {
        heap_caps_free(body);
        post_transport(FV_TRANSPORT_HTTP_ERROR, "HTTP init failed");
        return ESP_FAIL;
    }

    esp_err_t err = esp_http_client_open(client, 0);
    if (err != ESP_OK) {
        esp_http_client_cleanup(client);
        heap_caps_free(body);
        post_transport(FV_TRANSPORT_HTTP_ERROR, "Host unreachable");
        return err;
    }

    int64_t content_length = esp_http_client_fetch_headers(client);
    if (content_length < 0 || content_length > FV_HTTP_BODY_MAX_BYTES) {
        esp_http_client_close(client);
        esp_http_client_cleanup(client);
        heap_caps_free(body);
        post_transport(FV_TRANSPORT_HTTP_ERROR, "Invalid HTTP response length");
        return ESP_ERR_INVALID_RESPONSE;
    }

    int total = 0;
    while (total <= FV_HTTP_BODY_MAX_BYTES) {
        if (monotonic_ms() - start_ms >= FV_HTTP_TIMEOUT_MS) {
            err = ESP_ERR_TIMEOUT;
            break;
        }
        int read = esp_http_client_read(client, body + total, (FV_HTTP_BODY_MAX_BYTES + 1) - total);
        if (read < 0) {
            err = ESP_FAIL;
            break;
        }
        if (read == 0) {
            break;
        }
        total += read;
        if (total > FV_HTTP_BODY_MAX_BYTES) {
            err = ESP_ERR_INVALID_SIZE;
            break;
        }
    }
    const int status = esp_http_client_get_status_code(client);
    const bool complete = esp_http_client_is_complete_data_received(client);
    esp_http_client_close(client);
    esp_http_client_cleanup(client);

    if (total > FV_HTTP_BODY_MAX_BYTES) {
        heap_caps_free(body);
        post_transport(FV_TRANSPORT_PARSE_ERROR, "Body over 64 KiB");
        return ESP_ERR_INVALID_SIZE;
    }
    if (err != ESP_OK || status != 200 || !complete ||
        monotonic_ms() - start_ms > FV_HTTP_TIMEOUT_MS) {
        heap_caps_free(body);
        post_transport(FV_TRANSPORT_HTTP_ERROR, "HTTP error");
        return err != ESP_OK ? err : ESP_FAIL;
    }
    body[total] = '\0';

    flightview_model_t *parsed = heap_caps_malloc(sizeof(*parsed), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (parsed == NULL) {
        parsed = heap_caps_malloc(sizeof(*parsed), MALLOC_CAP_8BIT);
    }
    if (parsed == NULL) {
        heap_caps_free(body);
        post_transport(FV_TRANSPORT_HTTP_ERROR, "No model memory");
        return ESP_ERR_NO_MEM;
    }
    flightview_parse_result_t parse = flightview_parse_display_payload(
        body,
        (size_t)total,
        monotonic_ms(),
        monotonic_ms() - start_ms,
        parsed);
    heap_caps_free(body);
    if (parse != FV_PARSE_OK) {
        char msg[64];
        snprintf(msg, sizeof(msg), "Rejected payload: %s", flightview_parse_result_name(parse));
        heap_caps_free(parsed);
        post_transport(FV_TRANSPORT_PARSE_ERROR, msg);
        return ESP_ERR_INVALID_RESPONSE;
    }

    ESP_LOGI(TAG, "GET /api/v1/display 200 bytes=%d returned=%u display=%s",
             total,
             (unsigned)parsed->aircraft_count,
             parsed->has_display ? "yes" : "no");
    post_model(parsed);
    heap_caps_free(parsed);
    return ESP_OK;
}

static void network_task(void *arg)
{
    (void)arg;
    uint32_t backoff_ms = FV_POLL_INTERVAL_MS;
    uint32_t wifi_backoff_ms = FV_POLL_INTERVAL_MS;
    while (true) {
        EventBits_t bits = xEventGroupGetBits(g_wifi_events);
        if ((bits & FV_WIFI_CONNECTED_BIT) == 0) {
            post_transport(FV_TRANSPORT_WIFI_DISCONNECTED, "Waiting for Wi-Fi/IP");
            esp_err_t connect_err = esp_wifi_connect();
            if (connect_err != ESP_OK) {
                ESP_LOGW(TAG, "Wi-Fi connect attempt: %s", esp_err_to_name(connect_err));
            }
            xEventGroupWaitBits(g_wifi_events, FV_WIFI_CONNECTED_BIT, pdFALSE, pdTRUE,
                                pdMS_TO_TICKS(wifi_backoff_ms + esp_random() % 350U));
            wifi_backoff_ms = wifi_backoff_ms >= FV_BACKOFF_MAX_MS / 2
                ? FV_BACKOFF_MAX_MS : wifi_backoff_ms * 2;
            continue;
        }
        wifi_backoff_ms = FV_POLL_INTERVAL_MS;

        esp_err_t err = fetch_once();
        if (err == ESP_OK) {
            backoff_ms = FV_POLL_INTERVAL_MS;
            vTaskDelay(pdMS_TO_TICKS(FV_POLL_INTERVAL_MS));
        } else {
            uint32_t jitter = esp_random() % 350U;
            vTaskDelay(pdMS_TO_TICKS(backoff_ms + jitter));
            if (backoff_ms < FV_BACKOFF_MAX_MS) {
                backoff_ms *= 2;
                if (backoff_ms > FV_BACKOFF_MAX_MS) {
                    backoff_ms = FV_BACKOFF_MAX_MS;
                }
            }
        }
    }
}

esp_err_t flightview_network_start(QueueHandle_t ui_queue)
{
    if (ui_queue == NULL) {
        return ESP_ERR_INVALID_ARG;
    }
    g_ui_queue = ui_queue;
    int written = snprintf(g_url, sizeof(g_url), "%s/api/v1/display", FLIGHTVIEW_API_BASE_URL);
    if (written <= 0 || written >= (int)sizeof(g_url)) {
        return ESP_ERR_INVALID_ARG;
    }

    post_transport(FV_TRANSPORT_STARTING, "Starting Wi-Fi");
    ESP_RETURN_ON_ERROR(wifi_start(), TAG, "wifi start failed");
    BaseType_t ok = xTaskCreatePinnedToCore(network_task, "fv_http", FV_NET_TASK_STACK, NULL, 5, NULL, 0);
    return ok == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
