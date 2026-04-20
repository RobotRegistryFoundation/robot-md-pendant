idf_component_register(
    SRCS "provisioning.c" "app_main_task.c"
    INCLUDE_DIRS "include"
    REQUIRES wifi_mgr ws_client protocol ui app_state es8311_audio json nvs_flash esp_system
)
