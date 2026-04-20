#include "protocol.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "cJSON.h"

static msg_type_t type_from_string(const char *s) {
    if (!s) return MSG_UNKNOWN;
    if (!strcmp(s, "hello")) return MSG_HELLO;
    if (!strcmp(s, "heartbeat")) return MSG_HEARTBEAT;
    if (!strcmp(s, "button_press")) return MSG_BUTTON_PRESS;
    if (!strcmp(s, "chat_prompt"))  return MSG_CHAT_PROMPT;
    if (!strcmp(s, "chat_message")) return MSG_CHAT_MESSAGE;
    if (!strcmp(s, "tool_call"))    return MSG_TOOL_CALL;
    if (!strcmp(s, "status"))       return MSG_STATUS;
    if (!strcmp(s, "soft_stop"))    return MSG_SOFT_STOP;
    if (!strcmp(s, "thumbnail"))    return MSG_THUMBNAIL;
    if (!strcmp(s, "voice_state"))  return MSG_VOICE_STATE;
    if (!strcmp(s, "wake_enabled")) return MSG_WAKE_ENABLED;
    if (!strcmp(s, "barge_in"))     return MSG_BARGE_IN;
    if (!strcmp(s, "voice_error"))  return MSG_VOICE_ERROR;
    if (!strcmp(s, "error"))        return MSG_ERROR;
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
    switch (out->type) {
    case MSG_CHAT_MESSAGE: {
        cJSON *txt = cJSON_GetObjectItem(root, "text");
        cJSON *role = cJSON_GetObjectItem(root, "role");
        if (cJSON_IsString(txt))  strncpy(out->u.chat_message.text, txt->valuestring, sizeof(out->u.chat_message.text) - 1);
        if (cJSON_IsString(role)) strncpy(out->u.chat_message.role, role->valuestring, sizeof(out->u.chat_message.role) - 1);
        break;
    }
    case MSG_TOOL_CALL: {
        cJSON *name = cJSON_GetObjectItem(root, "name");
        cJSON *status = cJSON_GetObjectItem(root, "status");
        cJSON *summary = cJSON_GetObjectItem(root, "summary");
        if (cJSON_IsString(name))    strncpy(out->u.tool_call.name, name->valuestring, sizeof(out->u.tool_call.name) - 1);
        if (cJSON_IsString(status))  strncpy(out->u.tool_call.status, status->valuestring, sizeof(out->u.tool_call.status) - 1);
        if (cJSON_IsString(summary)) strncpy(out->u.tool_call.summary, summary->valuestring, sizeof(out->u.tool_call.summary) - 1);
        break;
    }
    case MSG_STATUS: {
        cJSON *es = cJSON_GetObjectItem(root, "estopped");
        out->u.status.estopped = cJSON_IsTrue(es);
        break;
    }
    case MSG_VOICE_STATE: {
        cJSON *s = cJSON_GetObjectItem(root, "state");
        if (cJSON_IsString(s)) strncpy(out->u.voice_state.state, s->valuestring, sizeof(out->u.voice_state.state) - 1);
        break;
    }
    case MSG_WAKE_ENABLED: {
        cJSON *e = cJSON_GetObjectItem(root, "enabled");
        out->u.wake_enabled.enabled = cJSON_IsTrue(e);
        break;
    }
    case MSG_VOICE_ERROR: {
        cJSON *st = cJSON_GetObjectItem(root, "stage");
        cJSON *m = cJSON_GetObjectItem(root, "message");
        if (cJSON_IsString(st)) strncpy(out->u.voice_error.stage, st->valuestring, sizeof(out->u.voice_error.stage) - 1);
        if (cJSON_IsString(m))  strncpy(out->u.voice_error.message, m->valuestring, sizeof(out->u.voice_error.message) - 1);
        break;
    }
    case MSG_ERROR: {
        cJSON *c = cJSON_GetObjectItem(root, "code");
        cJSON *m = cJSON_GetObjectItem(root, "message");
        if (cJSON_IsString(c)) strncpy(out->u.error.code, c->valuestring, sizeof(out->u.error.code) - 1);
        if (cJSON_IsString(m)) strncpy(out->u.error.message, m->valuestring, sizeof(out->u.error.message) - 1);
        break;
    }
    default: break;
    }
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
    cJSON *obj = cJSON_CreateObject();
    cJSON_AddNumberToObject(obj, "v", 1);
    cJSON_AddStringToObject(obj, "type", "chat_prompt");
    cJSON_AddStringToObject(obj, "text", text);
    char *s = cJSON_PrintUnformatted(obj);
    int n = -1;
    if (s && strlen(s) < cap) { strcpy(buf, s); n = (int)strlen(s); }
    free(s);
    cJSON_Delete(obj);
    return n;
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
