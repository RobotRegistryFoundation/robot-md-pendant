#include "protocol.h"
#include <string.h>
#include <stdio.h>
#include "cJSON.h"

static msg_type_t type_from_string(const char *s) {
    if (!s) return MSG_UNKNOWN;
    if (!strcmp(s, "hello")) return MSG_HELLO;
    if (!strcmp(s, "heartbeat")) return MSG_HEARTBEAT;
    return MSG_UNKNOWN;
}

bool protocol_parse(const char *json, size_t len, msg_in_t *out) {
    (void)len;
    memset(out, 0, sizeof(*out));
    cJSON *root = cJSON_Parse(json);
    if (!root) return false;
    cJSON *v = cJSON_GetObjectItem(root, "v");
    cJSON *t = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsNumber(v) || v->valueint != 1 || !cJSON_IsString(t)) {
        cJSON_Delete(root);
        return false;
    }
    out->type = type_from_string(t->valuestring);
    cJSON_Delete(root);
    return true;
}

int protocol_emit_heartbeat(char *buf, size_t cap, uint32_t seq) {
    int n = snprintf(buf, cap, "{\"v\":1,\"type\":\"heartbeat\",\"seq\":%u}", (unsigned)seq);
    return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

int protocol_emit_button_press(char *buf, size_t cap, const char *id) {
    int n = snprintf(buf, cap, "{\"v\":1,\"type\":\"button_press\",\"id\":\"%s\"}", id);
    return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

int protocol_emit_chat_prompt(char *buf, size_t cap, const char *text) {
    // Does NOT JSON-escape `text`. Proper escaping added in Task 8.
    int n = snprintf(buf, cap, "{\"v\":1,\"type\":\"chat_prompt\",\"text\":\"%s\"}", text);
    return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

int protocol_emit_soft_stop(char *buf, size_t cap) {
    int n = snprintf(buf, cap, "{\"v\":1,\"type\":\"soft_stop\"}");
    return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

int protocol_emit_voice_state(char *buf, size_t cap, const char *state) {
    int n = snprintf(buf, cap, "{\"v\":1,\"type\":\"voice_state\",\"state\":\"%s\"}", state);
    return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

int protocol_emit_barge_in(char *buf, size_t cap) {
    int n = snprintf(buf, cap, "{\"v\":1,\"type\":\"barge_in\"}");
    return (n < 0 || (size_t)n >= cap) ? -1 : n;
}
