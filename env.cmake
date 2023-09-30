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

if(NOT DEFINED CMKABE_HOME)
set(CMKABE_HOME "${CMAKE_CURRENT_LIST_DIR}")

# The path separator: ";" on Windows, ":" on Linux
if(WIN32)
    set(CMKABE_PS ";")
else()
    set(CMKABE_PS ":")
endif()

# Capitalize the initial fo a string.
function(cmkabe_initial_capitalize str var)
    # Convert the system name to camel case.
    string(SUBSTRING "${str}" 0 1 x)
    string(TOUPPER "${x}" x)
    string(REGEX REPLACE "^.(.*)$" "${x}\\1" x "${str}")
    set(${var} "${x}" PARENT_SCOPE)
endfunction()

# Convert an underscore string into camel-case.
function(cmkabe_underscore_camel_case str var)
    string(TOLOWER "${str}" str)
    string(REPLACE "_" ";" words "${str}")
    set(value "")
    foreach(x IN ITEMS ${words})
        cmkabe_initial_capitalize("${x}" x)
        set(value "${value}${x}")
    endforeach()
    set(${var} "${value}" PARENT_SCOPE)
endfunction()

# Convert a camel-case string into lower-case-underscore.
function(cmkabe_camel_case_to_lower_underscore str var)
    string(REGEX REPLACE "(.)([A-Z][a-z]+)" "\\1_\\2" value "${str}")
    string(REGEX REPLACE "([a-z0-9])([A-Z])" "\\1_\\2" value "${value}")
    string(TOLOWER "${value}" value)
    set(${var} "${value}" PARENT_SCOPE)
endfunction()

# Convert a camel-case string into upper-case-underscore.
function(cmkabe_camel_case_to_upper_underscore str var)
    cmkabe_camel_case_to_lower_underscore("${str}" value)
    string(TOUPPER "${value}" value)
    set(${var} "${value}" PARENT_SCOPE)
endfunction()

# Get the full path of an executable.
function(cmkabe_get_exe_path executable var)
    if(CMAKE_HOST_WIN32)
        set(which "where")
    else()
        set(which "which")
    endif()
    execute_process(COMMAND "${which}" "${executable}"
        RESULT_VARIABLE status
        OUTPUT_VARIABLE output
        ERROR_QUIET
    )
    if(status EQUAL 0)
        # Only keep the first line.
        string(REGEX MATCH "^([^\r\n]+)" _ "${output}")
        set(output "${CMAKE_MATCH_1}")
    else()
        set(output "")
    endif()
    set(${var} "${output}" PARENT_SCOPE)
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
# Set the full path in ${var} if the target is found.
function(cmkabe_find_in_ancesters directory name var)
    get_filename_component(current_dir "${directory}" ABSOLUTE)
    while(true)
        if (EXISTS "${current_dir}/${name}")
            set(${var} "${current_dir}/${name}" PARENT_SCOPE)
            return()
        endif()
        # Get the parent directory.
        get_filename_component(current_dir "${current_dir}" DIRECTORY)
        if(NOT current_dir MATCHES "^([A-Za-z]:)?/$")
            break()
        endif()
    endwhile()
    set(${var} "" PARENT_SCOPE)
endfunction()

# Get the target architecture from the system processor.
function(cmkabe_target_arch system_name system_processor var)
    cmkabe_camel_case_to_lower_underscore("${system_processor}" arch)
    if(system_name STREQUAL "Windows")
        if(arch STREQUAL "arm64")
            set(arch "aarch64")
        elseif(arch MATCHES "^(amd64|x64)$")
            set(arch "x86_64")
        elseif(arch MATCHES "^(x86|win32)$")
            set(arch "i686")
        endif()
    endif()
    set(${var} "${arch}" PARENT_SCOPE)
endfunction()

# Set C++ standard
function(cmkabe_set_cxx_standard cxx_standard)
    set(CMAKE_CXX_STANDARD ${cxx_standard} CACHE STRING "C++ stardard version." FORCE)
    set(CMAKE_CXX_STANDARD_REQUIRED ON CACHE BOOL "Enable/disable setting of C++ stardard version." FORCE)
    if(MSVC)
        add_compile_options("/Zc:__cplusplus")
    endif()
endfunction()

endif()
