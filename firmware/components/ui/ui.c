#include "ui.h"
#include "lvgl.h"
#include <stdio.h>
#include <string.h>
#include "app_state.h"
#include <stdint.h>

static lv_obj_t *s_connecting = NULL, *s_dashboard = NULL, *s_error = NULL;
static lv_obj_t *s_status_lbl = NULL, *s_chat_list = NULL, *s_estopped_banner = NULL;

static ui_soft_stop_cb_t s_stop_cb = NULL;
void ui_set_soft_stop_cb(ui_soft_stop_cb_t cb) { s_stop_cb = cb; }

static void stop_ev(lv_event_t *e) { (void)e; if (s_stop_cb) s_stop_cb(); }

static ui_chat_submit_cb_t s_chat_cb = NULL;
static lv_obj_t *s_chat_ta = NULL, *s_kb = NULL;

void ui_set_chat_submit_cb(ui_chat_submit_cb_t cb) { s_chat_cb = cb; }

static void kb_ev(lv_event_t *e) {
    lv_event_code_t code = lv_event_get_code(e);
    if (code == LV_EVENT_READY) {
        const char *t = lv_textarea_get_text(s_chat_ta);
        if (s_chat_cb && t && *t) s_chat_cb(t);
        lv_textarea_set_text(s_chat_ta, "");
    }
}

static void ta_focus_ev(lv_event_t *e) {
    lv_event_code_t c = lv_event_get_code(e);
    if (c == LV_EVENT_FOCUSED) lv_obj_clear_flag(s_kb, LV_OBJ_FLAG_HIDDEN);
    else if (c == LV_EVENT_DEFOCUSED) lv_obj_add_flag(s_kb, LV_OBJ_FLAG_HIDDEN);
}

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
    lv_obj_add_event_cb(stop_btn, stop_ev, LV_EVENT_CLICKED, NULL);

    s_chat_ta = lv_textarea_create(s_dashboard);
    lv_obj_set_size(s_chat_ta, 368, 36);
    lv_obj_align(s_chat_ta, LV_ALIGN_BOTTOM_MID, 0, -80);
    lv_textarea_set_one_line(s_chat_ta, true);
    lv_textarea_set_placeholder_text(s_chat_ta, "ask Claude...");

    s_kb = lv_keyboard_create(s_dashboard);
    lv_obj_set_size(s_kb, 368, 180);
    lv_obj_align(s_kb, LV_ALIGN_BOTTOM_MID, 0, 0);
    lv_keyboard_set_textarea(s_kb, s_chat_ta);
    lv_obj_add_event_cb(s_kb, kb_ev, LV_EVENT_READY, NULL);
    lv_obj_add_flag(s_kb, LV_OBJ_FLAG_HIDDEN);

    lv_obj_add_event_cb(s_chat_ta, ta_focus_ev, LV_EVENT_FOCUSED, NULL);
    lv_obj_add_event_cb(s_chat_ta, ta_focus_ev, LV_EVENT_DEFOCUSED, NULL);
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

static ui_button_pressed_cb_t s_btn_cb = NULL;
static lv_obj_t *s_btn_grid = NULL;

void ui_set_button_pressed_cb(ui_button_pressed_cb_t cb) { s_btn_cb = cb; }

static void btn_ev(lv_event_t *e) {
    uintptr_t idx = (uintptr_t)lv_event_get_user_data(e);
    if (s_btn_cb) s_btn_cb((uint8_t)idx);
}

void ui_rebuild_button_grid(void) {
    if (!s_dashboard) return;
    if (s_btn_grid) { lv_obj_del(s_btn_grid); s_btn_grid = NULL; }
    s_btn_grid = lv_obj_create(s_dashboard);
    lv_obj_set_size(s_btn_grid, 240, 240);
    lv_obj_align(s_btn_grid, LV_ALIGN_BOTTOM_LEFT, 10, -10);
    lv_obj_set_flex_flow(s_btn_grid, LV_FLEX_FLOW_ROW_WRAP);
    lv_obj_set_style_pad_all(s_btn_grid, 6, 0);

    app_state_lock();
    for (uint8_t i = 0; i < g_app.button_count; i++) {
        lv_obj_t *b = lv_btn_create(s_btn_grid);
        lv_obj_set_size(b, 110, 60);
        lv_obj_add_event_cb(b, btn_ev, LV_EVENT_CLICKED, (void*)(uintptr_t)i);
        lv_obj_t *lbl = lv_label_create(b);
        lv_label_set_text(lbl, g_app.buttons[i].label);
        lv_obj_center(lbl);
    }
    app_state_unlock();
}
