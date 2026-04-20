#pragma once
#include "app_state.h"
#include <stdbool.h>

void ui_init(void);
void ui_show_connecting(const char *ssid);
void ui_show_dashboard(void);
void ui_show_error(const char *msg);
void ui_update_status_strip(void);     // called after app_state changes
void ui_append_chat(const char *role, const char *text);
void ui_set_estopped_banner(bool on);
#include <stdint.h>
typedef void (*ui_button_pressed_cb_t)(uint8_t index);
void ui_set_button_pressed_cb(ui_button_pressed_cb_t cb);
void ui_rebuild_button_grid(void);   // reads g_app.buttons[]
typedef void (*ui_soft_stop_cb_t)(void);
void ui_set_soft_stop_cb(ui_soft_stop_cb_t cb);
