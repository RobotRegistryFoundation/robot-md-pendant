#pragma once
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>

typedef enum {
    MSG_UNKNOWN = 0,
    MSG_HELLO,
    MSG_HEARTBEAT,
    MSG_BUTTON_PRESS,
    MSG_CHAT_PROMPT,
    MSG_CHAT_MESSAGE,
    MSG_TOOL_CALL,
    MSG_STATUS,
    MSG_SOFT_STOP,
    MSG_THUMBNAIL,
    MSG_VOICE_STATE,
    MSG_WAKE_ENABLED,
    MSG_BARGE_IN,
    MSG_VOICE_ERROR,
    MSG_ERROR,
} msg_type_t;

typedef struct {
    msg_type_t type;
    union {
        struct { int wifi_mode_is_ap; } hello;
        struct { char text[512]; char role[32]; } chat_message;
        struct { char name[64]; char status[16]; char summary[256]; } tool_call;
        struct { int estopped; } status;
        struct { char state[16]; } voice_state;
        struct { int enabled; } wake_enabled;
        struct { char stage[16]; char message[128]; } voice_error;
        struct { char code[32]; char message[128]; } error;
    } u;
} msg_in_t;

// Parse a JSON text frame. Returns true on success; out->type set to
// MSG_UNKNOWN if unsupported type.
bool protocol_parse(const char *json, size_t len, msg_in_t *out);

// Emit helpers. Return bytes written, or -1 on buffer-too-small.
int protocol_emit_heartbeat(char *buf, size_t cap, uint32_t seq);
int protocol_emit_button_press(char *buf, size_t cap, const char *id);
int protocol_emit_chat_prompt(char *buf, size_t cap, const char *text);
int protocol_emit_soft_stop(char *buf, size_t cap);
int protocol_emit_voice_state(char *buf, size_t cap, const char *state);
int protocol_emit_barge_in(char *buf, size_t cap);
