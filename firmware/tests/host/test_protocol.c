#include "protocol.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static void test_parse_hello(void) {
    msg_in_t m;
    const char *js =
        "{\"v\":1,\"type\":\"hello\",\"buttons\":[],\"voice_state\":{\"state\":\"idle\"},\"wifi_mode\":\"sta\",\"robot_status\":{\"bus\":\"ok\"}}";
    assert(protocol_parse(js, strlen(js), &m));
    assert(m.type == MSG_HELLO);
    printf("ok  test_parse_hello\n");
}

static void test_parse_rejects_bad_version(void) {
    msg_in_t m;
    const char *js = "{\"v\":2,\"type\":\"heartbeat\",\"seq\":1}";
    assert(!protocol_parse(js, strlen(js), &m));
    printf("ok  test_parse_rejects_bad_version\n");
}

static void test_emit_heartbeat(void) {
    char buf[128];
    int n = protocol_emit_heartbeat(buf, sizeof(buf), 42);
    assert(n > 0);
    assert(strstr(buf, "\"type\":\"heartbeat\"") != NULL);
    assert(strstr(buf, "\"seq\":42") != NULL);
    printf("ok  test_emit_heartbeat\n");
}

static void test_parse_tool_call(void) {
    msg_in_t m;
    const char *js =
        "{\"v\":1,\"type\":\"tool_call\",\"name\":\"execute_capability\","
        "\"args\":{},\"status\":\"ok\",\"summary\":\"home:done\"}";
    assert(protocol_parse(js, strlen(js), &m));
    assert(m.type == MSG_TOOL_CALL);
    assert(!strcmp(m.u.tool_call.name, "execute_capability"));
    assert(!strcmp(m.u.tool_call.status, "ok"));
    printf("ok  test_parse_tool_call\n");
}

static void test_parse_unknown_type_safe(void) {
    msg_in_t m;
    const char *js = "{\"v\":1,\"type\":\"made_up\"}";
    assert(protocol_parse(js, strlen(js), &m));
    assert(m.type == MSG_UNKNOWN);
    printf("ok  test_parse_unknown_type_safe\n");
}

static void test_emit_chat_prompt_escapes_quotes(void) {
    char buf[256];
    int n = protocol_emit_chat_prompt(buf, sizeof(buf), "say \"hi\"");
    assert(n > 0);
    assert(strstr(buf, "\\\"hi\\\"") != NULL);
    printf("ok  test_emit_chat_prompt_escapes_quotes\n");
}

int main(void) {
    test_parse_hello();
    test_parse_rejects_bad_version();
    test_emit_heartbeat();
    test_parse_tool_call();
    test_parse_unknown_type_safe();
    test_emit_chat_prompt_escapes_quotes();
    printf("PASS 6/6\n");
    return 0;
}
