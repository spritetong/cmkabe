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

# Windows ARCH -> Rust ARCH
_win_arch_table = arm64=aarch64 amd64=x86_64 x64=x86_64 x86=i686 win32=i686
# Rust ARCH -> MSVC ARCH
_msvc_arch_table = aarch64=ARM64 x86_64=x64 i686=Win32
# Rust ARCH -> Android ARCH
_android_arch_table = aarch64=aarch64 armv7=armv7a thumbv7neon=armv7a i686=i686 x86_64=x86_64
# Rust ARCH -> Zig ARCH
_zig_arch_table = aarch64=aarch64 armv7=arm thumbv7neon=thumb i686=x86 x86_64=x86_64

ifeq ($(HOST),Windows)
    _win_arch_ := $(PROCESSOR_ARCHITECTURE)
    ifeq ($(_win_arch_),x86)
        ifneq ($(ProgramW6432),$(ProgramFiles))
            ifneq ($(ProgramW6432),)
               _win_arch_ = x64
            endif
        endif
    endif
    HOST_ARCH := $(call sel,$(call lower,$(_win_arch_)),$(_win_arch_table))
    HOST_TRIPLE := $(HOST_ARCH)-pc-windows-msvc
else
    HOST_ARCH := $(shell uname -m)
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
        override ARCH := $(call sel,$(call lower,$(if $(ARCH),$(ARCH),$(_win_arch_))),\
            $(_win_arch_table),$(ARCH))
        override TARGET := $(ARCH)-windows-msvc
        override TARGET_TRIPLE := $(ARCH)-pc-windows-msvc
    else
        ifeq ($(ARCH),)
            override ARCH := $(HOST_ARCH)
        endif
        ifeq ($(HOST),Darwin)
            override TARGET := $(ARCH)-macos-none
            override TARGET_TRIPLE := $(ARCH)-apple-darwin
        endif
        ifeq ($(HOST),Linux)
            override TARGET := $(ARCH)-linux-gnu
            override TARGET_TRIPLE := $(ARCH)-unknown-linux-gnu
        endif
    endif
else
    override TARGET := $(call lower,$(TARGET))
    ifeq ($(TARGET_TRIPLE),)
        override ARCH := $(firstword $(subst -, ,$(TARGET)))
        _env_ := $(lastword $(subst -, ,$(TARGET)))
        ifeq ($(filter $(ARCH)-pc-windows-% $(ARCH)-unknown-linux-%,$(TARGET)):$(filter msvc gnu musl,$(_env_)),$(TARGET):$(_env_))
            override TARGET_TRIPLE := $(TARGET)
            override TARGET := $(subst -pc-,-,$(subst -unknown-,-,$(TARGET)))
        else ifeq ($(filter i686 x86_64 aarch64,$(ARCH)):$(filter $(ARCH)-windows-% $(ARCH)-linux-%,$(TARGET)):$(filter msvc gnu musl,$(_env_)),$(ARCH):$(TARGET):$(_env_))
            override TARGET_TRIPLE := $(subst -windows-,-pc-windows-,$(subst -linux-,-unknown-linux-,$(TARGET)))
        else
            override TARGET_TRIPLE := $(TARGET)
        endif
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
override ZIG := $(call bool,$(ZIG))

override ARCH := $(firstword $(subst -, ,$(TARGET_TRIPLE)))
override MSVC_ARCH := $(call bsel,$(WINDOWS),$(call sel,$(ARCH),$(_msvc_arch_table)),)
override ANDROID_ARCH := $(call bsel,$(ANDROID),$(call sel,$(ARCH),$(_zig_arch_table)),)
override ZIG_ARCH := $(call bsel,$(ZIG),$(call sel,$(ARCH),$(_zig_arch_table)),$(ARCH))

ifneq ($(filter ON,$(WINDOWS)$(MSVC_ARCH) $(ANDROID)$(ANDROID_ARCH) $(ZIG)$(ZIG_ARCH)),)
    $(error Unknown ARCH: $(ARCH))
endif

endif # __TARGETS_MK__
