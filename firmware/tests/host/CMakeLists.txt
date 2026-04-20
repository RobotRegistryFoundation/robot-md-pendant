cmake_minimum_required(VERSION 3.16)
project(firmware_host_tests C)

set(CMAKE_C_STANDARD 11)
enable_testing()

find_library(CJSON_LIB cjson REQUIRED)
find_path(CJSON_INC cJSON.h PATHS /usr/include/cjson /usr/local/include/cjson REQUIRED)

add_executable(test_protocol
    test_protocol.c
    ../../components/protocol/protocol.c
)
target_include_directories(test_protocol PRIVATE
    ../../components/protocol/include
    ${CJSON_INC}
)
target_link_libraries(test_protocol PRIVATE ${CJSON_LIB})
add_test(NAME test_protocol COMMAND test_protocol)
