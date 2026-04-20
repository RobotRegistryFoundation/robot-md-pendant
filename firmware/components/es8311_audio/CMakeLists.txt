idf_component_register(
    SRCS "es8311_audio.c"
    INCLUDE_DIRS "include"
    REQUIRES driver es8311 board_hw esp_driver_i2s
)
