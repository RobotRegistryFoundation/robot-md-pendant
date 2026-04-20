#include "wifi_mgr.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "nvs_flash.h"
#include "nvs.h"
#include "freertos/FreeRTOS.h"
#include "freertos/event_groups.h"
#include <string.h>

static const char *TAG = "wifi_mgr";
static EventGroupHandle_t s_evt;
#define BIT_CONNECTED BIT0
#define BIT_FAIL      BIT1
static int s_retry = 0;
static const int MAX_RETRY = 8;

static void on_event(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT && id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (base == WIFI_EVENT && id == WIFI_EVENT_STA_DISCONNECTED) {
        if (s_retry < MAX_RETRY) {
            s_retry++;
            int shift = s_retry > 4 ? 4 : s_retry;
            int backoff_ms = 1000 << shift;
            ESP_LOGW(TAG, "disconnected, retry %d in %dms", s_retry, backoff_ms);
            vTaskDelay(pdMS_TO_TICKS(backoff_ms));
            esp_wifi_connect();
        } else {
            xEventGroupSetBits(s_evt, BIT_FAIL);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        s_retry = 0;
        xEventGroupSetBits(s_evt, BIT_CONNECTED);
    }
}

esp_err_t wifi_mgr_init(void) {
    esp_err_t e = nvs_flash_init();
    if (e == ESP_ERR_NVS_NO_FREE_PAGES || e == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        nvs_flash_erase();
        e = nvs_flash_init();
    }
    ESP_ERROR_CHECK(e);
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_ERROR_CHECK(esp_wifi_init(&cfg));
    s_evt = xEventGroupCreate();
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &on_event, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT,   IP_EVENT_STA_GOT_IP, &on_event, NULL));
    return ESP_OK;
}

esp_err_t wifi_mgr_load_creds(char *ssid_out, size_t sc, char *psk_out, size_t pc) {
    nvs_handle_t h;
    esp_err_t e = nvs_open("wifi", NVS_READONLY, &h);
    if (e != ESP_OK) return ESP_ERR_NVS_NOT_FOUND;
    e = nvs_get_str(h, "ssid", ssid_out, &sc);
    if (e == ESP_OK) e = nvs_get_str(h, "psk", psk_out, &pc);
    nvs_close(h);
    return (e == ESP_OK) ? ESP_OK : ESP_ERR_NVS_NOT_FOUND;
}

esp_err_t wifi_mgr_save_creds(const char *ssid, const char *psk) {
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open("wifi", NVS_READWRITE, &h));
    nvs_set_str(h, "ssid", ssid);
    nvs_set_str(h, "psk", psk);
    esp_err_t e = nvs_commit(h);
    nvs_close(h);
    return e;
}

esp_err_t wifi_mgr_start(const char *ssid, const char *psk) {
    wifi_config_t wc = {0};
    strncpy((char*)wc.sta.ssid, ssid, sizeof(wc.sta.ssid) - 1);
    strncpy((char*)wc.sta.password, psk, sizeof(wc.sta.password) - 1);
    ESP_ERROR_CHECK(esp_wifi_set_mode(WIFI_MODE_STA));
    ESP_ERROR_CHECK(esp_wifi_set_config(WIFI_IF_STA, &wc));
    ESP_ERROR_CHECK(esp_wifi_start());
    EventBits_t b = xEventGroupWaitBits(s_evt, BIT_CONNECTED | BIT_FAIL, pdFALSE, pdFALSE, portMAX_DELAY);
    return (b & BIT_CONNECTED) ? ESP_OK : ESP_FAIL;
}

bool wifi_mgr_is_connected(void) {
    return (xEventGroupGetBits(s_evt) & BIT_CONNECTED) != 0;
}
