#include "display_lvgl.h"
#include "board_pins.h"
#include "board_hw.h"
#include "driver/spi_master.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_sh8601.h"
#include "esp_lcd_touch_ft5x06.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "lvgl.h"

static const char *TAG = "display_lvgl";
static lv_display_t *s_disp = NULL;
static esp_lcd_panel_handle_t s_panel = NULL;
static esp_lcd_touch_handle_t s_touch = NULL;
static lv_obj_t *s_touch_dot = NULL;

static void touch_read_cb(lv_indev_t *indev, lv_indev_data_t *data) {
    uint16_t x[1], y[1], strength[1];
    uint8_t count = 0;
    esp_lcd_touch_read_data(s_touch);
    bool pressed = esp_lcd_touch_get_coordinates(s_touch, x, y, strength, &count, 1);
    if (pressed && count > 0) {
        data->state = LV_INDEV_STATE_PRESSED;
        data->point.x = x[0];
        data->point.y = y[0];
        if (s_touch_dot) {
            lv_obj_clear_flag(s_touch_dot, LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_pos(s_touch_dot, x[0] - 20, y[0] - 20);
        }
    } else {
        data->state = LV_INDEV_STATE_RELEASED;
    }
}

static esp_err_t touch_init(void) {
    esp_lcd_panel_io_handle_t tio = NULL;
    esp_lcd_panel_io_i2c_config_t tio_cfg = ESP_LCD_TOUCH_IO_I2C_FT5x06_CONFIG();
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_i2c_v2(board_hw_i2c_bus(), &tio_cfg, &tio));

    const esp_lcd_touch_config_t tcfg = {
        .x_max = 368, .y_max = 488,
        .rst_gpio_num = -1,
        .int_gpio_num = BSP_TOUCH_INT,
        .levels = { .reset = 0, .interrupt = 0 },
        .flags = { .swap_xy = 0, .mirror_x = 0, .mirror_y = 0 },
    };
    return esp_lcd_touch_new_i2c_ft5x06(tio, &tcfg, &s_touch);
}

// SH8601 QSPI init command sequence (from Waveshare demo).
static const sh8601_lcd_init_cmd_t sh8601_init_cmds[] = {
    {0x11, (uint8_t[]){0x00}, 0, 120},
    {0xC4, (uint8_t[]){0x80}, 1, 0},
    {0x44, (uint8_t[]){0x01, 0xD1}, 2, 0},
    {0x35, (uint8_t[]){0x00}, 1, 0},
    {0x53, (uint8_t[]){0x20}, 1, 10},
    {0x63, (uint8_t[]){0xFF}, 1, 0},
    {0x29, (uint8_t[]){0x00}, 0, 10},
    {0x51, (uint8_t[]){0xFF}, 1, 0},
};

static void flush_cb(lv_display_t *disp, const lv_area_t *area, uint8_t *px) {
    int x1 = area->x1, y1 = area->y1, x2 = area->x2 + 1, y2 = area->y2 + 1;
    esp_lcd_panel_draw_bitmap(s_panel, x1, y1, x2, y2, px);
    lv_display_flush_ready(disp);
}

esp_err_t display_lvgl_init(void) {
    spi_bus_config_t bus = SH8601_PANEL_BUS_QSPI_CONFIG(
        BSP_LCD_PCLK,
        BSP_LCD_DATA0, BSP_LCD_DATA1, BSP_LCD_DATA2, BSP_LCD_DATA3,
        368 * 80 * sizeof(uint16_t));
    ESP_ERROR_CHECK(spi_bus_initialize(BSP_LCD_HOST, &bus, SPI_DMA_CH_AUTO));

    esp_lcd_panel_io_spi_config_t io_cfg = SH8601_PANEL_IO_QSPI_CONFIG(BSP_LCD_CS, NULL, NULL);
    esp_lcd_panel_io_handle_t io = NULL;
    ESP_ERROR_CHECK(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)BSP_LCD_HOST, &io_cfg, &io));

    sh8601_vendor_config_t vcfg = {
        .init_cmds = sh8601_init_cmds,
        .init_cmds_size = sizeof(sh8601_init_cmds) / sizeof(sh8601_init_cmds[0]),
        .flags = {.use_qspi_interface = 1},
    };
    esp_lcd_panel_dev_config_t panel_cfg = {
        .reset_gpio_num = -1,   // reset is via TCA9554, handled in board_hw
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
        .vendor_config = &vcfg,
    };
    ESP_ERROR_CHECK(esp_lcd_new_panel_sh8601(io, &panel_cfg, &s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_init(s_panel));
    ESP_ERROR_CHECK(esp_lcd_panel_disp_on_off(s_panel, true));

    // LVGL
    lv_init();
    s_disp = lv_display_create(368, 488);
    // Two 30KB-ish tile buffers (partial render)
    static uint8_t buf1[368 * 40 * 2] __attribute__((aligned(4)));
    static uint8_t buf2[368 * 40 * 2] __attribute__((aligned(4)));
    lv_display_set_buffers(s_disp, buf1, buf2, sizeof(buf1), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(s_disp, flush_cb);

    lv_obj_t *scr = lv_display_get_screen_active(s_disp);
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x0a0a0a), 0);

    lv_obj_t *title = lv_label_create(scr);
    lv_label_set_text(title, "robot-md-pendant");
    lv_obj_set_style_text_color(title, lv_color_hex(0xffffff), 0);
    lv_obj_align(title, LV_ALIGN_TOP_MID, 0, 20);

    lv_obj_t *btn = lv_btn_create(scr);
    lv_obj_set_size(btn, 200, 60);
    lv_obj_align(btn, LV_ALIGN_CENTER, 0, 0);
    lv_obj_t *btn_lbl = lv_label_create(btn);
    lv_label_set_text(btn_lbl, "tap me");
    lv_obj_center(btn_lbl);

    // Touch indicator dot (so we can see taps)
    lv_obj_t *dot = lv_obj_create(scr);
    lv_obj_set_size(dot, 40, 40);
    lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(dot, lv_color_hex(0xff3333), 0);
    lv_obj_add_flag(dot, LV_OBJ_FLAG_HIDDEN);
    s_touch_dot = dot;

    ESP_ERROR_CHECK(touch_init());
    lv_indev_t *indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, touch_read_cb);
    lv_indev_set_display(indev, s_disp);

    ESP_LOGI(TAG, "display init ok (368x488)");
    return ESP_OK;
}

lv_display_t *display_lvgl_get_display(void) { return s_disp; }
