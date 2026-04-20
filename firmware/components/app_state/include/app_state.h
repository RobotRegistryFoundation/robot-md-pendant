#pragma once
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include <stdbool.h>
#include <stdint.h>

#define APP_MAX_BUTTONS 8
#define APP_MAX_CHAT    5
#define APP_LABEL_LEN   32
#define APP_PROMPT_LEN  128
#define APP_CHAT_TEXT_LEN 256

typedef enum {
    CONN_BOOT, CONN_PROVISIONING, CONN_WIFI_CONNECTING,
    CONN_WS_CONNECTING, CONN_ONLINE, CONN_LOST,
} conn_state_t;

typedef struct {
    char label[APP_LABEL_LEN];
    char type[16];                  // "prompt" | "direct_mcp"
    char prompt[APP_PROMPT_LEN];    // only for prompt-type
} app_button_t;

typedef struct {
    conn_state_t conn;
    bool estopped;
    bool speaker_active;            // set while audio_out is playing (for barge-in)
    char wifi_ssid[32];
    char robot_bus[16];             // "ok" | "disconnected" | "servo_latched"
    uint8_t button_count;
    app_button_t buttons[APP_MAX_BUTTONS];
    uint8_t chat_count;
    char chat[APP_MAX_CHAT][APP_CHAT_TEXT_LEN];
    SemaphoreHandle_t mutex;
} app_state_t;

extern app_state_t g_app;

void app_state_init(void);
void app_state_lock(void);
void app_state_unlock(void);
