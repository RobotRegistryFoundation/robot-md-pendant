#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "nvs.h"
#include "board_hw.h"
#include "display_lvgl.h"
#include "app_state.h"
#include "wifi_mgr.h"
#include "provisioning.h"
#include "ui.h"
#include "lvgl.h"
#include "app_task.h"

static const char *TAG = "main";

static void lvgl_tick_cb(void *arg) { lv_tick_inc(2); }

void app_main(void) {
    ESP_LOGI(TAG, "boot");
    app_state_init();
    ESP_ERROR_CHECK(board_hw_init());
    ESP_ERROR_CHECK(display_lvgl_init());
    ui_init();

    const esp_timer_create_args_t timer_args = {.callback = lvgl_tick_cb, .name = "lvgl_tick"};
    esp_timer_handle_t tick;
    ESP_ERROR_CHECK(esp_timer_create(&timer_args, &tick));
    ESP_ERROR_CHECK(esp_timer_start_periodic(tick, 2000));

    ESP_ERROR_CHECK(wifi_mgr_init());
    char ssid[32] = {0}, psk[64] = {0};
    if (wifi_mgr_load_creds(ssid, sizeof(ssid), psk, sizeof(psk)) == ESP_ERR_NVS_NOT_FOUND) {
        ESP_LOGI(TAG, "no creds — entering provisioning");
        provisioning_run();
        // does not return
    }
    ESP_LOGI(TAG, "creds found, ssid=%s", ssid);
    ui_show_connecting(ssid);
    ESP_ERROR_CHECK(wifi_mgr_start(ssid, psk));

    nvs_handle_t sh; char url[128] = {0}; size_t url_len = sizeof(url);
    ESP_ERROR_CHECK(nvs_open("server", NVS_READONLY, &sh));
    ESP_ERROR_CHECK(nvs_get_str(sh, "url", url, &url_len));
    nvs_close(sh);
    ESP_LOGI(TAG, "connecting to %s", url);
    ESP_ERROR_CHECK(app_task_start(url));

    while (1) {
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
