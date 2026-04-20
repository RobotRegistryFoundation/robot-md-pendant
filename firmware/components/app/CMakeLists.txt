idf_component_register(
    SRCS "provisioning.c"
    INCLUDE_DIRS "include"
    REQUIRES wifi_mgr nvs_flash esp_system
)
