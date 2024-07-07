# * @file       env.cmake
# * @brief      This file contains environment and common utilities for CMake.
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

if(NOT DEFINED CMKABE_HOME)
set(CMKABE_HOME "${CMAKE_CURRENT_LIST_DIR}")

# Windows ARCH -> Rust ARCH
set(__WIN_ARCH_MAP "arm64=aarch64;amd64=x86_64;x64=x86_64;x86=i686;win32=i686")
# Rust ARCH -> MSVC ARCH
set(__MSVC_ARCH_MAP "aarch64=ARM64;x86_64=x64;i686=Win32")
# Rust ARCH -> Android ARCH
set(__ANDROID_ARCH_MAP "aarch64=aarch64;armv7=armv7a;thumbv7neon=armv7a;i686=i686;x86_64=x86_64")

# CMAKE_HOST_SYSTEM_PROCESSOR
if("${CMAKE_HOST_SYSTEM_PROCESSOR}" STREQUAL "")
    if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Windows")
        set(CMAKE_HOST_SYSTEM_PROCESSOR "$ENV{PROCESSOR_ARCHITECTURE}")
        if(("${CMAKE_HOST_SYSTEM_PROCESSOR}" STREQUAL "x86") AND
                (NOT "$ENV{ProgramW6432}" STREQUAL "$ENV{ProgramFiles}") AND
                (NOT "$ENV{ProgramW6432}" STREQUAL ""))
            set(CMAKE_HOST_SYSTEM_PROCESSOR "x64")
        endif()
    else()
        execute_process(
            COMMAND uname -m
            OUTPUT_VARIABLE CMAKE_HOST_SYSTEM_PROCESSOR
            OUTPUT_STRIP_TRAILING_WHITESPACE
        )
    endif()
endif()

# CMKABE_PS: the path separator, ";" on Windows, ":" on Linux
# CMKABE_EXE_EXT: default extension for executables
if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Windows")
    set(CMKABE_PS ";")
    set(CMKABE_EXE_EXT ".exe")
else()
    set(CMKABE_PS ":")
    set(CMKABE_EXE_EXT "")
endif()

# Find the value of a key in a key-value map string.
function(cmkabe_value_from_map map_string key default result)
    set(value "${default}")
    foreach(kv ${map_string})
        if("${kv}" MATCHES "^([^=]+)=(.*)$")
            if(CMAKE_MATCH_1 STREQUAL "${key}")
                set(value "${CMAKE_MATCH_2}")
                break()
            endif()
        endif()
    endforeach()
    set(${result} "${value}" PARENT_SCOPE)
endfunction()

# Capitalize the initial fo a string.
function(cmkabe_initial_capitalize str result)
    # Convert the system name to camel case.
    string(SUBSTRING "${str}" 0 1 x)
    string(TOUPPER "${x}" x)
    string(REGEX REPLACE "^.(.*)$" "${x}\\1" x "${str}")
    set(${result} "${x}" PARENT_SCOPE)
endfunction()

# Convert an underscore string into camel-case.
function(cmkabe_underscore_camel_case str result)
    string(TOLOWER "${str}" str)
    string(REPLACE "_" ";" words "${str}")
    set(value "")
    foreach(x IN ITEMS ${words})
        cmkabe_initial_capitalize("${x}" x)
        set(value "${value}${x}")
    endforeach()
    set(${result} "${value}" PARENT_SCOPE)
endfunction()

# Convert a camel-case string into lower-case-underscore.
function(cmkabe_camel_case_to_lower_underscore str result)
    string(REGEX REPLACE "(.)([A-Z][a-z]+)" "\\1_\\2" value "${str}")
    string(REGEX REPLACE "([a-z0-9])([A-Z])" "\\1_\\2" value "${value}")
    string(TOLOWER "${value}" value)
    set(${result} "${value}" PARENT_SCOPE)
endfunction()

# Convert a camel-case string into upper-case-underscore.
function(cmkabe_camel_case_to_upper_underscore str result)
    cmkabe_camel_case_to_lower_underscore("${str}" value)
    string(TOUPPER "${value}" value)
    set(${result} "${value}" PARENT_SCOPE)
endfunction()

# Get the full path of an executable.
# There is no `NO_CACHE` option for `find_program` before CMake 3.21.
function(cmkabe_get_exe_path executable result)
    find_program(_cmkabe_get_exe_path "${executable}")
    if(_cmkabe_get_exe_path STREQUAL "_cmkabe_get_exe_path-NOTFOUND")
        set(${result} "" PARENT_SCOPE)
    else()
        set(${result} "${_cmkabe_get_exe_path}" PARENT_SCOPE)
    endif()
    unset(_cmkabe_get_exe_path CACHE)
endfunction()

# Search in a directory and add all projects in its child directories.
function(cmkabe_add_subdirs parent_dir)
    file(GLOB node_list "${parent_dir}/*")
    foreach(node ${node_list})
        if(IS_DIRECTORY "${node}")
            foreach(sub "" "/mk" "/mak" "/make" "/cmk" "/cmake")
                if(EXISTS "${node}${sub}/CMakeLists.txt")
                    add_subdirectory("${node}${sub}")
                endif()
            endforeach()
        endif()
    endforeach()
endfunction()

# Set the output directory of a target.
# If the specified directory is "RESTORE",
# restore the target's output directory to ${CMAKE_CURRENT_BINARY_DIR}.
function(cmkabe_set_target_output_directory target output_dir)
    if((output_dir STREQUAL "DEFAULT") OR (output_dir STREQUAL ""))
        set_target_properties(${target} PROPERTIES
            ARCHIVE_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}"
            LIBRARY_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}"
            RUNTIME_OUTPUT_DIRECTORY "${TARGET_BIN_DIR}"
        )
    elseif(output_dir STREQUAL "RESTORE")
        set_target_properties(${target} PROPERTIES
            ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
            LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
            RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}"
        )
    else()
        set_target_properties(${target} PROPERTIES
            ARCHIVE_OUTPUT_DIRECTORY "${output_dir}"
            LIBRARY_OUTPUT_DIRECTORY "${output_dir}"
            RUNTIME_OUTPUT_DIRECTORY "${output_dir}"
        )
    endif()
endfunction()

# Find a target file or directory in a directory and its ancesters,
# Set the full path in ${result} if the target is found.
function(cmkabe_find_in_ancesters directory name result)
    get_filename_component(current_dir "${directory}" ABSOLUTE)
    while(true)
        if (EXISTS "${current_dir}/${name}")
            set(${result} "${current_dir}/${name}" PARENT_SCOPE)
            return()
        endif()
        # Get the parent directory.
        get_filename_component(current_dir "${current_dir}" DIRECTORY)
        if(NOT current_dir MATCHES "^([A-Za-z]:)?/$")
            break()
        endif()
    endwhile()
    set(${result} "" PARENT_SCOPE)
endfunction()

# Get the target architecture from the system processor.
function(cmkabe_target_arch system_name system_processor result)
    cmkabe_camel_case_to_lower_underscore("${system_processor}" arch)
    if(system_name STREQUAL "Windows")
        cmkabe_value_from_map("${__WIN_ARCH_MAP}" "${arch}" "${arch}" arch)
    endif()
    set(${result} "${arch}" PARENT_SCOPE)
endfunction()

# Set C++ standard (11, 14, or 17 ...)
function(cmkabe_set_cxx_standard cxx_standard)
    set(CMAKE_CXX_STANDARD ${cxx_standard} CACHE STRING "C++ stardard version." FORCE)
    set(CMAKE_CXX_STANDARD_REQUIRED ON CACHE BOOL "Enable/disable setting of C++ stardard version." FORCE)
    if(MSVC)
        add_compile_options("/Zc:__cplusplus")
    endif()
endfunction()

# Function:
#   cmkabe_rust_dlls_for_linker(<result> [dll1 dll2 ...])
#
# On Windows, add a suffix ".dll.lib" to each item of the dll list and return the result list.
# On other platforms, return the input list directly.
function(cmkabe_rust_dlls_for_linker)
    list(POP_FRONT ARGN result)
    if(NOT result)
        message(FATAL_ERROR "<result> is missing.")
    endif()

    set(dlls)
    foreach(item IN LISTS ARGN)
        if(WIN32)
            list(APPEND dlls "${item}.dll.lib")
        else()
            list(APPEND dlls "${item}")
        endif()
    endforeach()
    set(${result} ${dlls} PARENT_SCOPE)
endfunction()

# Function:
#   cmkabe_target_link_rust_dlls(<target> <INTERFACE|PUBLIC|PRIVATE> [items1...])
#
# Link the specified Rust DLLs to the <target>.
function(cmkabe_target_link_rust_dlls)
    list(POP_FRONT ARGN target)
    if(NOT target)
        message(FATAL_ERROR "<target> is missing.")
    endif()
    cmake_parse_arguments(args "INTERFACE;PUBLIC;PRIVATE" "" "" ${ARGN})

    set(args ${target})
    if(args_INTERFACE)
        list(APPEND args "INTERFACE")
    elseif(args_PUBLIC)
        list(APPEND args "PUBLIC")
    elseif(args_PRIVATE)
        list(APPEND args "PRIVATE")
    endif()
    cmkabe_rust_dlls_for_linker(dlls ${args_UNPARSED_ARGUMENTS})
    list(APPEND args ${dlls})
    target_link_libraries(${args})
endfunction()

# Function:
#   cmkabe_install_rust_dlls(dll1 dll2 ... [DIRECTORY dir] EXCLUDE_FROM_ALL [COMPONENT component])
#
# Install the specified DLL files.
# <dir> is the source directory if specified.
# EXCLUDE_FROM_ALL Specify that the file is excluded from a full installation and
#   only installed as part of a component-specific installation.
# <component> is the install component if specified.
function(cmkabe_install_rust_dlls)
    cmake_parse_arguments(args "EXCLUDE_FROM_ALL" "DIRECTORY;COMPONENT" "" ${ARGN})

    set(component "")
    if(args_COMPONENT)
        set(component COMPONENT ${args_COMPONENT})
    endif()
    if(args_EXCLUDE_FROM_ALL)
        list(INSERT component 0 EXCLUDE_FROM_ALL)
    endif()

    foreach(item IN LISTS args_UNPARSED_ARGUMENTS)
        if(WIN32)
            if(args_DIRECTORY)
                set(item "${args_DIRECTORY}/${item}")
            endif()
            install(FILES "${item}.dll" DESTINATION bin ${component})
            get_filename_component(name "${item}" NAME_WE)
            install(FILES "${item}.dll.lib" DESTINATION lib RENAME "${name}.lib" ${component})
        else()
            set(item "lib${item}")
            if(args_DIRECTORY)
                set(item "${args_DIRECTORY}/${item}")
            endif()
            install(FILES "${item}.so" DESTINATION lib ${component})
        endif()
    endforeach()
endfunction()

endif()
