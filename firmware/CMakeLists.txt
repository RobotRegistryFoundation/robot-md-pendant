cmake_minimum_required(VERSION 3.16)
# Pick up vendored components (e.g. esp_lcd_sh8601) from components/vendored/
list(APPEND EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/components/vendored")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(robot_md_pendant_firmware)
