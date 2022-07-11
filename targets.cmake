#** @file       targets.cmake
#*  @brief      This file contains target triple definitions to build cmake targets.
#*  @details    Copyright (C) 2022 spritetong@gmail.com.\n
#*              All rights reserved.\n
#*  @author     spritetong@gmail.com
#*  @date       2014
#*  @version    1.0, 7/9/2022, Tong
#*              - Initial revision.
#**

# TARGET, TARGET_TRIPLE
if(NOT ("${TARGET}" MATCHES "^(|native)$"))
    # pass
elseif(WIN32 AND (CMAKE_SYSTEM_PROCESSOR STREQUAL "AMD64"))
    set(TARGET "x86_64-pc-windows-msvc")
    set(TARGET_TRIPLE "${TARGET}")
elseif(UNIX AND (CMAKE_SYSTEM_PROCESSOR STREQUAL "x86_64"))
    set(TARGET "${CMAKE_SYSTEM_PROCESSOR}-unknown-linux-gnu")
    set(TARGET_TRIPLE "${TARGET}")
else()
    message(FATAL_ERROR "Can not build for: ${CMAKE_SYSTEM_NAME}")
endif()

set(TARGET "${TARGET}" CACHE STRING "Target triple with a specified vendor." FORCE)
set(TARGET_TRIPLE "${TARGET_TRIPLE}" CACHE STRING "Target triple maybe with an unknown vendor." FORCE)
