#pragma once
#include "esp_err.h"
#include "lvgl.h"

// Init QSPI, SH8601 panel, FT5x06 touch (added in Task 5), and LVGL port.
// Call board_hw_init() before this.
esp_err_t display_lvgl_init(void);
lv_display_t *display_lvgl_get_display(void);
