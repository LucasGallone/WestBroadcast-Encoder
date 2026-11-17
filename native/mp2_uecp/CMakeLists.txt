# mp2_uecp.exe - MP2 encoder with UECP (RDS) ancillary data, used by stream_manager.py when
# RDS (UECP) embedding is enabled on an MP2 stream. See main.cpp for the stdin/stdout protocol.
#
# Sources:
#   libtoolame-dab/  copied from UecpSource (itself a modified ODR-AudioEnc libtoolame-dab,
#                    LGPL 2.1+; changes listed in libtoolame-dab/MODIFICATIONS.md)
#   mp2_encoder.*    copied unchanged from UecpSource src/common
#
# Build (with VS Build Tools' cmake.exe, or from a VS developer prompt):
#   cmake -S . -B build -A x64
#   cmake --build build --config Release
# The executable is written next to app.py as mp2_uecp_x64.exe (mp2_uecp_x86.exe for -A Win32).

cmake_minimum_required(VERSION 3.20)
project(mp2_uecp LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)

# Static CRT so the executable needs no VC++ redistributable.
if(MSVC)
    set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
endif()

add_subdirectory(libtoolame-dab)

add_executable(mp2_uecp
    main.cpp
    mp2_encoder.h
    mp2_encoder.cpp
)
target_link_libraries(mp2_uecp PRIVATE toolame)

if(MSVC)
    target_compile_options(mp2_uecp PRIVATE /W4 /wd4996)
else()
    target_compile_options(mp2_uecp PRIVATE -Wall -Wextra)
    target_link_libraries(mp2_uecp PRIVATE m)
endif()

if(CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(MP2_UECP_NAME mp2_uecp_x64)
else()
    set(MP2_UECP_NAME mp2_uecp_x86)
endif()

set_target_properties(mp2_uecp PROPERTIES
    OUTPUT_NAME ${MP2_UECP_NAME}
    RUNTIME_OUTPUT_DIRECTORY_RELEASE ${CMAKE_CURRENT_SOURCE_DIR}/../..
    RUNTIME_OUTPUT_DIRECTORY_RELWITHDEBINFO ${CMAKE_CURRENT_SOURCE_DIR}/../..
)
