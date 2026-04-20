#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "board_hw.h"

static const char *TAG = "main";

void app_main(void)
{
    ESP_LOGI(TAG, "robot-md-pendant firmware v0.1");
    ESP_ERROR_CHECK(board_hw_init());
    ESP_LOGI(TAG, "board init complete, entering idle loop");
    while (1) {
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
