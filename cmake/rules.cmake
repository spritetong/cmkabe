# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe


cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED _cmkabe_options_initialized)
    set(_cmkabe_options_initialized ON)

    if(NOT DEFINED _cmkabe_toolchain_inited)
        include("${CMAKE_CURRENT_LIST_DIR}/toolchain.cmake")
    endif()

    set(TARGET_OUTPUT_MODE "DEFAULT"
        CACHE STRING "Mode to set the target output directory: `NONE`, `DEFAULT` OR `REDIRECT`.")

    option(TARGET_STRIP_ON_RELEASE
        "Strip the target on release build."
        ON)

    option(TARGET_CC_VISIBILITY_HIDDEN
        "Add option `-fvisibility=hidden` to C/C++ compiler by default."
        ON)

    option(TARGET_WIN32_UNICODE
        "Add definition `_UNICODE` on Windows targets by default."
        ON)
    option(TARGET_MSVC_AFXDLL
        "Add definition `_AFXDLL` to MSVC compiler by default."
        ON)
    option(TARGET_MSVC_UTF8
        "Add option `/utf-8` to MSVC compiler by default."
        ON)
    option(TARGET_MSVC_NO_PDB_WARNING
        "Add option `/ignore:4099` to MSVC linker by default."
        ON)
endif()

if(DEFINED _cmkabe_rules_initialized)
    return()
endif()

# Ensure that CMake will use MASM as the assembler for MSVC projects.
if(${CMAKE_VERSION} VERSION_GREATER_EQUAL "4.1")
    if(CMAKE_ASM_COMPILER)
        cmake_policy(SET CMP0194 NEW)
    else()
        cmake_policy(SET CMP0194 OLD)
    endif()
endif()

if(CMKABE_IS_LOADED_AS_TOOLCHAIN_FILE)
    # Skip if no project is defined.
    if(NOT PROJECT_NAME)
        return()
    endif()
    enable_language(C CXX ASM)
else()
    if(PROJECT_NAME)
        message(fatal_error "Can not define any project before `include <cmkabe>/rules.cmake`.")
    endif()
    project(CMKABE LANGUAGES C CXX ASM)
endif()
set(_cmkabe_rules_initialized ON)

#===============================================================================

include(CheckCCompilerFlag)

if(CMAKE_C_COMPILER_ID MATCHES "(Clang|GNU)")
    check_c_compiler_flag("-s" CC_HAVE_OPTION_STRIP)
else()
    set(CC_HAVE_OPTION_STRIP OFF)
endif()

if(ZIG AND (CMAKE_IMPORT_LIBRARY_SUFFIX STREQUAL ".dll.a"))
    # Change the DLL file name from `lib<name>.dll` to `<name>.dll`
    set(CMAKE_SHARED_LIBRARY_PREFIX "")
    set(CMAKE_SHARED_LIBRARY_SUFFIX ".dll")
    set(CMAKE_IMPORT_LIBRARY_PREFIX "lib")
    set(CMAKE_IMPORT_LIBRARY_SUFFIX ".dll.a")
endif()

# Redirect the output directories to the target directories.
if(TARGET_OUTPUT_MODE MATCHES "^[Dd][Ee][Ff][Aa][Uu][Ll][Tt]$")
    set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}$<LOWER_CASE:>")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}$<LOWER_CASE:>")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}$<LOWER_CASE:>")
endif()

# Define `_DEBUG` for Debug build.
add_compile_definitions($<$<AND:$<COMPILE_LANGUAGE:C,CXX>,$<CONFIG:Debug>>:_DEBUG>)

if(TARGET_STRIP_ON_RELEASE AND CC_HAVE_OPTION_STRIP)
    add_compile_options($<$<AND:$<COMPILE_LANGUAGE:C,CXX>,$<CONFIG:Release>>:-s>)
    add_link_options($<$<CONFIG:Release>:-s>)
    add_compile_options($<$<AND:$<COMPILE_LANGUAGE:C,CXX>,$<CONFIG:MinSizeRel>>:-s>)
    add_link_options($<$<CONFIG:MinSizeRel>:-s>)
endif()

if(TARGET_CC_VISIBILITY_HIDDEN)
    set(CMAKE_C_VISIBILITY_PRESET "hidden")
    set(CMAKE_CXX_VISIBILITY_PRESET "hidden")
    set(CMAKE_ASM_VISIBILITY_PRESET "hidden")
endif()

if(TARGET_WIN32_UNICODE AND (MSVC OR TARGET_IS_WIN32))
    add_compile_definitions($<$<COMPILE_LANGUAGE:C,CXX>:UNICODE> $<$<COMPILE_LANGUAGE:C,CXX>:_UNICODE>)
endif()

if(TARGET_MSVC_AFXDLL AND (MSVC OR TARGET_IS_MSVC))
    add_compile_definitions($<$<COMPILE_LANGUAGE:C,CXX>:_AFXDLL>)
endif()

if(TARGET_MSVC_UTF8 AND (MSVC OR TARGET_IS_MSVC))
    add_compile_options($<$<COMPILE_LANGUAGE:C,CXX>:/utf-8>)
endif()

if(TARGET_MSVC_NO_PDB_WARNING AND (MSVC OR TARGET_IS_MSVC))
    add_link_options(/ignore:4099)
endif()

_cmkabe_apply_extra_flags()
