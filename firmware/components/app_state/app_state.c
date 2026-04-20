#include "app_state.h"
#include <string.h>

app_state_t g_app;

void app_state_init(void) {
    memset(&g_app, 0, sizeof(g_app));
    g_app.conn = CONN_BOOT;
    g_app.mutex = xSemaphoreCreateMutex();
}

void app_state_lock(void)   { xSemaphoreTake(g_app.mutex, portMAX_DELAY); }
void app_state_unlock(void) { xSemaphoreGive(g_app.mutex); }
