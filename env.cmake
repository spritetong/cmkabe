# * @file       env.cmake
# * @brief      This file contains environment and common utilities for CMake.
# * @details    This file is the part of the `cmkabe` library
# *             (https://github.com/spritetong/cmkabe),
# *             which is licensed under the MIT license
# *             (https://opensource.org/licenses/MIT).
# *             Copyright (C) 2024 spritetong@gmail.com.
# * @author     spritetong@gmail.com
# * @date       2022
# * @version    1.0, 7/9/2022, Tong
# *             - Initial revision.
# *

cmake_minimum_required(VERSION 3.16)

if(NOT DEFINED _CMKABE_ENV_INITED)
set(_CMKABE_ENV_INITED ON)

if(NOT DEFINED CMKABE_HOME)
    set(CMKABE_HOME "${CMAKE_CURRENT_LIST_DIR}")
endif()

# If `TARGET_IS_NATIVE` is `ON`, return `native`; otherwise, return `${TARGET}`.
set(CMKABE_TARGET "native")

# `CMKABE_IS_LOADED_AS_TOOLCHAIN_FILE`:
#    If the CMKABE module is loaded as a toolchain file, the value is `ON`; otherwise `OFF`.
if(NOT DEFINED CMKABE_IS_LOADED_AS_TOOLCHAIN_FILE)
    get_filename_component(_cmkabe_path "${CMAKE_CURRENT_LIST_FILE}" DIRECTORY)
    get_filename_component(_cmkabe_path "${_cmkabe_path}/toolchain.cmake" ABSOLUTE)
    if ("${CMAKE_TOOLCHAIN_FILE}" STREQUAL "${_cmkabe_path}")
        set(CMKABE_IS_LOADED_AS_TOOLCHAIN_FILE ON)
    else()
        set(CMKABE_IS_LOADED_AS_TOOLCHAIN_FILE OFF)
    endif()
    set(CMKABE_IS_LOADED_AS_TOOLCHAIN_FILE "${CMKABE_IS_LOADED_AS_TOOLCHAIN_FILE}"
        CACHE INTERNAL "CMKABE is loaded as toolchain file or not.")
    unset(_cmkabe_path)
endif()

# `CMAKE_BUILD_TYPE`
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Release")
endif()
string(TOLOWER "${CMAKE_BUILD_TYPE}" CMAKE_BUILD_TYPE_LOWER)

# `CMAKE_HOST_SYSTEM_PROCESSOR`
if(NOT CMAKE_HOST_SYSTEM_PROCESSOR)
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

# Check if the C compiler is GNU or Clang
function(cmkabe_c_compiler_is_gnu_clang result)
    set(value OFF)
    if(DEFINED CMAKE_C_COMPILER_ID)
        if(CMAKE_C_COMPILER_ID MATCHES "(Clang|GNU)")
            set(value ON)
        endif()
    elseif(TARGET_CC MATCHES "(clang|gcc|armcc|zig-cc)(\\.exe)?$")
        set(value ON)
    elseif((NOT TARGET_CC) AND (NOT TARGET_IS_MSVC))
        set(value ON)
    endif()
    set(${result} "${value}" PARENT_SCOPE)
endfunction()

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

# Function:
#   cmkabe_set_target_output_directory(<target> [NONE | DEFAULT | REDIRECT | DIRECTORY <dir>])
#
# Set the output directory of a target.
#   NONE: Set the output directory to `${CMAKE_CURRENT_BINARY_DIR}`.
#   DEFAULT: Set the output directory to `${CMAKE_BINARY_DIR}`.
#   REDIRECT: Set the output directory to `${TARGET_LIB_DIR}`, `${TARGET_BIN_DIR}`.
#   DIRECTORY: Set the output directory to `<dir>`.
function(cmkabe_set_target_output_directory)
    list(POP_FRONT ARGN target)
    if(NOT target)
        message(FATAL_ERROR "<target> is missing.")
    endif()
    cmake_parse_arguments(args "NONE;DEFAULT;REDIRECT" "DIRECTORY" "" ${ARGN})

    if(args_DIRECTORY)
        set_target_properties(${target} PROPERTIES
            ARCHIVE_OUTPUT_DIRECTORY "${output_dir}$<LOWER_CASE:>"
            LIBRARY_OUTPUT_DIRECTORY "${output_dir}$<LOWER_CASE:>"
            RUNTIME_OUTPUT_DIRECTORY "${output_dir}$<LOWER_CASE:>"
        )
    elseif(args_REDIRECT)
        set_target_properties(${target} PROPERTIES
            ARCHIVE_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>"
            LIBRARY_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>"
            RUNTIME_OUTPUT_DIRECTORY "${TARGET_BIN_DIR}$<LOWER_CASE:>"
        )
    elseif(args_DEFAULT)
        set_target_properties(${target} PROPERTIES
            ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}$<LOWER_CASE:>"
            LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}$<LOWER_CASE:>"
            RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}$<LOWER_CASE:>"
        )
    else()
        set_target_properties(${target} PROPERTIES
            ARCHIVE_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}$<LOWER_CASE:>"
            LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}$<LOWER_CASE:>"
            RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}$<LOWER_CASE:>"
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

# Set C++ standard (11, 14, or 17 ...)
function(cmkabe_set_cxx_standard cxx_standard)
    set(CMAKE_CXX_STANDARD ${cxx_standard} CACHE STRING "C++ stardard version." FORCE)
    set(CMAKE_CXX_STANDARD_REQUIRED ON CACHE BOOL "Enable/disable setting of C++ stardard version." FORCE)
    if(MSVC OR TARGET_IS_MSVC)
        add_compile_options($<$<COMPILE_LANGUAGE:CXX>:/Zc:__cplusplus>)
    endif()
endfunction()

# Function:
#   cmkabe_rust_dlls_for_linker(<result> [name1 name2 ...])
#
# On Windows MSVC, add a suffix ".dll.lib" to each item of the dll list and return the result list.
# On other platforms, return the input list directly.
#
# Library File Name Format of Rust:
# Windows MSVC: Shared (`<name>.dll`, `<name>.dll.lib`); Static `<name>.lib`
# Windows GNU: Shared (`<name>.dll`, `lib<name>.dll.a`); Static `lib<name>.a`
# Linux: Shared `lib<name>.so`; Static `lib<name>.a`
# Apple: Shared `lib<name>.dylib`; Static `lib<name>.a`
function(cmkabe_rust_dlls_for_linker)
    list(POP_FRONT ARGN result)
    if(NOT result)
        message(FATAL_ERROR "<result> is missing.")
    endif()

    set(dlls)
    foreach(name IN LISTS ARGN)
        set(lib_opt "")
        if(name MATCHES "^-l(.*)$")
            set(lib_opt "-l")
            set(name "${CMAKE_MATCH_1}")
        endif()
        if(WIN32 AND (CMAKE_IMPORT_LIBRARY_SUFFIX STREQUAL ".lib"))
            list(APPEND dlls "${name}.dll.lib")
        else()
            list(APPEND dlls "${lib_opt}${name}")
        endif()
    endforeach()
    set(${result} ${dlls} PARENT_SCOPE)
endfunction()

# Function:
#   cmkabe_target_link_rust_dlls(<target> <INTERFACE|PUBLIC|PRIVATE> [name1 name2 ...])
#
# Link the specified Rust DLLs to the <target>.
function(cmkabe_target_link_rust_dlls)
    list(POP_FRONT ARGN target)
    if(NOT target)
        message(FATAL_ERROR "<target> is missing.")
    endif()
    cmake_parse_arguments(args "INTERFACE;PUBLIC;PRIVATE" "" "" ${ARGN})

    set(args)
    if(args_INTERFACE)
        list(APPEND args "INTERFACE")
    elseif(args_PUBLIC)
        list(APPEND args "PUBLIC")
    elseif(args_PRIVATE)
        list(APPEND args "PRIVATE")
    endif()
    cmkabe_rust_dlls_for_linker(dlls ${args_UNPARSED_ARGUMENTS})
    list(APPEND args ${dlls})
    target_link_libraries(${target} ${args})
endfunction()

# Function:
#   cmkabe_install_rust_dlls(name1 name2 ... [DIRECTORY dir] EXCLUDE_FROM_ALL [COMPONENT component])
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

    if(args_DIRECTORY)
        set(dir "${args_DIRECTORY}/")
    else()
        set(dir "")
    endif()
    foreach(name IN LISTS args_UNPARSED_ARGUMENTS)
        set(dll "${CMAKE_SHARED_LIBRARY_PREFIX}${name}${CMAKE_SHARED_LIBRARY_SUFFIX}")
        if(WIN32)
            set(lib "${CMAKE_IMPORT_LIBRARY_PREFIX}${name}${CMAKE_IMPORT_LIBRARY_SUFFIX}")
            if(CMAKE_IMPORT_LIBRARY_SUFFIX STREQUAL ".lib")
                install(FILES "${dir}${name}.dll.lib" DESTINATION lib RENAME "${lib}" ${component})
            else()
                install(FILES "${dir}${lib}" DESTINATION lib ${component})
            endif()
            install(FILES "${dir}${dll}" DESTINATION bin ${component})
        else()
            install(FILES "${dir}${dll}" DESTINATION lib ${component})
        endif()
    endforeach()
endfunction()

# Function:
# cmkabe_make_options(result)
#
# Returns the common options to pass to the `make` command.
function(cmkabe_make_options result)
    set(debug OFF)
    set(minsize OFF)
    set(dbginfo OFF)
    if(CMAKE_BUILD_TYPE_LOWER STREQUAL "debug")
        set(debug ON)
        set(dbginfo ON)
    elseif(CMAKE_BUILD_TYPE_LOWER STREQUAL "minsizerel")
        set(minsize ON)
    elseif(CMAKE_BUILD_TYPE_LOWER STREQUAL "relwithdebinfo")
        set(dbginfo ON)
    endif()
    set(${result}
        TARGET=${CMKABE_TARGET}
        TARGET_DIR=${TARGET_DIR}
        TARGET_CMAKE_DIR=${TARGET_CMAKE_DIR}
        CMAKE_TARGET_PREFIX=${TARGET_PREFIX}
        TARGET_CC=${TARGET_CC}
        CARGO_TARGET=${CARGO_TARGET}
        ZIG_TARGET=${ZIG_TARGET}
        DEBUG=${debug}
        MINSIZE=${minsize}
        DBGINFO=${dbginfo}
        PARENT_SCOPE
    )
endfunction()

# Function:
# cmkabe_add_make_target(
#     Name [ALL]
#     TARGETS target1 [target2...]
#     [ENVIRONMENT [env1...]]
#     [DEPENDS depend depend depend ... ]
#     [BYPRODUCTS [files...]]
#     [WORKING_DIRECTORY dir]
#     [COMMENT comment]
#     [JOB_POOL job_pool]
#     [JOB_SERVER_AWARE <bool>]
#     [VERBATIM] [USES_TERMINAL]
#     [COMMAND_EXPAND_LISTS]
#     [SOURCES src1 [src2...]]
# )
function(cmkabe_add_make_target)
    set(options ALL VERBATIM USES_TERMINAL COMMAND_EXPAND_LISTS)
    set(one_value_args WORKING_DIRECTORY COMMENT JOB_POOL JOB_SERVER_AWARE)
    set(multi_value_args DEPENDS BYPRODUCTS SOURCES)
    cmake_parse_arguments(PARSE_ARGV 0 args 
        "${options}" "${one_value_args}" "TARGETS;ENVIRONMENT;${multi_value_args}")

    set(lst)
    cmkabe_make_options(make_options)

    if(NOT args_WORKING_DIRECTORY)
        set(args_WORKING_DIRECTORY "${WORKSPACE_DIR}")
    endif()

    # name
    list(POP_FRONT args_UNPARSED_ARGUMENTS name)
    list(APPEND lst "${name}")
    # options
    foreach(arg IN LISTS options)
        if(args_${arg})
            list(APPEND lst "${arg}")
        endif()
    endforeach()
    # one-value args
    foreach(arg IN LISTS one_value_args)
        if(args_${arg})
            list(APPEND lst "${arg}" "${args_${arg}}")
        endif()
    endforeach()
    # multi-value args
    foreach(arg IN LISTS multi_value_args)
        if(args_${arg})
            list(APPEND lst "${arg}" ${args_${arg}})
        endif()
    endforeach()
    # command
    list(APPEND lst "COMMAND")
    if(args_ENVIRONMENT)
        list(APPEND lst "${CMAKE_COMMAND}" "-E" "env" ${args_ENVIRONMENT})
    endif()
    list(APPEND lst "make")
    list(APPEND lst ${args_TARGETS})
    list(APPEND lst ${make_options})
    if(args_DEPENDS)
        list(JOIN args_DEPENDS "," depends)
        list(APPEND lst "CMKABE_COMPLETED_PORJECTS=${depends}")
    endif()

    add_custom_target(${lst})
endfunction()

# Function:
# cmkabe_add_env_compiler_flags(target lang1 lang2 ...)
function(cmkabe_add_env_compiler_flags)
    list(POP_FRONT ARGN target)
    foreach(lang IN LISTS ARGN)
        set(name "${lang}FLAGS_${target}")
        string(STRIP "$ENV{${name}}" value)
        if(NOT value STREQUAL "")
            set(CMAKE_${lang}_FLAGS " ${value}" PARENT_SCOPE)
        endif()
    endforeach()
endfunction()

function(_cmkabe_build_make_deps)
    if(CMAKE_HOST_SYSTEM_NAME STREQUAL "Windows")
        set(python "python.exe")
    else()
        set(python "python3")
    endif()
    cmkabe_make_options(options)
    execute_process(
        COMMAND ${python} ${CMAKE_CURRENT_LIST_DIR}/shlutil.py build_target_deps ${options}
        OUTPUT_VARIABLE output
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
endfunction()

function(_cmkabe_apply_extra_flags)
    # Read global flags
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS}")
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS}")
    set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS}")
    set(CMAKE_SYSTEM_PREFIX_PATH "${CMAKE_SYSTEM_PREFIX_PATH}")

    if(CARGO_TARGET_UNDERSCORE)
        cmkabe_add_env_compiler_flags(${CARGO_TARGET_UNDERSCORE} C CXX)
    endif()

    # Allow `__declspec(dllexport)` by defaults.
    if(ZIG AND (NOT ZIG_CC_DISABLE_DLLEXPORT))
        string(REPLACE "--disable-dllexport" "" CMAKE_C_FLAGS "${CMAKE_C_FLAGS}")
        string(REPLACE "--disable-dllexport" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
    endif()

    cmkabe_c_compiler_is_gnu_clang(is_gcc_clang)
    if(TARGET_IS_MSVC OR (CMAKE_C_COMPILER_ID STREQUAL "MSVC"))
        set(I "/I ")
        set(L "/LIBPATH:")
    elseif(is_gcc_clang)
        set(I "-isystem ")
        set(L "-L ")
    else()
        set(I "-I ")
        set(L "-L ")
    endif()

    if (TARGET_INCLUDE_DIR)
        string(APPEND CMAKE_C_FLAGS " ${I}\"${TARGET_INCLUDE_DIR}\"")
        string(APPEND CMAKE_CXX_FLAGS " ${I}\"${TARGET_INCLUDE_DIR}\"")
    endif()
    foreach(dir IN LISTS TARGET_PREFIX_INCLUDES)
        if((NOT dir STREQUAL "${TARGET_INCLUDE_DIR}") AND (IS_DIRECTORY "${dir}"))
            string(APPEND CMAKE_C_FLAGS " ${I}\"${dir}\"")
            string(APPEND CMAKE_CXX_FLAGS " ${I}\"${dir}\"")
        endif()
    endforeach()

    set(path)
    foreach(dir IN ITEMS "${CARGO_OUT_DIR}" "${CMAKE_BINARY_DIR}" "${TARGET_LIB_DIR}")
        if((NOT dir STREQUAL "") AND (NOT "${dir}" IN_LIST path))
            list(APPEND path "${dir}")
            string(APPEND CMAKE_EXE_LINKER_FLAGS " ${L}\"${dir}\"")
            string(APPEND CMAKE_SHARED_LINKER_FLAGS " ${L}\"${dir}\"")
        endif()
    endforeach()
    foreach(dir IN LISTS TARGET_PREFIX_LIBS)
        if((NOT "${dir}" IN_LIST path) AND (IS_DIRECTORY "${dir}"))
            string(APPEND CMAKE_EXE_LINKER_FLAGS " ${L}\"${dir}\"")
            string(APPEND CMAKE_SHARED_LINKER_FLAGS " ${L}\"${dir}\"")
        endif()
    endforeach()

    set(path)
    foreach(dir IN LISTS TARGET_PREFIX_SUBDIRS)
        if(IS_DIRECTORY "${dir}")
            list(APPEND path "${dir}")
        endif()
    endforeach()
    list(INSERT CMAKE_SYSTEM_PREFIX_PATH 0 "${path}")

    # Write global flags
    set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS}" PARENT_SCOPE)
    set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}" PARENT_SCOPE)
    set(CMAKE_EXE_LINKER_FLAGS "${CMAKE_EXE_LINKER_FLAGS}" PARENT_SCOPE)
    set(CMAKE_SHARED_LINKER_FLAGS "${CMAKE_SHARED_LINKER_FLAGS}" PARENT_SCOPE)
    set(CMAKE_SYSTEM_PREFIX_PATH "${CMAKE_SYSTEM_PREFIX_PATH}" PARENT_SCOPE)
endfunction()

endif()
