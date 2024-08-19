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

if(NOT DEFINED _CMKABE_RULES_INITIALIZED)
set(_CMKABE_RULES_INITIALIZED ON)

include("${CMAKE_CURRENT_LIST_DIR}/toolchain.cmake")

if(NOT DEFINED TARGET_INCLUDE_DIR)
    set(TARGET_INCLUDE_DIR "${TARGET_PREFIX_TRIPLE}/include")
endif()

if(NOT DEFINED TARGET_LIB_DIR)
    set(TARGET_LIB_DIR "${TARGET_PREFIX_TRIPLE}/lib")
endif()

if(NOT DEFINED TARGET_BIN_DIR)
    set(TARGET_BIN_DIR "${TARGET_PREFIX_TRIPLE}/bin")
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

if(NOT DEFINED TARGET_CC_NO_DELETE_NULL_POINTER_CHECKS)
    set(TARGET_CC_NO_DELETE_NULL_POINTER_CHECKS ON)
endif()

if(NOT DEFINED TARGET_CC_VISIBILITY_HIDDEN)
    set(TARGET_CC_VISIBILITY_HIDDEN ON)
endif()

if(NOT DEFINED TARGET_MSVC_AFXDLL)
    set(TARGET_MSVC_AFXDLL OFF)
endif()

if(NOT DEFINED TARGET_MSVC_UNICODE)
    set(TARGET_MSVC_UNICODE ON)
endif()

if(NOT DEFINED TARGET_MSVC_UTF8)
    set(TARGET_MSVC_UTF8 ON)
endif()

if(NOT DEFINED TARGET_MSVC_NO_PDB_WARNING)
    set(TARGET_MSVC_NO_PDB_WARNING ON)
endif()

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

if(MSVC)
    set(CC_DEFINE_OPT "/D")
else()
    set(CC_DEFINE_OPT "-D")
endif()

include(CheckCCompilerFlag)
check_c_compiler_flag("-s" CC_SUPPORT_STRIP)
check_c_compiler_flag("-fPIC" CC_SUPPORT_PIC)
check_c_compiler_flag("-fno-delete-null-pointer-checks" CC_SUPPORT_NO_DELETE_NULL_POINTER_CHECKS)

# Redirect the output directorires to the target directories.
if(TARGET_OUTPUT_REDIRECT)
    set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${TARGET_BIN_DIR}$<LOWER_CASE:>")
endif()

if(TARGET_STRIP_ON_RELEASE AND CC_SUPPORT_STRIP)
    if(NOT CMAKE_C_FLAGS_RELEASE MATCHES " -s( |$)")
        # Strip debug info for Release
        set(CMAKE_C_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE} -s" CACHE STRING
            "Flags used by the C compiler during RELEASE builds." FORCE)
        set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -s" CACHE STRING
            "Flags used by the CXX compiler during RELEASE builds." FORCE)
        set(CMAKE_C_FLAGS_MINSIZEREL "${CMAKE_C_FLAGS_MINSIZEREL} -s" CACHE STRING
            "Flags used by the C compiler during MINSIZEREL builds." FORCE)
        set(CMAKE_CXX_FLAGS_MINSIZEREL "${CMAKE_CXX_FLAGS_MINSIZEREL} -s" CACHE STRING
            "Flags used by the CXX compiler during MINSIZEREL builds." FORCE)
    endif()
endif()

if(NOT CMAKE_C_FLAGS_DEBUG MATCHES " ${CC_DEFINE_OPT}_DEBUG( |$)")
    set(CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG} ${CC_DEFINE_OPT}_DEBUG" CACHE STRING
        "Flags used by the C compiler during DEBUG builds." FORCE)
    set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} ${CC_DEFINE_OPT}_DEBUG" CACHE STRING
        "Flags used by the CXX compiler during DEBUG builds." FORCE)
endif()

if(TARGET_CC_PIC AND CC_SUPPORT_PIC)
    add_compile_options("-fPIC")
endif()

if(TARGET_CC_NO_DELETE_NULL_POINTER_CHECKS AND CC_SUPPORT_NO_DELETE_NULL_POINTER_CHECKS)
    add_compile_options("-fno-delete-null-pointer-checks")
endif()

if(TARGET_CC_VISIBILITY_HIDDEN)
    set(CMAKE_C_VISIBILITY_PRESET "hidden")
    set(CMAKE_CXX_VISIBILITY_PRESET "hidden")
    set(CMAKE_ASM_VISIBILITY_PRESET "hidden")
endif()

if(TARGET_MSVC_AFXDLL AND MSVC)
    add_compile_definitions("_AFXDLL")
endif()

if(TARGET_MSVC_UNICODE AND MSVC)
    add_compile_definitions("_UNICODE")
endif()

if(TARGET_MSVC_UTF8 AND MSVC)
    add_compile_options("/utf-8")
endif()

if(TARGET_MSVC_NO_PDB_WARNING AND MSVC)
    # MSVC warning LNK4099: PDB 'vc80.pdb' was not found
    add_link_options("/ignore:4099")
endif()

if(TARGET_PREFIX_INCLUDES)
    include_directories(SYSTEM ${TARGET_PREFIX_INCLUDES})
endif()
if (NOT TARGET_INCLUDE_DIR IN_LIST TARGET_PREFIX_INCLUDES)
    include_directories(SYSTEM "${TARGET_INCLUDE_DIR}")
endif()

link_directories(BEFORE "${CARGO_TARGET_OUT_DIR}")
if (NOT TARGET_LIB_DIR IN_LIST TARGET_PREFIX_LIBS)
    link_directories("${TARGET_LIB_DIR}")
endif()
if(TARGET_PREFIX_LIBS)
    link_directories(${TARGET_PREFIX_LIBS})
endif()

endif()
