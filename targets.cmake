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
if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Windows")
    cmkabe_target_arch("${CMAKE_HOST_SYSTEM_NAME}" "$ENV{PROCESSOR_ARCHITECTURE}" HOST_ARCH)
	set(HOST_TRIPLE "${HOST_ARCH}-pc-windows-msvc")
else()
    execute_process(
        COMMAND uname -p
        OUTPUT_VARIABLE _arch
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    cmkabe_target_arch("${CMAKE_HOST_SYSTEM_NAME}" "${_arch}" HOST_ARCH)
	if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Darwin")
		set(HOST_TRIPLE "${HOST_ARCH}-apple-darwin")
	endif()
	if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Linux")
        set(HOST_TRIPLE "${HOST_ARCH}-unknown-linux-gnu")
	endif()
endif()

if(NOT DEFINED _CMAKABE_TARGET_INITIALIZED)
    # TARGET_ARCH, TARGET, TARGET_TRIPLE
    if("${TARGET}" MATCHES "^([^-]+)-([^-]+)-(android|androideabi)")
        if(CMAKE_SYSTEM_PROCESSOR STREQUAL "")
            if(NOT ANDROID_ABI STREQUAL "")
                set(CMAKE_SYSTEM_PROCESSOR "${ANDROID_ABI}" CACHE INTERNAL "" FORCE)
            else()
                set(CMAKE_SYSTEM_PROCESSOR "${CMAKE_MATCH_1}" CACHE INTERNAL "" FORCE)
            endif()
        endif()
        set(CMAKE_SYSTEM_NAME "Android" CACHE INTERNAL "" FORCE)
        set(TARGET_ARCH "${CMAKE_MATCH_1}")
        set(TARGET_TRIPLE "${TARGET}")
    elseif(NOT "${TARGET}" MATCHES "^(|native)$")
        if("${TARGET_TRIPLE}" STREQUAL "")
            set(TARGET_TRIPLE "${TARGET}")
        endif()

        # Cross compiler
        if("${TARGET_C_COMPILER}" STREQUAL "")
            # Try to get the full path of the cross compile GCC.
            cmkabe_get_exe_path("${TARGET}-gcc" TARGET_C_COMPILER)
        endif()
        if(NOT TARGET_C_COMPILER STREQUAL "")
            # Try type "rustup target list" to get all supported target triples.
            if((NOT "${TARGET_TRIPLE}" MATCHES "-none(-$)") AND ("${TARGET_TRIPLE}" MATCHES "^([^-]+)-([^-]+)-([^-]+)"))
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
        endif()

        cmkabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
    elseif(WIN32)
        cmkabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
        set(TARGET "${TARGET_ARCH}-pc-windows-msvc")
        set(TARGET_TRIPLE "${TARGET}")
    elseif(UNIX)
        cmkabe_target_arch("${CMAKE_SYSTEM_NAME}" "${CMAKE_SYSTEM_PROCESSOR}" TARGET_ARCH)
        if(CMAKE_SYSTEM_NAME STREQUAL "Darwin")
            set(TARGET "${TARGET_ARCH}-apple-darwin")
        elseif(CMAKE_SYSTEM_NAME STREQUAL "Linux")
            set(TARGET "${TARGET_ARCH}-unknown-linux-gnu")
        else()
            message(FATAL_ERROR "Can not build for: ${CMAKE_SYSTEM_NAME}")
        endif()
        set(TARGET_TRIPLE "${TARGET}")
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
