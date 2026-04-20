#pragma once
#include "esp_err.h"

// Blocking. Prints prompts over stdin/stdout (UART), reads SSID/PSK/Pi URL,
// saves to NVS (wifi:ssid, wifi:psk, server:url), reboots.
esp_err_t provisioning_run(void);
