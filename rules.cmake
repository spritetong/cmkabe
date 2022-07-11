#** @file       rules.cmake
#*  @brief      This file contains common rules to build cmake targets.
#*  @details    Copyright (C) 2022 spritetong@gmail.com.\n
#*              All rights reserved.\n
#*  @author     spritetong@gmail.com
#*  @date       2014
#*  @version    1.0, 7/9/2022, Tong
#*              - Initial revision.
#**

# Cross compiler
if(TARGET_C_COMPILER)
    execute_process(COMMAND "which" "${TARGET_C_COMPILER}" OUTPUT_VARIABLE PREFIX_ OUTPUT_STRIP_TRAILING_WHITESPACE)
    string(REGEX REPLACE "-[^-]+$" "-" PREFIX_ "${PREFIX_}")

    set(CMAKE_SYSTEM_NAME "Linux" CACHE INTERNAL "")
    set(CMAKE_SYSTEM_PROCESSOR "mipsel" CACHE INTERNAL "")

    set(CMAKE_C_COMPILER "${PREFIX_}gcc" CACHE STRING "" FORCE)
    set(CMAKE_CXX_COMPILER "${PREFIX_}g++" CACHE STRING "" FORCE)
    set(CMAKE_ASM_COMPILER "${PREFIX_}gcc" CACHE STRING "" FORCE)
    set(CMAKE_ASM-ATT_COMPILER "${PREFIX_}as" CACHE STRING "" FORCE)
endif()

if(NOT CMAKE_BUILD_TYPE)
    # Build for Release by default
    set(CMAKE_BUILD_TYPE "Release" CACHE STRING "" FORCE)
endif()

if(NOT DEFINED TARGET_PREFIX)
    set(TARGET_PREFIX "${CMAKE_SOURCE_DIR}")
endif()

if(NOT DEFINED TARGET_COMMON_INCLUDE_DIR)
    set(TARGET_COMMON_INCLUDE_DIR "${TARGET_PREFIX}/include")
endif()

if(NOT DEFINED TARGET_INCLUDE_DIR)
    set(TARGET_INCLUDE_DIR "${TARGET_PREFIX}/${TARGET_TRIPLE}/include")
endif()

if(NOT DEFINED TARGET_LIB_DIR)
    set(TARGET_LIB_DIR "${TARGET_PREFIX}/${TARGET_TRIPLE}/lib")
endif()

if(NOT DEFINED TARGET_BIN_DIR)
    set(TARGET_BIN_DIR "${TARGET_PREFIX}/${TARGET_TRIPLE}/bin")
endif()

if(NOT DEFINED TARGET_OUTPUT_REDIRECT)
    set(TARGET_OUTPUT_REDIRECT ON)
endif()

if(NOT DEFINED TARGET_STRIP_ON_RELEASE)
    set(TARGET_STRIP_ON_RELEASE ON)
endif()

# Redirect the output directorires to the target directories.
if(TARGET_OUTPUT_REDIRECT)
    set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>" CACHE INTERNAL "")
    set(CMAKE_LIBRARY_OUTPUT_DIRECTORY "${TARGET_LIB_DIR}$<LOWER_CASE:>" CACHE INTERNAL "")
    set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${TARGET_BIN_DIR}$<LOWER_CASE:>" CACHE INTERNAL "")
endif()

if(TARGET_STRIP_ON_RELEASE)
    if(UNIX AND NOT(CMAKE_C_FLAGS_RELEASE MATCHES " -s( |$)"))
        # Strip debug info for Release
        SET(CMAKE_C_FLAGS_RELEASE "${CMAKE_C_FLAGS_RELEASE} -s" CACHE STRING "" FORCE)
        SET(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -s" CACHE STRING "" FORCE)
        SET(CMAKE_C_FLAGS_MINSIZEREL "${CMAKE_C_FLAGS_MINSIZEREL} -s" CACHE STRING "" FORCE)
        SET(CMAKE_CXX_FLAGS_MINSIZEREL "${CMAKE_CXX_FLAGS_MINSIZEREL} -s" CACHE STRING "" FORCE)
    endif()
endif()

if(NOT(CMAKE_C_FLAGS_DEBUG MATCHES " -D_DEBUG( |$)"))
    SET(CMAKE_C_FLAGS_DEBUG "${CMAKE_C_FLAGS_DEBUG} -D_DEBUG" CACHE STRING "" FORCE)
    SET(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -D_DEBUG" CACHE STRING "" FORCE)
endif()

include_directories(BEFORE
    SYSTEM "${TARGET_INCLUDE_DIR}"
    SYSTEM "${TARGET_COMMON_INCLUDE_DIR}"
)
link_directories(BEFORE "${TARGET_LIB_DIR}")

# ==============================================================================

# * Search in a directory and add all projects in its child directories.
function(cmkabe_add_subdirs parent_dir)
    file(GLOB node_list "${parent_dir}/*")

    foreach(node ${node_list})
        if(IS_DIRECTORY "${node}")
            foreach(path "${node}" "${node}/mak")
                if(EXISTS "${path}/CMakeLists.txt")
                    add_subdirectory("${path}")
                endif()
            endforeach()
        endif()
    endforeach()
endfunction()
