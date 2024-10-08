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

cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED _CMKABE_TOOLCHAIN_INITED)
set(_CMKABE_TOOLCHAIN_INITED ON)

include("${CMAKE_CURRENT_LIST_DIR}/env.cmake")

# Default value of `CARGO_TARGET_DIR`
if(NOT DEFINED TARGET_DIR)
    set(TARGET_DIR "${CMAKE_SOURCE_DIR}/target")
endif()

# The root of CMake build directories.
if(NOT DEFINED TARGET_CMAKE_DIR)
    set(TARGET_CMAKE_DIR "${TARGET_DIR}/.cmake")
endif()

# `HOST_TARGET`
set(DOT_HOST_CMAKE "${TARGET_CMAKE_DIR}/.${CMKABE_HOST_SYSTEM_LOWER}.host.cmake")
if(NOT EXISTS "${DOT_HOST_CMAKE}")
    _cmkabe_build_make_deps()
endif()
include("${DOT_HOST_CMAKE}")

# Target and toolchain definitions.
if("${TARGET}" MATCHES "^(|native)$")
    set(DOT_TARGET_DIR "${TARGET_CMAKE_DIR}/${CMKABE_HOST_SYSTEM_LOWER}-native")
else()
    set(DOT_TARGET_DIR "${TARGET_CMAKE_DIR}/${TARGET}")
endif()
if(NOT EXISTS "${DOT_TARGET_DIR}/.${CMKABE_HOST_SYSTEM_LOWER}.settings.cmake")
    _cmkabe_build_make_deps()
endif()
include("${DOT_TARGET_DIR}/.${CMKABE_HOST_SYSTEM_LOWER}.settings.cmake")
include("${DOT_TARGET_DIR}/.${CMKABE_HOST_SYSTEM_LOWER}.environ.cmake")

# Update `CMKABE_TARGET` 
if(NOT TARGET_IS_NATIVE)
    set(CMKABE_TARGET "${TARGET}")
endif()

if(TARGET_IS_ANDROID)
    # Android

    # ANDROID_SDK_VERSION, ANDROID_ARM_MODE, ANDROID_ARM_NEON, ANDROID_STL
    if(NOT DEFINED ANDROID_SDK_VERSION)
        set(ANDROID_SDK_VERSION 24)
    endif()
    if(TARGET_ARCH STREQUAL "thumbv7neon")
        if(NOT DEFINED ANDROID_ARM_MODE)
            set(ANDROID_ARM_MODE "thumb")
        endif()
        if(NOT DEFINED ANDROID_ARM_NEON)
            set(ANDROID_ARM_NEON ON)
        endif()
    else()
        unset(ANDROID_ARM_MODE)
        unset(ANDROID_ARM_NEON)
    endif()
    if(NOT DEFINED ANDROID_STL)
        set(ANDROID_STL "c++_static")
    endif()

    set(ANDROID_TOOLCHAIN clang)
    set(ANDROID_ARCH "${ANDROID_ARCH}")
    set(ANDROID_ABI "${ANDROID_ABI}")
    set(ANDROID_SDK_VERSION "${ANDROID_SDK_VERSION}")
    set(ANDROID_NATIVE_API_LEVEL "${ANDROID_SDK_VERSION}")
    set(ANDROID_NDK "${ANDROID_NDK_ROOT}")
    set(ANDROID_PLATFORM "android-${ANDROID_SDK_VERSION}")

    set(CMAKE_SYSTEM_NAME "Android")
    set(CMAKE_SYSTEM_PROCESSOR "${ANDROID_ABI}")
    set(CMAKE_SYSTEM_VERSION "${ANDROID_SDK_VERSION}")
    set(CMAKE_TOOLCHAIN_FILE "${ANDROID_NDK}/build/cmake/android.toolchain.cmake")
    set(CMAKE_ANDROID_ARCH_ABI "${ANDROID_ARCH}")
    set(CMAKE_ANDROID_NDK "${ANDROID_NDK}")
    set(CMAKE_ANDROID_NDK_TOOLCHAIN_VERSION clang)
elseif(ZIG OR TARGET_CC)
    # Cross compiler

    # Convert the system name to camel case.
    if(TARGET_IS_WIN32)
        set(_system "Windows")
    elseif(TARGET_IS_ANDROID)
        set(_system "Android")
    elseif(TARGET_IS_APPLE AND NOT TARGET_IS_IOS)
        set(_system "Darwin")
    elseif(TARGET_IS_APPLE AND TARGET_IS_IOS)
        set(_system "iOS")
    else()
        cmkabe_initial_capitalize("${TARGET_OS}" _system)
    endif()

    set(CMAKE_SYSTEM_NAME "${_system}")
    set(CMAKE_SYSTEM_PROCESSOR "${TARGET_ARCH}")

    set(CMAKE_C_COMPILER "${TARGET_CC}")
    set(CMAKE_CXX_COMPILER "${TARGET_CXX}")
    set(CMAKE_ASM_COMPILER "${TARGET_CC}")
    set(CMAKE_ASM-ATT_COMPILER "${TARGET_CC}")
    if(NOT MSVC_MASM STREQUAL "")
        set(CMAKE_ASM_MASM_COMPILER "${MSVC_MASM}")
    endif()
    set(CMAKE_AR "${TARGET_AR}")
    set(CMAKE_RANLIB "${TARGET_RANLIB}")

    if(TARGET_RC)
        set(CMAKE_RC_COMPILER "${TARGET_RC}")
    endif()
else()
    # Native

    set(CMAKE_SYSTEM_NAME "${CMAKE_HOST_SYSTEM_NAME}")
    if(MSVC_ARCH)
        set(CMAKE_SYSTEM_PROCESSOR "${MSVC_ARCH}")
        if(CMAKE_GENERATOR MATCHES "^($|Visual Studio)")
            set(CMAKE_GENERATOR_PLATFORM "${MSVC_ARCH}")
        endif()
    else()
        set(CMAKE_SYSTEM_PROCESSOR "${TARGET_ARCH}")
    endif()
endif()

endif()
