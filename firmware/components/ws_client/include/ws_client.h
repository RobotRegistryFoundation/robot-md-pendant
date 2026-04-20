#pragma once
#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Callbacks — MUST NOT block.
typedef void (*ws_text_cb_t)(const char *data, size_t len);
typedef void (*ws_bin_cb_t)(const uint8_t *data, size_t len);

esp_err_t ws_client_init(const char *url, ws_text_cb_t on_text, ws_bin_cb_t on_bin);
esp_err_t ws_client_start(void);
esp_err_t ws_client_stop(void);
bool      ws_client_is_connected(void);
esp_err_t ws_client_send_text(const char *data, size_t len);
esp_err_t ws_client_send_bin(const uint8_t *data, size_t len);
