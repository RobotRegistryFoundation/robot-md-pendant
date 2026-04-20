#include "es8311_audio.h"
#include "board_pins.h"
#include "board_hw.h"
#include "es8311.h"
#include "driver/i2s_std.h"
#include "esp_log.h"
#include "esp_err.h"
#include "esp_check.h"

static const char *TAG = "audio";
static i2s_chan_handle_t s_tx = NULL, s_rx = NULL;

esp_err_t audio_init(void)
{
    // Codec: uses the shared I2C master bus already owned by board_hw.
    es8311_handle_t es = es8311_create(board_hw_i2c_bus(), BSP_ES8311_ADDR);
    ESP_RETURN_ON_FALSE(es, ESP_FAIL, TAG, "es8311_create");

    es8311_clock_config_t clk = {
        .mclk_inverted      = false,
        .sclk_inverted      = false,
        .mclk_from_mclk_pin = true,
        .mclk_frequency     = 16000 * 256,
        .sample_frequency   = 16000,
    };
    ESP_RETURN_ON_ERROR(es8311_init(es, &clk, ES8311_RESOLUTION_16, ES8311_RESOLUTION_16),
                        TAG, "es init");
    ESP_RETURN_ON_ERROR(es8311_sample_frequency_config(es, clk.mclk_frequency, clk.sample_frequency),
                        TAG, "sf");
    ESP_RETURN_ON_ERROR(es8311_microphone_config(es, false),   TAG, "mic cfg");
    ESP_RETURN_ON_ERROR(es8311_voice_volume_set(es, 85, NULL), TAG, "vol");
    ESP_RETURN_ON_ERROR(es8311_microphone_gain_set(es, ES8311_MIC_GAIN_18DB), TAG, "gain");

    // I2S master full-duplex, 16kHz mono s16le
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    ESP_ERROR_CHECK(i2s_new_channel(&cc, &s_tx, &s_rx));

    i2s_std_config_t std = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(16000),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = BSP_I2S_MCK,
            .bclk = BSP_I2S_BCK,
            .ws   = BSP_I2S_WS,
            .dout = BSP_I2S_DOUT,
            .din  = BSP_I2S_DIN,
        },
    };
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_tx, &std));
    ESP_ERROR_CHECK(i2s_channel_init_std_mode(s_rx, &std));
    ESP_ERROR_CHECK(i2s_channel_enable(s_tx));
    ESP_ERROR_CHECK(i2s_channel_enable(s_rx));
    ESP_LOGI(TAG, "audio init ok (16kHz mono)");
    return ESP_OK;
}

esp_err_t audio_start_record(audio_rx_cb_t cb) { (void)cb; return ESP_ERR_NOT_SUPPORTED; }
esp_err_t audio_stop_record(void)              { return ESP_OK; }
esp_err_t audio_play_chunk(const uint8_t *p, size_t n) { (void)p; (void)n; return ESP_ERR_NOT_SUPPORTED; }
esp_err_t audio_stop_playback(void)            { return ESP_OK; }
