#include "ui.h"
#include "lvgl.h"
#include <stdio.h>
#include <string.h>

static lv_obj_t *s_connecting = NULL, *s_dashboard = NULL, *s_error = NULL;
static lv_obj_t *s_status_lbl = NULL, *s_chat_list = NULL, *s_estopped_banner = NULL;

static void build_connecting(void) {
    s_connecting = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_connecting, lv_color_hex(0x0a0a0a), 0);
    lv_obj_t *spin = lv_spinner_create(s_connecting);
    lv_obj_set_size(spin, 100, 100);
    lv_obj_align(spin, LV_ALIGN_CENTER, 0, -40);
    s_status_lbl = lv_label_create(s_connecting);
    lv_label_set_text(s_status_lbl, "Connecting...");
    lv_obj_set_style_text_color(s_status_lbl, lv_color_hex(0xffffff), 0);
    lv_obj_align(s_status_lbl, LV_ALIGN_CENTER, 0, 40);
}

static void build_dashboard(void) {
    s_dashboard = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_dashboard, lv_color_hex(0x0a0a0a), 0);

    // Status strip
    lv_obj_t *strip = lv_obj_create(s_dashboard);
    lv_obj_set_size(strip, 368, 36);
    lv_obj_align(strip, LV_ALIGN_TOP_MID, 0, 0);
    lv_obj_set_style_bg_color(strip, lv_color_hex(0x1a1a1a), 0);
    lv_obj_set_style_pad_all(strip, 6, 0);
    lv_obj_t *status = lv_label_create(strip);
    lv_label_set_text(status, "\xe2\x97\x8f online");
    lv_obj_set_style_text_color(status, lv_color_hex(0x33ff66), 0);
    lv_obj_align(status, LV_ALIGN_LEFT_MID, 6, 0);

    // Chat list
    s_chat_list = lv_list_create(s_dashboard);
    lv_obj_set_size(s_chat_list, 368, 180);
    lv_obj_align(s_chat_list, LV_ALIGN_TOP_MID, 0, 40);

    // E-stop banner (hidden by default)
    s_estopped_banner = lv_label_create(s_dashboard);
    lv_label_set_text(s_estopped_banner, "  [STOPPED]  ");
    lv_obj_set_style_bg_color(s_estopped_banner, lv_color_hex(0xff0000), 0);
    lv_obj_set_style_bg_opa(s_estopped_banner, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(s_estopped_banner, lv_color_hex(0xffffff), 0);
    lv_obj_align(s_estopped_banner, LV_ALIGN_TOP_MID, 0, 40);
    lv_obj_add_flag(s_estopped_banner, LV_OBJ_FLAG_HIDDEN);

    // Soft-stop button (always visible, bottom-right)
    lv_obj_t *stop_btn = lv_btn_create(s_dashboard);
    lv_obj_set_size(stop_btn, 120, 60);
    lv_obj_align(stop_btn, LV_ALIGN_BOTTOM_RIGHT, -10, -10);
    lv_obj_set_style_bg_color(stop_btn, lv_color_hex(0xcc0000), 0);
    lv_obj_t *stop_lbl = lv_label_create(stop_btn);
    lv_label_set_text(stop_lbl, "STOP");
    lv_obj_set_style_text_color(stop_lbl, lv_color_hex(0xffffff), 0);
    lv_obj_center(stop_lbl);
    // Task 16 wires the event.
}

static void build_error(void) {
    s_error = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(s_error, lv_color_hex(0x330000), 0);
    lv_obj_t *lbl = lv_label_create(s_error);
    lv_label_set_text(lbl, "Pi unreachable");
    lv_obj_set_style_text_color(lbl, lv_color_hex(0xffffff), 0);
    lv_obj_center(lbl);
}

void ui_init(void) {
    build_connecting();
    build_dashboard();
    build_error();
    lv_screen_load(s_connecting);
}

void ui_show_connecting(const char *ssid) {
    if (ssid && s_status_lbl) {
        char buf[80];
        snprintf(buf, sizeof(buf), "Connecting to %s...", ssid);
        lv_label_set_text(s_status_lbl, buf);
    }
    lv_screen_load(s_connecting);
}

void ui_show_dashboard(void) { lv_screen_load(s_dashboard); }
void ui_show_error(const char *msg) { (void)msg; lv_screen_load(s_error); }
void ui_update_status_strip(void) { /* Task 14/22 */ }

void ui_append_chat(const char *role, const char *text) {
    if (!s_chat_list) return;
    char line[320];
    snprintf(line, sizeof(line), "%s: %s", role, text);
    lv_list_add_text(s_chat_list, line);
}

void ui_set_estopped_banner(bool on) {
    if (!s_estopped_banner) return;
    if (on) lv_obj_clear_flag(s_estopped_banner, LV_OBJ_FLAG_HIDDEN);
    else    lv_obj_add_flag(s_estopped_banner, LV_OBJ_FLAG_HIDDEN);
}
