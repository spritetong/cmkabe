# * @file       rules.cmake
# * @brief      This file contains common rules to build cmake targets.
# * @details    Copyright (C) 2022 spritetong@gmail.com.\n
# *             All rights reserved.\n
# * @author     spritetong@gmail.com
# * @date       2014
# * @version    1.0, 7/9/2022, Tong
# *             - Initial revision.
# *

# Cross compiler
if(NOT TARGET_C_COMPILER)
    # Try to get the full path of the cross compile GCC.
    cmkabe_get_exe_path("${TARGET}-gcc" TARGET_C_COMPILER)
endif()
if(TARGET_C_COMPILER)
    if(TARGET_TRIPLE MATCHES "^([^-]+)-([^-]+)-([^-]+)")
        set(CMAKE_SYSTEM_PROCESSOR "${CMAKE_MATCH_1}" CACHE STRING "")
        # Convert the system name to camel case.
        cmkabe_initial_capitalize("${CMAKE_MATCH_3}" _system)
        set(CMAKE_SYSTEM_NAME "${_system}" CACHE STRING "")
    else()
        message(FATAL_ERROR "Invalid target triple ${TARGET_TRIPLE}")
    endif()

    if(NOT IS_ABSOLUTE TARGET_C_COMPILER)
        cmkabe_get_exe_path("${TARGET_C_COMPILER}" TARGET_C_COMPILER)
    endif()
    string(REGEX REPLACE "-[^-]+$" "-" _prefix "${TARGET_C_COMPILER}")
    if(NOT _prefix)
        message(FATAL_ERROR "*** Can not find the C compiler: ${TARGET_C_COMPILER}, please add its path to the PATH enviornment variable.")
    endif()
    set(CMAKE_C_COMPILER "${_prefix}gcc" CACHE STRING "" FORCE)
    set(CMAKE_CXX_COMPILER "${_prefix}g++" CACHE STRING "" FORCE)
    set(CMAKE_ASM_COMPILER "${_prefix}gcc" CACHE STRING "" FORCE)
    set(CMAKE_ASM-ATT_COMPILER "${_prefix}as" CACHE STRING "" FORCE)
endif()

if(NOT CMAKE_BUILD_TYPE)
    # Build for Release by default
    set(CMAKE_BUILD_TYPE "Release" CACHE STRING "" FORCE)
endif()

if(NOT DEFINED TARGET_PREFIX)
    if(NOT $ENV{CMAKE_TARGET_PREFIX} STREQUAL "")
        set(TARGET_PREFIX "$ENV{CMAKE_TARGET_PREFIX}")
    else()
        set(TARGET_PREFIX "${CMAKE_SOURCE_DIR}/build/output")
    endif()
endif()

if(NOT DEFINED TARGET_COMMON_INCLUDE_DIR)
    set(TARGET_COMMON_INCLUDE_DIR "${TARGET_PREFIX}/include")
endif()

if(NOT DEFINED TARGET_INCLUDE_DIR)
    set(TARGET_INCLUDE_DIR "${TARGET_PREFIX}/${TARGET_TRIPLE}/include")
endif()

if(NOT DEFINED TARGET_LIB_DIR)
    set(TARGET_LIB_DIR "${TARGET_PREFIX}/${TARGET_TRIPLE}/lib")
endif()

if(NOT DEFINED TARGET_BIN_DIR)
    set(TARGET_BIN_DIR "${TARGET_PREFIX}/${TARGET_TRIPLE}/bin")
endif()

if(NOT DEFINED TARGET_OUTPUT_REDIRECT)
    set(TARGET_OUTPUT_REDIRECT ON)
endif()

if(NOT DEFINED TARGET_STRIP_ON_RELEASE)
    set(TARGET_STRIP_ON_RELEASE ON)
endif()

if(NOT DEFINED TARGET_CC_PIC)
    set(TARGET_CC_PIC ON)
endif()

if(NOT DEFINED TARGET_CC_VISIBILITY_HIDDEN)
    set(TARGET_CC_VISIBILITY_HIDDEN ON)
endif()

if(NOT DEFINED TARGET_CC_NO_DELETE_NULL_POINTER_CHECKS)
    set(TARGET_CC_NO_DELETE_NULL_POINTER_CHECKS ON)
endif()

if(NOT DEFINED TARGET_MSVC_AFXDLL)
    set(TARGET_MSVC_AFXDLL ON)
endif()

if(NOT DEFINED TARGET_MSVC_UNICODE)
    set(TARGET_MSVC_UNICODE ON)
endif()

# ==============================================================================

include(CheckCCompilerFlag)
check_c_compiler_flag("-s" CC_SUPPORT_STRIP)
check_c_compiler_flag("-fPIC" CC_SUPPORT_PIC)
check_c_compiler_flag("-fvisibility=hidden" CC_SUPPORT_VISIBILITY)
check_c_compiler_flag("-fno-delete-null-pointer-checks" CC_SUPPORT_NO_DELETE_NULL_POINTER_CHECKS)

# Redirect the output directorires to the target directories.
if(TARGET_OUTPUT_REDIRECT)
    set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>" CACHE INTERNAL "")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>" CACHE INTERNAL "")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${TARGET_BIN_DIR}$<LOWER_CASE:>" CACHE INTERNAL "")
endif()

if(TARGET_STRIP_ON_RELEASE AND CC_SUPPORT_STRIP)
    if(NOT(CMAKE_C_FLAGS_RELEASE MATCHES " -s( |$)"))
        # Strip debug info for Release
        SET(CMAKE_C_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE} -s" CACHE STRING "" FORCE)
        SET(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -s" CACHE STRING "" FORCE)
        SET(CMAKE_C_FLAGS_MINSIZEREL "${CMAKE_C_FLAGS_MINSIZEREL} -s" CACHE STRING "" FORCE)
        SET(CMAKE_CXX_FLAGS_MINSIZEREL "${CMAKE_CXX_FLAGS_MINSIZEREL} -s" CACHE STRING "" FORCE)
    endif()
endif()

if(NOT(CMAKE_C_FLAGS_DEBUG MATCHES " -D_DEBUG( |$)"))
    SET(CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG} -D_DEBUG" CACHE STRING "" FORCE)
    SET(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -D_DEBUG" CACHE STRING "" FORCE)
endif()

if(TARGET_CC_PIC AND CC_SUPPORT_PIC)
    add_compile_options("-fPIC")
endif()

if(TARGET_CC_VISIBILITY_HIDDEN AND CC_SUPPORT_VISIBILITY)
    add_compile_options("-fvisibility=hidden")
endif()

if(TARGET_CC_NO_DELETE_NULL_POINTER_CHECKS AND CC_SUPPORT_NO_DELETE_NULL_POINTER_CHECKS)
    add_compile_options("-fno-delete-null-pointer-checks")
endif()

if(TARGET_MSVC_AFXDLL AND WIN32)
    add_compile_definitions("_AFXDLL")
endif()

if(TARGET_MSVC_UNICODE AND WIN32)
    add_compile_definitions("_UNICODE")
endif()

include_directories(BEFORE
    SYSTEM "${TARGET_INCLUDE_DIR}"
    SYSTEM "${TARGET_COMMON_INCLUDE_DIR}"
)
link_directories(BEFORE "${TARGET_LIB_DIR}")
