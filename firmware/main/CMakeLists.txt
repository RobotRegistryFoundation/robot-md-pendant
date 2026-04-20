idf_component_register(
    SRCS "main.c"
    INCLUDE_DIRS "."
    REQUIRES board_hw display_lvgl wifi_mgr app app_state ui lvgl nvs_flash es8311_audio
)
