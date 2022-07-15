# * @file       env.cmake
# * @brief      This file contains environment and common utilities for CMake.
# * @details    Copyright (C) 2022 spritetong@gmail.com.\n
# *             All rights reserved.\n
# * @author     spritetong@gmail.com
# * @date       2014
# * @version    1.0, 7/9/2022, Tong
# *             - Initial revision.
# *

if(NOT DEFINED CMKABE_HOME)
set(CMKABE_HOME "${CMAKE_CURRENT_LIST_DIR}")

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

endif()
