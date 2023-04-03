# * @file       targets.cmake
# * @brief      This file contains target triple definitions to build cmake targets.
# * @details    Copyright (C) 2022 spritetong@gmail.com.\n
# *             All rights reserved.\n
# * @author     spritetong@gmail.com
# * @date       2014
# * @version    1.0, 7/9/2022, Tong
# *             - Initial revision.
# *

if(NOT DEFINED CMKABE_HOME)

include("${CMAKE_CURRENT_LIST_DIR}/env.cmake")

# HOST_ARCH, HOST_TRIPLE
if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Windows")
    cmakabe_target_arch("${CMAKE_HOST_SYSTEM_NAME}" "$ENV{PROCESSOR_ARCHITECTURE}" HOST_ARCH)
	set(HOST_TRIPLE "${HOST_ARCH}-pc-windows-msvc")
else()
    execute_process(
        COMMAND uname -p
        OUTPUT_VARIABLE _arch
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    cmakabe_target_arch("${CMAKE_HOST_SYSTEM_NAME}" "${_arch}" HOST_ARCH)
	if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
		set(HOST_TRIPLE "${HOST_ARCH}-apple-darwin")
	endif()
	if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Linux")
        set(HOST_TRIPLE "${HOST_ARCH}-unknown-linux-gnu")
	endif()
endif()

# TARGET_ARCH, TARGET, TARGET_TRIPLE
if((NOT "${TARGET}" MATCHES "^(|native)$") AND (NOT _CMAKABE_AUTO_TARGET))
    if(NOT TARGET_TRIPLE)
        set(TARGET_TRIPLE "${TARGET}")
    endif()

    # Cross compiler
    if(NOT TARGET_C_COMPILER)
        # Try to get the full path of the cross compile GCC.
        cmkabe_get_exe_path("${TARGET}-gcc" TARGET_C_COMPILER)
    endif()
    if(TARGET_C_COMPILER)
        # Try type "rustup target list" to get all supported target triples.
        if((NOT TARGET_TRIPLE MATCHES "-none(-$)") AND (TARGET_TRIPLE MATCHES "^([^-]+)-([^-]+)-([^-]+)"))
            set(CMAKE_SYSTEM_PROCESSOR "${CMAKE_MATCH_1}" CACHE STRING "" FORCE)
            # Convert the system name to camel case.
            if(CMAKE_MATCH_3 STREQUAL "androideabi")
                set(_system "android")
            else()
                cmkabe_initial_capitalize("${CMAKE_MATCH_3}" _system)
            endif()
            set(CMAKE_SYSTEM_NAME "${_system}" CACHE STRING "" FORCE)
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

    cmakabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
    set(_CMAKABE_AUTO_TARGET OFF CACHE BOOL "")
elseif(WIN32)
    cmakabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
    set(TARGET "${TARGET_ARCH}-pc-windows-msvc")
    set(TARGET_TRIPLE "${TARGET}")
    # Set TARGET automatically.
    set(_CMAKABE_AUTO_TARGET ON CACHE BOOL "")
elseif(UNIX)
    cmakabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
    if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
        set(TARGET "${TARGET_ARCH}-apple-darwin")
    elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
        set(TARGET "${TARGET_ARCH}-unknown-linux-gnu")
    else()
        message(FATAL_ERROR "Can not build for: ${CMAKE_SYSTEM_NAME}")
    endif()
    set(TARGET_TRIPLE "${TARGET}")
    # Set TARGET automatically.
    set(_CMAKABE_AUTO_TARGET ON CACHE BOOL "")
else()
    message(FATAL_ERROR "Can not build for: ${CMAKE_SYSTEM_NAME}")
endif()

set(TARGET_ARCH "${TARGET_ARCH}" CACHE STRING "Target architecture." FORCE)
set(TARGET "${TARGET}" CACHE STRING "Target triple with a specified vendor." FORCE)
set(TARGET_TRIPLE "${TARGET_TRIPLE}" CACHE STRING "Target triple maybe with an unknown vendor." FORCE)

# TARGET_TRIPLE_UNDERSCORE
string(REPLACE "-" "_" TARGET_TRIPLE_UNDERSCORE "${TARGET_TRIPLE}")

endif()
