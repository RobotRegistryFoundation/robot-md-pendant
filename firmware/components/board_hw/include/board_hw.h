#pragma once
#include "esp_err.h"
#include "driver/i2c_master.h"

// Initialize I2C bus, I/O expander (TCA9554), enable speaker amp,
// take LCD out of reset. Must be called once at boot.
esp_err_t board_hw_init(void);

// Return the shared I2C master bus handle (valid after board_hw_init()).
i2c_master_bus_handle_t board_hw_i2c_bus(void);
