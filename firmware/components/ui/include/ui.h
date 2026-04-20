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
