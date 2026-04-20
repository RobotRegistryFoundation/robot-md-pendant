#include "ws_client.h"
#include "esp_websocket_client.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "protocol.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <string.h>

static const char *TAG = "ws_client";
static esp_websocket_client_handle_t s_cli = NULL;
static ws_text_cb_t s_on_text = NULL;
static ws_bin_cb_t  s_on_bin = NULL;
static esp_timer_handle_t s_hb_timer = NULL;
static uint32_t s_hb_seq = 0;
static bool s_connected = false;

static void hb_cb(void *arg) {
    if (!s_connected) return;
    char buf[48];
    int n = protocol_emit_heartbeat(buf, sizeof(buf), ++s_hb_seq);
    if (n > 0) esp_websocket_client_send_text(s_cli, buf, n, 10 / portTICK_PERIOD_MS);
}

static void ev(void *arg, esp_event_base_t base, int32_t id, void *data) {
    esp_websocket_event_data_t *d = data;
    switch ((esp_websocket_event_id_t)id) {
    case WEBSOCKET_EVENT_CONNECTED:
        s_connected = true;
        ESP_LOGI(TAG, "connected");
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
    case WEBSOCKET_EVENT_ERROR:
        s_connected = false;
        ESP_LOGW(TAG, "disconnected");
        break;
    case WEBSOCKET_EVENT_DATA:
        if (d->op_code == 0x1 /* text */ && s_on_text)
            s_on_text(d->data_ptr, d->data_len);
        else if (d->op_code == 0x2 /* binary */ && s_on_bin)
            s_on_bin((const uint8_t*)d->data_ptr, d->data_len);
        break;
    default: break;
    }
}

esp_err_t ws_client_init(const char *url, ws_text_cb_t ontxt, ws_bin_cb_t onbin) {
    s_on_text = ontxt;
    s_on_bin = onbin;
    esp_websocket_client_config_t cfg = {
        .uri = url,
        .reconnect_timeout_ms = 1000,
        .network_timeout_ms = 10000,
        .buffer_size = 16 * 1024,
    };
    s_cli = esp_websocket_client_init(&cfg);
    if (!s_cli) return ESP_FAIL;
    ESP_ERROR_CHECK(esp_websocket_register_events(s_cli, WEBSOCKET_EVENT_ANY, ev, NULL));
    const esp_timer_create_args_t t = { .callback = hb_cb, .name = "ws_hb" };
    ESP_ERROR_CHECK(esp_timer_create(&t, &s_hb_timer));
    return ESP_OK;
}

esp_err_t ws_client_start(void) {
    ESP_ERROR_CHECK(esp_websocket_client_start(s_cli));
    return esp_timer_start_periodic(s_hb_timer, 100000);  // 100ms = 10Hz
}

esp_err_t ws_client_stop(void) {
    esp_timer_stop(s_hb_timer);
    return esp_websocket_client_stop(s_cli);
}

bool ws_client_is_connected(void) { return s_connected; }

esp_err_t ws_client_send_text(const char *data, size_t len) {
    int n = esp_websocket_client_send_text(s_cli, data, len, 100 / portTICK_PERIOD_MS);
    return (n > 0) ? ESP_OK : ESP_FAIL;
}

esp_err_t ws_client_send_bin(const uint8_t *data, size_t len) {
    int n = esp_websocket_client_send_bin(s_cli, (const char*)data, len, 100 / portTICK_PERIOD_MS);
    return (n > 0) ? ESP_OK : ESP_FAIL;
}
