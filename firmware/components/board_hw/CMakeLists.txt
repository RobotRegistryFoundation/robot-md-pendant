idf_component_register(
    SRCS "board_hw.c"
    INCLUDE_DIRS "include"
    REQUIRES driver esp_driver_i2c
    PRIV_REQUIRES esp_io_expander_tca9554 esp_io_expander
)
