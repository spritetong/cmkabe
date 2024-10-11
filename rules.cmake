# * @file       rules.cmake
# * @brief      This file contains common rules to build cmake targets.
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

if(NOT DEFINED _CMKABE_RULES_INITIALIZED)
set(_CMKABE_RULES_INITIALIZED ON)

include("${CMAKE_CURRENT_LIST_DIR}/toolchain.cmake")

if(NOT DEFINED TARGET_PREFIX_DIR)
    message(FATAL_ERROR "`TARGET_PREFIX_DIR` is not defined.")
endif()

set(TARGET_INCLUDE_DIR "${TARGET_PREFIX_DIR}/include"
    CACHE STRING "Target include directory.")
set(TARGET_LIB_DIR "${TARGET_PREFIX_DIR}/lib"
    CACHE STRING "Target library output directory while `TARGET_OUTPUT_MODE` is `REDIRECT`.")
set(TARGET_BIN_DIR "${TARGET_PREFIX_DIR}/bin"
    CACHE STRING "Target binary output directory while `TARGET_OUTPUT_MODE` is `REDIRECT`.")

set(TARGET_OUTPUT_MODE "DEFAULT"
    CACHE STRING "Mode to set the target output directory: `NONE`, `DEFAULT` OR `REDIRECT`.")

option(TARGET_STRIP_ON_RELEASE
    "Strip the target on release build."
    ON)

option(TARGET_CC_PIC
    "Add the `-fPIC` option to C/C++ compiler by default."
    ON)

option(TARGET_CC_VISIBILITY_HIDDEN
    "Add option `-fvisibility=hidden` to C/C++ compiler by default."
    ON)

option(TARGET_MSVC_AFXDLL
    "Add definition `_AFXDLL` to MSVC compiler by default."
    ON)

option(TARGET_MSVC_UNICODE
    "Add definition `_UNICODE` to MSVC compiler by default."
    ON)
option(TARGET_MSVC_UTF8
    "Add option `/utf-8` to MSVC compiler by default."
    ON)
option(TARGET_MSVC_NO_PDB_WARNING
    "Add option `/ignore:4099` to MSVC linker by default."
    ON)

# ==============================================================================

if(NOT "${PROJECT_NAME}" STREQUAL "")
    message(FATAL_ERROR "Can not define any project before `include <cmake-abe>/rules.cmake`.")
endif()
# Define a dummy project.
project(CMKABE LANGUAGES C CXX ASM)

if(ZIG AND (CMAKE_IMPORT_LIBRARY_SUFFIX STREQUAL ".dll.a"))
    # Change the DLL file name from `lib<name>.dll` to `<name>.dll`
    set(CMAKE_SHARED_LIBRARY_PREFIX "")
    set(CMAKE_SHARED_LIBRARY_SUFFIX ".dll")
    set(CMAKE_IMPORT_LIBRARY_PREFIX "lib")
    set(CMAKE_IMPORT_LIBRARY_SUFFIX ".dll.a")
endif()

include(CheckCCompilerFlag)
check_c_compiler_flag("-fPIC" CC_HAVE_OPTION_PIC)

if(CMAKE_C_COMPILER_ID MATCHES "(Clang|GNU)")
    check_c_compiler_flag("-s" CC_HAVE_OPTION_STRIP)
else()
    set(CC_HAVE_OPTION_STRIP OFF)
endif()

# Redirect the output directorires to the target directories.
if(TARGET_OUTPUT_MODE MATCHES "^[Rr][Ee][Dd][Ii][Rr][Ee][Cc][Tt]$")
    set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${TARGET_BIN_DIR}$<LOWER_CASE:>")
elseif(TARGET_OUTPUT_MODE MATCHES "^[Dd][Ee][Ff][Aa][Uu][Ll][Tt]$")
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

if(TARGET_CC_PIC AND CC_HAVE_OPTION_PIC)
    add_compile_options($<$<COMPILE_LANGUAGE:C,CXX>:-fPIC>)
endif()

if(TARGET_CC_VISIBILITY_HIDDEN)
    set(CMAKE_C_VISIBILITY_PRESET "hidden")
    set(CMAKE_CXX_VISIBILITY_PRESET "hidden")
    set(CMAKE_ASM_VISIBILITY_PRESET "hidden")
endif()

if(TARGET_MSVC_AFXDLL AND (MSVC OR TARGET_IS_MSVC))
    add_compile_definitions($<$<COMPILE_LANGUAGE:C,CXX>:_AFXDLL>)
endif()

if(TARGET_MSVC_UNICODE AND (MSVC OR TARGET_IS_MSVC))
    add_compile_definitions($<$<COMPILE_LANGUAGE:C,CXX>:UNICODE> $<$<COMPILE_LANGUAGE:C,CXX>:_UNICODE>)
endif()

if(TARGET_MSVC_UTF8 AND (MSVC OR TARGET_IS_MSVC))
    add_compile_options($<$<COMPILE_LANGUAGE:C,CXX>:/utf-8>)
endif()

if(TARGET_MSVC_NO_PDB_WARNING AND (MSVC OR TARGET_IS_MSVC))
    # MSVC warning LNK4099: PDB 'vc80.pdb' was not found
    add_link_options(/ignore:4099)
endif()

_cmkabe_apply_extra_flags()

endif()
