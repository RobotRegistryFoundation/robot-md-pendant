#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "board_hw.h"
#include "display_lvgl.h"
#include "lvgl.h"

static const char *TAG = "main";

static void lvgl_tick_cb(void *arg) { lv_tick_inc(2); }

void app_main(void) {
    ESP_LOGI(TAG, "boot");
    ESP_ERROR_CHECK(board_hw_init());
    ESP_ERROR_CHECK(display_lvgl_init());

    const esp_timer_create_args_t timer_args = {.callback = lvgl_tick_cb, .name = "lvgl_tick"};
    esp_timer_handle_t tick;
    ESP_ERROR_CHECK(esp_timer_create(&timer_args, &tick));
    ESP_ERROR_CHECK(esp_timer_start_periodic(tick, 2000));  // 2ms

    while (1) {
        lv_timer_handler();
        vTaskDelay(pdMS_TO_TICKS(5));
    }
}
