#include "board_hw.h"
#include "board_pins.h"
#include "driver/i2c_master.h"
#include "esp_io_expander.h"
#include "esp_io_expander_tca9554.h"
#include "esp_log.h"
#include "esp_check.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "board_hw";

static i2c_master_bus_handle_t s_i2c_bus = NULL;
static esp_io_expander_handle_t s_io_exp = NULL;

static esp_err_t i2c_bus_init(void)
{
    if (s_i2c_bus) {
        return ESP_OK;
    }
    i2c_master_bus_config_t cfg = {
        .clk_source = I2C_CLK_SRC_DEFAULT,
        .sda_io_num = BSP_I2C_SDA,
        .scl_io_num = BSP_I2C_SCL,
        .i2c_port = BSP_I2C_NUM,
        .glitch_ignore_cnt = 7,
        .flags.enable_internal_pullup = true,
        .trans_queue_depth = 0,
    };
    return i2c_new_master_bus(&cfg, &s_i2c_bus);
}

esp_err_t board_hw_init(void)
{
    ESP_RETURN_ON_ERROR(i2c_bus_init(), TAG, "i2c bus init");

    ESP_RETURN_ON_ERROR(
        esp_io_expander_new_i2c_tca9554(s_i2c_bus, BSP_IO_EXPANDER_ADDR, &s_io_exp),
        TAG, "tca9554 init");

    const uint32_t out_mask = BIT(BSP_IO_EXP_LCD_RST) | BIT(BSP_IO_EXP_SPK_EN);
    ESP_RETURN_ON_ERROR(
        esp_io_expander_set_dir(s_io_exp, out_mask, IO_EXPANDER_OUTPUT),
        TAG, "set dir");

    // Pulse LCD reset low -> high (active-low reset)
    ESP_RETURN_ON_ERROR(
        esp_io_expander_set_level(s_io_exp, BIT(BSP_IO_EXP_LCD_RST), 0),
        TAG, "lcd rst low");
    vTaskDelay(pdMS_TO_TICKS(20));
    ESP_RETURN_ON_ERROR(
        esp_io_expander_set_level(s_io_exp, BIT(BSP_IO_EXP_LCD_RST), 1),
        TAG, "lcd rst high");
    vTaskDelay(pdMS_TO_TICKS(120));

    // Enable speaker amplifier
    ESP_RETURN_ON_ERROR(
        esp_io_expander_set_level(s_io_exp, BIT(BSP_IO_EXP_SPK_EN), 1),
        TAG, "spk en");

    ESP_LOGI(TAG, "board hw init ok");
    return ESP_OK;
}

i2c_master_bus_handle_t board_hw_i2c_bus(void)
{
    return s_i2c_bus;
}
