#pragma once
#include "esp_err.h"
#include <stddef.h>
#include <stdint.h>

typedef void (*audio_rx_cb_t)(const uint8_t *pcm, size_t n);

esp_err_t audio_init(void);
esp_err_t audio_start_record(audio_rx_cb_t cb);
esp_err_t audio_stop_record(void);
esp_err_t audio_play_chunk(const uint8_t *pcm, size_t n);
esp_err_t audio_stop_playback(void);
