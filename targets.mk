# * @file       targets.mk
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

ifndef __TARGETS_MK__
__TARGETS_MK__ = $(abspath $(lastword $(MAKEFILE_LIST)))

# ==============================================================================
# = TARGET(triple), TARGET_TRIPLE(triple), WINDOWS(bool), UNIX(bool)

_win_arch_table = arm64=aarch64 amd64=x86_64 x64=x86_64 x86=i686 win32=i686
ifeq ($(HOST),Windows)
	HOST_ARCH := $(call sel,$(call lower,$(PROCESSOR_ARCHITECTURE)),$(_win_arch_table))
	HOST_TRIPLE := $(HOST_ARCH)-pc-windows-msvc
else
	HOST_ARCH := $(shell uname -p)
	ifeq ($(HOST),Darwin)
		HOST_TRIPLE := $(HOST_ARCH)-apple-darwin
	endif
	ifeq ($(HOST),Linux)
		HOST_TRIPLE := $(HOST_ARCH)-unknown-linux-gnu
	endif
endif

override TARGET := $(filter-out native,$(TARGET))
ifeq ($(TARGET),)
    ifeq ($(HOST),Windows)
        override ARCH := $(call sel,$(call lower,$(if $(ARCH),$(ARCH),$(PROCESSOR_ARCHITECTURE))),\
            $(_win_arch_table),$(ARCH))
        override TARGET := $(ARCH)-pc-windows-msvc
        override TARGET_TRIPLE := $(TARGET)
    else
        ifeq ($(ARCH),)
            override ARCH := $(HOST_ARCH)
        endif
        ifeq ($(HOST),Darwin)
            override TARGET := $(ARCH)-apple-darwin
            override TARGET_TRIPLE := $(TARGET)
        endif
        ifeq ($(HOST),Linux)
            override TARGET := $(ARCH)-unknown-linux-gnu
            override TARGET_TRIPLE := $(TARGET)
        endif
    endif
else
    override TARGET := $(call lower,$(TARGET))
    ifeq ($(TARGET_TRIPLE),)
        override TARGET_TRIPLE := $(TARGET)
    endif
endif

ifeq ($(TARGET),)
    $(error TARGET is not defined)
endif

ifeq ($(TARGET_TRIPLE),)
    $(error TARGET_TRIPLE is not defined)
endif
override TARGET_TRIPLE_UNDERSCORE := $(subst -,_,$(TARGET_TRIPLE))
override TARGET_TRIPLE_UNDERSCORE_UPPER := $(call upper,$(TARGET_TRIPLE_UNDERSCORE))

override WINDOWS := $(if $(findstring -windows,$(TARGET_TRIPLE)),ON,OFF)
override ANDROID := $(if $(findstring -android,$(TARGET_TRIPLE)),ON,OFF)
override UNIX := $(call not,$(WINDOWS))

override ARCH := $(firstword $(subst -, ,$(TARGET_TRIPLE)))
override MSVC_ARCH := $(call bsel,$(WINDOWS),$(call sel,$(ARCH),\
    aarch64=ARM64 x86_64=x64 i686=Win32),)
override ANDROID_ARCH := $(call bsel,$(ANDROID),$(call sel,$(ARCH),\
    aarch64=aarch64 armv7=armv7a i686=i686 x86_64=x86_64),)
override ANROID_TRIPLE := $(ANDROID_ARCH)-linux-$(if $(findstring armv7,$(ANDROID_ARCH)),androideabi,android)

ifneq ($(filter ON,$(WINDOWS)$(MSVC_ARCH) $(ANDROID)$(ANDROID_ARCH)),)
    $(error Unknown ARCH: $(ARCH))
endif

endif # __TARGETS_MK__
