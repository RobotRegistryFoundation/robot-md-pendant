idf_component_register(
    SRCS "display_lvgl.c"
    INCLUDE_DIRS "include"
    REQUIRES driver esp_lcd esp_lcd_sh8601 esp_lcd_touch_ft5x06 lvgl board_hw
)
