#include "app_task.h"
#include "app_state.h"
#include "ws_client.h"
#include "protocol.h"
#include "ui.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/task.h"
#include "cJSON.h"
#include <string.h>
#include <stdio.h>

static const char *TAG = "app_task";
static QueueHandle_t s_inbox = NULL;

typedef struct { char json[512]; size_t len; } inbox_item_t;

static void on_text(const char *data, size_t len) {
    if (!s_inbox) return;
    inbox_item_t item = {0};
    size_t n = len < sizeof(item.json) - 1 ? len : sizeof(item.json) - 1;
    memcpy(item.json, data, n);
    item.len = n;
    if (xQueueSend(s_inbox, &item, 0) != pdTRUE) {
        inbox_item_t trash; xQueueReceive(s_inbox, &trash, 0);
        xQueueSend(s_inbox, &item, 0);
    }
}

static void on_bin(const uint8_t *data, size_t len) { (void)data; (void)len; /* Task 20 */ }

static void apply_hello(const char *json) {
    cJSON *root = cJSON_Parse(json);
    if (!root) return;
    cJSON *wm = cJSON_GetObjectItem(root, "wifi_mode");
    cJSON *rs = cJSON_GetObjectItem(root, "robot_status");
    cJSON *bs = cJSON_GetObjectItem(root, "buttons");

    app_state_lock();
    if (cJSON_IsString(wm)) strncpy(g_app.wifi_ssid, wm->valuestring, sizeof(g_app.wifi_ssid) - 1);
    if (cJSON_IsObject(rs)) {
        cJSON *b = cJSON_GetObjectItem(rs, "bus");
        if (cJSON_IsString(b)) strncpy(g_app.robot_bus, b->valuestring, sizeof(g_app.robot_bus) - 1);
    }
    g_app.button_count = 0;
    if (cJSON_IsArray(bs)) {
        int cnt = cJSON_GetArraySize(bs);
        for (int i = 0; i < cnt && g_app.button_count < APP_MAX_BUTTONS; i++) {
            cJSON *b = cJSON_GetArrayItem(bs, i);
            cJSON *lbl = cJSON_GetObjectItem(b, "label");
            cJSON *tp = cJSON_GetObjectItem(b, "type");
            cJSON *pr = cJSON_GetObjectItem(b, "prompt");
            if (cJSON_IsString(lbl)) strncpy(g_app.buttons[i].label, lbl->valuestring, APP_LABEL_LEN - 1);
            if (cJSON_IsString(tp))  strncpy(g_app.buttons[i].type,  tp->valuestring,  sizeof(g_app.buttons[i].type) - 1);
            if (cJSON_IsString(pr))  strncpy(g_app.buttons[i].prompt, pr->valuestring, APP_PROMPT_LEN - 1);
            g_app.button_count++;
        }
    }
    g_app.conn = CONN_ONLINE;
    app_state_unlock();
    cJSON_Delete(root);
}

static void app_loop(void *arg) {
    inbox_item_t item;
    while (1) {
        if (xQueueReceive(s_inbox, &item, pdMS_TO_TICKS(100)) == pdTRUE) {
            msg_in_t m;
            if (!protocol_parse(item.json, item.len, &m)) continue;
            switch (m.type) {
            case MSG_HELLO:
                apply_hello(item.json);
                ui_show_dashboard();
                ui_rebuild_button_grid();
                break;
            case MSG_CHAT_MESSAGE:
                ui_append_chat(m.u.chat_message.role, m.u.chat_message.text);
                break;
            case MSG_TOOL_CALL: {
                char line[320];
                snprintf(line, sizeof(line), "\xe2\x86\x92 %s (%s)", m.u.tool_call.name, m.u.tool_call.status);
                ui_append_chat("tool", line);
                break;
            }
            case MSG_STATUS:
                ui_set_estopped_banner(m.u.status.estopped);
                break;
            default: break;
            }
        }
    }
}

static void on_button_press(uint8_t index) {
    char buf[80]; char id[8]; snprintf(id, sizeof(id), "%u", index);
    int n = protocol_emit_button_press(buf, sizeof(buf), id);
    if (n > 0) ws_client_send_text(buf, n);
}

static void on_chat_submit(const char *text) {
    char buf[APP_PROMPT_LEN + 64];
    int n = protocol_emit_chat_prompt(buf, sizeof(buf), text);
    if (n > 0) ws_client_send_text(buf, n);
    ui_append_chat("you", text);
}

static void on_soft_stop(void) {
    // Paint banner immediately — don't wait for Pi confirmation.
    ui_set_estopped_banner(true);
    char buf[64];
    int n = protocol_emit_soft_stop(buf, sizeof(buf));
    if (n > 0) ws_client_send_text(buf, n);
}

esp_err_t app_task_start(const char *ws_url) {
    s_inbox = xQueueCreate(32, sizeof(inbox_item_t));
    ESP_ERROR_CHECK(ws_client_init(ws_url, on_text, on_bin));
    ui_set_soft_stop_cb(on_soft_stop);
    ui_set_button_pressed_cb(on_button_press);
    ui_set_chat_submit_cb(on_chat_submit);
    ESP_ERROR_CHECK(ws_client_start());
    xTaskCreate(app_loop, "app_loop", 6144, NULL, 5, NULL);
    return ESP_OK;
}
