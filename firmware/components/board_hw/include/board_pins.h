#pragma once
// Pins confirmed from /tmp/waveshare-c6/examples/ESP-IDF-v5.5.1/03_esp-brookesia/components/esp32_c6_touch_amoled_1_8/include/bsp/esp32_c6_touch_amoled_1_8.h

#include "driver/gpio.h"

#define BSP_I2C_SDA         (GPIO_NUM_8)
#define BSP_I2C_SCL         (GPIO_NUM_9)
#define BSP_I2C_NUM         (0)

// LCD (SH8601 QSPI)
#define BSP_LCD_HOST        (SPI2_HOST)
#define BSP_LCD_PCLK        (GPIO_NUM_0)
#define BSP_LCD_DATA0       (GPIO_NUM_1)
#define BSP_LCD_DATA1       (GPIO_NUM_2)
#define BSP_LCD_DATA2       (GPIO_NUM_3)
#define BSP_LCD_DATA3       (GPIO_NUM_4)
#define BSP_LCD_CS          (GPIO_NUM_5)

// Touch (FT5x06 I2C)
#define BSP_TOUCH_INT       (GPIO_NUM_7)

// I/O expander TCA9554 (I2C @ 0x20)
#define BSP_IO_EXPANDER_ADDR (0x20)
#define BSP_IO_EXP_SPK_EN   (7)   // expander pin; HIGH enables speaker amp
#define BSP_IO_EXP_LCD_RST  (2)   // expander pin; reset is active low

// ES8311 audio I2S
#define BSP_I2S_MCK         (GPIO_NUM_19)
#define BSP_I2S_BCK         (GPIO_NUM_20)
#define BSP_I2S_DIN         (GPIO_NUM_21)
#define BSP_I2S_WS          (GPIO_NUM_22)
#define BSP_I2S_DOUT        (GPIO_NUM_23)
#define BSP_ES8311_ADDR     (0x18)

// microSD (unused in v0.1)
#define BSP_SD_MOSI         (GPIO_NUM_10)
#define BSP_SD_SCK          (GPIO_NUM_11)
#define BSP_SD_MISO         (GPIO_NUM_18)
#define BSP_SD_CS           (GPIO_NUM_6)
