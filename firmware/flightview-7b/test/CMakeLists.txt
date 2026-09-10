cmake_minimum_required(VERSION 3.16)

set(EXTRA_COMPONENT_DIRS "../components/flightview_protocol")
set(SDKCONFIG_DEFAULTS "sdkconfig.defaults")
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(flightview_7b_protocol_test)
