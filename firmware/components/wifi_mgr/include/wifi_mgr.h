#pragma once
#include "esp_err.h"
#include <stdbool.h>
#include <stddef.h>

esp_err_t wifi_mgr_init(void);

// ESP_ERR_NVS_NOT_FOUND if NVS is empty (caller enters provisioning).
esp_err_t wifi_mgr_load_creds(char *ssid_out, size_t ssid_cap,
                              char *psk_out,  size_t psk_cap);

esp_err_t wifi_mgr_save_creds(const char *ssid, const char *psk);

// Blocks until first STA association or permanent failure.
esp_err_t wifi_mgr_start(const char *ssid, const char *psk);

bool wifi_mgr_is_connected(void);
