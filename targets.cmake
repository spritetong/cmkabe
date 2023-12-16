# * @file       targets.cmake
# * @brief      This file contains target triple definitions to build cmake targets.
# * @details    This file is the part of the cmake-abe library
# *             (https://github.com/spritetong/cmake-abe),
# *             which is licensed under the MIT license
# *             (https://opensource.org/licenses/MIT).
# *             Copyright (C) 2022 spritetong@gmail.com.
# * @author     spritetong@gmail.com
# * @date       2022
# * @version    1.0, 7/9/2022, Tong
# *             - Initial revision.
# *

if(NOT DEFINED CMKABE_HOME)

include("${CMAKE_CURRENT_LIST_DIR}/env.cmake")

# HOST_ARCH, HOST_TRIPLE
cmkabe_target_arch("${CMAKE_HOST_SYSTEM_NAME}" "${CMAKE_HOST_SYSTEM_PROCESSOR}" HOST_ARCH)
if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Windows")
	set(HOST_TRIPLE "${HOST_ARCH}-pc-windows-msvc")
elseif(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
    set(HOST_TRIPLE "${HOST_ARCH}-apple-darwin")
elseif(CMAKE_HOST_SYSTEM_NAME STREQUAL "Linux")
    set(HOST_TRIPLE "${HOST_ARCH}-unknown-linux-gnu")
else()
    message(FATAL_ERROR "Unrecognized CMAKE_HOST_SYSTEM_NAME: ${CMAKE_HOST_SYSTEM_NAME}")
endif()

if(NOT DEFINED _CMAKABE_TARGET_INITIALIZED)
    set(_target_type "")
    if("${TARGET}" MATCHES "^(|native)$")
        set(_target_type "native")
    elseif("${TARGET}" STREQUAL "${HOST_TRIPLE}")
        set(_target_type "native")
    elseif("${TARGET}" MATCHES "android")
        set(_target_type "android")
    else()
        # Cross compiler
        if("${TARGET_C_COMPILER}" STREQUAL "")
            # Try to get the full path of the cross compile GCC.
            cmkabe_get_exe_path("${TARGET}-gcc" TARGET_C_COMPILER)
        elseif(NOT IS_ABSOLUTE TARGET_C_COMPILER)
            cmkabe_get_exe_path("${TARGET_C_COMPILER}" TARGET_C_COMPILER)
        endif()

        if(NOT TARGET_C_COMPILER STREQUAL "")
            # The cross compiler has been found.
            set(TARGET_C_COMPILER "${TARGET_C_COMPILER}" CACHE STRING "" FORCE)
            set(_target_type "gcc")
        elseif("${TARGET}" MATCHES "^([^-]+)(.*)$")
            # Check if `system-vendor-env` of ${TARGET} matches that of ${HOST_TRIPLE}.
            set(_arch "${CMAKE_MATCH_1}")
            set(_s "${CMAKE_MATCH_2}")
            if("${HOST_TRIPLE}" MATCHES "^([^-]+)(.*)$")
            endif()
            if(_s STREQUAL "${CMAKE_MATCH_2}")
                if(WIN32)
                    cmkabe_value_from_map("${__MSVC_ARCH_MAP}" "${_arch}" "${_arch}" _arch)
                endif()
                set(_target_type "native")
                set(CMAKE_GENERATOR_PLATFORM "${_arch}")
                set(CMAKE_SYSTEM_PROCESSOR "${_arch}" CACHE INTERNAL "" FORCE)
            endif()
        endif()
    endif()
    if(_target_type STREQUAL "native")
        if("${CMAKE_SYSTEM_NAME}" STREQUAL "")
            set(CMAKE_SYSTEM_NAME "${CMAKE_HOST_SYSTEM_NAME}" CACHE INTERNAL "" FORCE)
        endif()
        if("${CMAKE_SYSTEM_PROCESSOR}" STREQUAL "")
            set(CMAKE_SYSTEM_PROCESSOR "${CMAKE_HOST_SYSTEM_PROCESSOR}" CACHE INTERNAL "" FORCE)
        endif()
    elseif(_target_type STREQUAL "")
        message(FATAL_ERROR "Unrecognized target triple: ${TARGET}")
    endif()

    # TARGET_ARCH, TARGET, TARGET_TRIPLE
    if(_target_type STREQUAL "native" AND WIN32)
        cmkabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
        set(TARGET "${TARGET_ARCH}-pc-windows-msvc")
        set(TARGET_TRIPLE "${TARGET}")
    elseif(_target_type STREQUAL "native" AND UNIX)
        cmkabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
        if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
            set(TARGET "${TARGET_ARCH}-apple-darwin")
        elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
            set(TARGET "${TARGET_ARCH}-unknown-linux-gnu")
        else()
            message(FATAL_ERROR "Can not build for: ${CMAKE_SYSTEM_NAME}")
        endif()
        set(TARGET_TRIPLE "${TARGET}")
    elseif(_target_type STREQUAL "android")
        if(NOT "${TARGET}" MATCHES "^([^-]+)-([^-]+)-(android|androideabi)$")
            message(FATAL_ERROR "Invalid target triple: ${TARGET}")
        endif()
        set(TARGET_ARCH "${CMAKE_MATCH_1}")
        set(TARGET_TRIPLE "${TARGET}")

        # ANDROID_ARCH, ANDROID_ABI, ANDROID_ARM_NEON
        set(_android_arches_k aarch64   armv7       thumbv7neon i686 x86_64)
        set(_android_arches_v aarch64   armv7a      armv7a      i686 x86_64)
        set(_android_abis     arm64-v8a armeabi-v7a armeabi-v7a x86  x86_64)
        list(FIND _android_arches_k "${TARGET_ARCH}" _android_arch_idx)
        if(_android_arch_idx LESS 0)
            message(FATAL_ERROR, "Unknown ARCH: ${TARGET_ARCH}")
        endif()
        list(GET _android_arches_v ${_android_arch_idx} ANDROID_ARCH)
        list(GET _android_abis     ${_android_arch_idx} ANDROID_ABI)

        # ANDROID_SDK_VERSION, ANDROID_ARM_MODE, ANDROID_ARM_NEON, ANDROID_STL
        if(NOT DEFINED ANDROID_SDK_VERSION)
            if(CMAKE_SYSTEM_VERSION STREQUAL "")
                set(ANDROID_SDK_VERSION 21)
            else()
                set(ANDROID_SDK_VERSION "${CMAKE_SYSTEM_VERSION}")
            endif()
        endif()
        # if(NOT DEFINED ANDROID_ARM_MODE)
        #     set(ANDROID_ARM_MODE "thumb")
        # endif()
        # if(NOT DEFINED ANDROID_ARM_NEON)
        #     set(ANDROID_ARM_NEON ON)
        # endif()
        if(NOT DEFINED ANDROID_STL)
            set(ANDROID_STL "c++_static")
        endif()

        set(ANDROID_TOOLCHAIN clang CACHE INTERNAL "")
        set(ANDROID_ARCH "${ANDROID_ARCH}" CACHE INTERNAL "Android architecture." FORCE)
        set(ANDROID_ABI "${ANDROID_ABI}" CACHE INTERNAL "Android ABI." FORCE)
        set(ANDROID_SDK_VERSION "${ANDROID_SDK_VERSION}" CACHE STRING "Android SDK version." FORCE)
        set(ANDROID_NATIVE_API_LEVEL "${ANDROID_SDK_VERSION}" CACHE INTERNAL "" FORCE)
        set(ANDROID_NDK "$ENV{ANDROID_NDK_ROOT}" CACHE INTERNAL "" FORCE)
        set(ANDROID_PLATFORM "android-${ANDROID_SDK_VERSION}" CACHE INTERNAL "" FORCE)
        if(TARGET_ARCH STREQUAL "thumbv7neon")
            if(NOT ANDROID_ARM_MODE STREQUAL "")
                set(ANDROID_ARM_MODE "${ANDROID_ARM_MODE}" CACHE STRING
                    "Specify whether to generate arm or thumb instructions for armeabi-v7a: arm, thumb (default)" FORCE)
            endif()
            if(NOT ANDROID_ARM_NEON STREQUAL "")
                set(ANDROID_ARM_NEON ${ANDROID_ARM_NEON} CACHE BOOL
                    "Specify whether to enable NEON instructions for armeabi-v7a." FORCE)
            endif()
        endif()
        if(NOT ANDROID_STL STREQUAL "")
            set(ANDROID_STL "${ANDROID_STL}" CACHE STRING
                "NDK STL: c++_shared, c++_static (default), none, system" FORCE)
        endif()

        set(CMAKE_SYSTEM_NAME "Android" CACHE INTERNAL "" FORCE)
        set(CMAKE_SYSTEM_PROCESSOR "${ANDROID_ABI}" CACHE INTERNAL "" FORCE)
        set(CMAKE_SYSTEM_VERSION "${ANDROID_SDK_VERSION}" CACHE INTERNAL "" FORCE)
        set(CMAKE_TOOLCHAIN_FILE "${ANDROID_NDK}/build/cmake/android.toolchain.cmake" CACHE INTERNAL "" FORCE)
        set(CMAKE_ANDROID_ARCH_ABI "${ANDROID_ARCH}" CACHE INTERNAL "" FORCE)
        set(CMAKE_ANDROID_NDK "${ANDROID_NDK}" CACHE INTERNAL "" FORCE)
        set(CMAKE_ANDROID_NDK_TOOLCHAIN_VERSION clang CACHE INTERNAL "" FORCE)
    elseif(_target_type STREQUAL "gcc")
        # Cross compiler
        if("${TARGET_TRIPLE}" STREQUAL "")
            set(TARGET_TRIPLE "${TARGET}")
        endif()

        # Try type "rustup target list" to get all supported target triples.
        if((NOT "${TARGET_TRIPLE}" MATCHES "-none(-|$)") AND ("${TARGET_TRIPLE}" MATCHES "^([^-]+)-([^-]+)-([^-]+)"))
            set(CMAKE_SYSTEM_PROCESSOR "${CMAKE_MATCH_1}" CACHE INTERNAL "" FORCE)
            # Convert the system name to camel case.
            if(CMAKE_MATCH_3 STREQUAL "androideabi")
                set(_system "Android")
            else()
                cmkabe_initial_capitalize("${CMAKE_MATCH_3}" _system)
            endif()
            set(CMAKE_SYSTEM_NAME "${_system}" CACHE INTERNAL "" FORCE)
        else()
            message(FATAL_ERROR "Invalid target triple ${TARGET_TRIPLE}")
        endif()

        if(NOT IS_ABSOLUTE TARGET_C_COMPILER)
            cmkabe_get_exe_path("${TARGET_C_COMPILER}" TARGET_C_COMPILER)
        endif()
        string(REGEX REPLACE "-[^-]+$" "-" _prefix "${TARGET_C_COMPILER}")
        if(_prefix STREQUAL "")
            message(FATAL_ERROR "*** Can not find the C compiler: ${TARGET_C_COMPILER}, please add its path to the PATH enviornment variable.")
        endif()
        set(CMAKE_C_COMPILER "${_prefix}gcc" CACHE STRING "C compiler" FORCE)
        set(CMAKE_CXX_COMPILER "${_prefix}g++" CACHE STRING "CXX compiler" FORCE)
        set(CMAKE_ASM_COMPILER "${_prefix}gcc" CACHE STRING "ASM compiler" FORCE)
        set(CMAKE_ASM-ATT_COMPILER "${_prefix}as" CACHE STRING "ASM-ATT compiler" FORCE)

        cmkabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
    else()
        message(FATAL_ERROR "Can not build for: ${CMAKE_SYSTEM_NAME}")
    endif()

    set(TARGET_ARCH "${TARGET_ARCH}" CACHE STRING "Target architecture." FORCE)
    set(TARGET "${TARGET}" CACHE STRING "Target triple with a specified vendor." FORCE)
    set(TARGET_TRIPLE "${TARGET_TRIPLE}" CACHE STRING "Target triple maybe with an unknown vendor." FORCE)

    set(_CMAKABE_TARGET_INITIALIZED ON CACHE INTERNAL "")
endif()

# TARGET_TRIPLE_UNDERSCORE
string(REPLACE "-" "_" TARGET_TRIPLE_UNDERSCORE "${TARGET_TRIPLE}")

endif()
