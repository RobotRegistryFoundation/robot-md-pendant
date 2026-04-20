#include "provisioning.h"
#include "wifi_mgr.h"
#include "nvs.h"
#include "esp_log.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <stdio.h>
#include <string.h>

static const char *TAG = "provisioning";

static void readline(const char *prompt, char *out, size_t cap) {
    printf("%s", prompt);
    fflush(stdout);
    size_t n = 0;
    while (n < cap - 1) {
        int c = getchar();
        if (c == EOF) { vTaskDelay(pdMS_TO_TICKS(20)); continue; }
        if (c == '\r') continue;
        if (c == '\n') break;
        out[n++] = (char)c;
    }
    out[n] = '\0';
}

static esp_err_t save_server_url(const char *url) {
    nvs_handle_t h;
    ESP_ERROR_CHECK(nvs_open("server", NVS_READWRITE, &h));
    nvs_set_str(h, "url", url);
    esp_err_t e = nvs_commit(h);
    nvs_close(h);
    return e;
}

esp_err_t provisioning_run(void) {
    char ssid[32], psk[64], url[128];
    printf("\npendant: provisioning required\n");
    readline("pendant: SSID? ", ssid, sizeof(ssid));
    readline("pendant: PSK?  ", psk, sizeof(psk));
    readline("pendant: Pi URL? (e.g. ws://192.168.1.42:8765) ", url, sizeof(url));
    ESP_ERROR_CHECK(wifi_mgr_save_creds(ssid, psk));
    ESP_ERROR_CHECK(save_server_url(url));
    ESP_LOGI(TAG, "saved; rebooting in 2s");
    vTaskDelay(pdMS_TO_TICKS(2000));
    esp_restart();
    return ESP_OK;  // unreachable
}
