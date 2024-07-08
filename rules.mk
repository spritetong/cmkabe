# * @file       rules.mk
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

ifndef __RULES_MK__
__RULES_MK__ = $(abspath $(lastword $(MAKEFILE_LIST)))
ifeq ($(CMKABE_HOME),)
    include $(dir $(__RULES_MK__))env.mk
endif
include $(CMKABE_HOME)/targets.mk

ifndef WORKSPACE_DIR
    $(warning Please insert to the head of `Makefile` in the workspace directory:)
    $(warning    WORKSPACE_DIR := $$(abspath $$(dir $$(lastword $$(MAKEFILE_LIST)))))
    $(error WORKSPACE_DIR is not defined)
endif

# ==============================================================================
# = Android NDK

#! Android SDK version (API level), defaults to 21.
override ANDROID_SDK_VERSION := \
    $(call either,$(ANDROID_SDK_VERSION),$(call either,$(CMAKE_SYSTEM_VERSION),21))
#! NDK STL: c++_shared, c++_static (default), none, system
ANDROID_STL ?=

# ==============================================================================
# = CMake

override DEBUG := $(call bool,$(DEBUG),ON)
override VERBOSE := $(call bool,$(VERBOSE),OFF)

#! The current configuration of CMake build: Debug, Release
CMAKE_BUILD_TYPE ?= $(call bsel,$(DEBUG),Debug,Release)
#! The CMake system version
CMAKE_SYSTEM_VERSION ?=
#! The root of CMake build directories.
CMAKE_BUILD_ROOT ?= $(WORKSPACE_DIR)/target/cmake
#! The CMake build directory for the current configuration.
CMAKE_BUILD_DIR ?= $(CMAKE_BUILD_ROOT)/$(TARGET_TRIPLE)/$(CMAKE_BUILD_TYPE)
#! The CMake output directory exclude the tailing triple.
CMAKE_TARGET_PREFIX ?= $(CMAKE_BUILD_ROOT)/output
#! The CMake output directory include the tailing triple.
CMAKE_TRPILE_DIR = $(CMAKE_TARGET_PREFIX)/$(TARGET_TRIPLE)
#! The CMake components to be installed.
CMAKE_COMPONENTS ?=
#! The CMake targets (libraries and executables) to be built.
CMAKE_TARGETS +=
#! CMake output directories to be cleaned.
CMAKE_OUTPUT_DIRS +=
#! CMake output file patterns to be cleaned.
CMAKE_OUTPUT_FILE_PATTERNS +=
#! CMake definitions, such as `FOO=bar`
CMAKE_DEFS ?=
#! CMake additional options
CMAKE_OPTS ?=
#! If automatically clean the $(CMAKE_TARGET_PREFIX) directory
CMAKE_AUTO_CLEAN_TARGET ?= ON
#! If set the system path to run output executables 
CMAKE_SET_PATH ?= ON

CMAKE_INIT = cmake -B "$(CMAKE_BUILD_DIR)"
CMAKE_INIT += $(if $(MSVC_ARCH),-A $(MSVC_ARCH),)
CMAKE_INIT += -D "TARGET:STRING=$(TARGET)" -D "TARGET_TRIPLE:STRING=$(TARGET_TRIPLE)"
CMAKE_INIT += -D "CMAKE_BUILD_TYPE:STRING=$(CMAKE_BUILD_TYPE)"
CMAKE_INIT += $(if $(CMAKE_SYSTEM_VERSION),-D "CMAKE_SYSTEM_VERSION:STRING=$(CMAKE_SYSTEM_VERSION)",)
# For Android NDK
ifeq ($(ANDROID),ON)
    ifndef ANDROID_NDK_ROOT
        ANDROID_NDK_ROOT := $(shell $(SHLUTIL) ndk-root)
	else
        override ANDROID_NDK_ROOT := $(subst \,/,$(ANDROID_NDK_ROOT))
    endif
    ifeq ($(ANDROID_NDK_ROOT),)
        $(error `ANDROID_NDK_ROOT` is not defined)
    endif
    export ANDROID_NDK_ROOT
    override CMAKE_SYSTEM_VERSION := $(ANDROID_SDK_VERSION)
    CMAKE_INIT += -GNinja
    CMAKE_INIT += -D "ANDROID_SDK_VERSION:STRING=$(ANDROID_SDK_VERSION)"
    ifneq ($(ANDROID_STL),)
        CMAKE_INIT += -D "ANDROID_STL:STRING=$(ANDROID_STL)"
    endif
else ifeq ($(ZIG),ON)
    ZIG_WRAPPER_DIR ?= $(WORKSPACE_DIR)/target/zig/$(HOST_TRIPLE)
    ZIG_WRAPPER_COMMANDS = $(foreach I,ar cc c++ rc ranlib strip,$(ZIG_WRAPPER_DIR)/zig-$(I)$(EXE_EXT))
    CMAKE_INIT += -GNinja
    CMAKE_INIT += -D "TARGET_C_COMPILER:STRING=$(filter %-cc$(EXE_EXT),$(ZIG_WRAPPER_COMMANDS))"
else
    CMAKE_INIT += -D "CMAKE_VERBOSE_MAKEFILE:BOOL=$(VERBOSE)"
endif
CMAKE_INIT += $(addprefix -D,$(CMAKE_DEFS))

cmake_init = $(CMAKE_INIT) $(CMAKE_INIT_OPTS)
cmake_build = cmake --build "$(CMAKE_BUILD_DIR)" $(addprefix --target ,$(CMAKE_TARGETS)) --config $(CMAKE_BUILD_TYPE) --parallel $(CMAKE_OPTS)
cmake_install = cmake --install "$(CMAKE_BUILD_DIR)" $(addprefix --component ,$(CMAKE_COMPONENTS)) --config $(CMAKE_BUILD_TYPE) $(CMAKE_OPTS)
ifeq ($(if $(filter --prefix,$(CMAKE_OPTS)),1,)$(if $(CMAKE_INSTALL_TARGET_PREFIX),,1),)
    cmake_install += --prefix "$(CMAKE_INSTALL_TARGET_PREFIX)/$(TARGET_TRIPLE)"
endif
cmake_clean = $(call cmake_build) --target clean

# ==============================================================================
# = Cargo

#! Cargo toolchain
CARGO_TOOLCHAIN +=
#! Extra options passed to "cargo build" or "cargo run"
CARGO_OPTS += $(if $(filter $(TARGET_TRIPLE),$(HOST_TRIPLE)),,--target $(TARGET_TRIPLE))
CARGO_OPTS += $(call bsel,$(DEBUG),,--release)
#! Cargo binary crates
CARGO_EXECUTABLES +=
#! Cargo library crates
CARGO_LIBRARIES +=

# cargo_command(<command:str>)
cargo_command = cargo $(CARGO_TOOLCHAIN) $(1) $(CARGO_OPTS)

# cargo_build(<crate:str>,<options:str>)
cargo_build = cargo $(CARGO_TOOLCHAIN) build --bin $(1) $(CARGO_OPTS) $(2)

# cargo_build_lib(<options:str>)
cargo_build_lib = cargo $(CARGO_TOOLCHAIN) build --lib $(CARGO_OPTS) $(1)

# cargo_run(<crate:str>,<options:str>)
cargo_run = cargo $(CARGO_TOOLCHAIN) run --bin $(1) $(CARGO_OPTS) $(2)

# cargo_upgrade(<excludes:str>,<options:str>)
cargo_upgrade = cargo upgrade --incompatible $(1)

# Set crosss compile tools for Rust
# cargo_set_gcc_env_vars()
cargo_set_gcc_env_vars = $(eval $(_cargo_set_gcc_env_vars_tpl_))
define _cargo_set_gcc_env_vars_tpl_
    export CARGO_TARGET_$$(TARGET_TRIPLE_UNDERSCORE_UPPER)_LINKER=$$(TARGET)-gcc
    $$(foreach I,AR=ar CC=gcc CXX=g++ RANLIB=ranlib STRIP=strip,\
        $$(eval export $$(call kv_key,$$I)_$$(TARGET_TRIPLE_UNDERSCORE)=$$(TARGET)-$$(call kv_value,$$I)))
endef

ifeq ($(ANDROID),ON)
    # Set Android NDK environment variables for Rust.
    _exe := $(if $(filter Windows,$(HOST)),.exe,)
    _ndk_bin_dir := $(ANDROID_NDK_ROOT)/toolchains/llvm/prebuilt/$(call lower,$(HOST))-$(HOST_ARCH)/bin
    _ndk_triple := $(ANDROID_ARCH)-linux-$(if $(filter armv7a,$(ANDROID_ARCH)),androideabi,android)
    _ndk_target_opt := --target=$(_ndk_triple)$(ANDROID_SDK_VERSION)
    # LINKER
    export CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_LINKER := $(_ndk_bin_dir)/clang$(EXE_EXT)
    # AR, CC, CXX, RANLIB, STRIP
    export AR_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/llvm-ar$(EXE_EXT)
    export CC_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/clang$(EXE_EXT)
    export CXX_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/clang++$(EXE_EXT)
    export RANLIB_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/llvm-ranlib$(EXE_EXT)
    export STRIP_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/llvm-strip$(EXE_EXT)
    # ARFLAGS, CFLAGS, CXXFLAGS, RANLIBFLAGS, RUSTFLAGS
    override ARFLAGS_$(TARGET_TRIPLE_UNDERSCORE) +=
    export ARFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CFLAGS_$(TARGET_TRIPLE_UNDERSCORE) += $(_ndk_target_opt)
    export CFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CXXFLAGS_$(TARGET_TRIPLE_UNDERSCORE) += $(_ndk_target_opt)
    export CXXFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override RANLIBFLAGS_$(TARGET_TRIPLE_UNDERSCORE) +=
    export RANLIBFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_RUSTFLAGS += $(addprefix -C link-arg=,$(_ndk_target_opt))
    export CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_RUSTFLAGS
    # Check if the NDK CC exists.
    ifeq ($(wildcard $(CC_$(TARGET_TRIPLE_UNDERSCORE))),)
        $(error "$(CC_$(TARGET_TRIPLE_UNDERSCORE))" does not exist)
    endif
else ifeq ($(ZIG),ON)
    # Set Zig environment variables for Rust.
    _zig_abi := $(lastword $(subst -, ,$(TARGET_TRIPLE)))
    _zig_os := $(lastword $(filter-out $(_zig_abi),$(subst -, ,$(TARGET_TRIPLE))))
    ifneq ($(findstring -apple,$(TARGET_TRIPLE)),)
        _zig_os := $(call sel,$(_zig_abi),darwin=macos ios=ios sim=ios,$(_zig_abi))
        _zig_abi = none
    endif
    ZIG_TARGET := $(ZIG_ARCH)-$(_zig_os)-$(_zig_abi)
    export ZIG_WRAPPER_TARGET = $(ZIG_TARGET)
    _zig_target_opt =
    # AR, CC, CXX, RANLIB, STRIP
    export AR_$(TARGET_TRIPLE_UNDERSCORE) := $(ZIG_WRAPPER_DIR)/zig-ar$(EXE_EXT)
    export CC_$(TARGET_TRIPLE_UNDERSCORE) := $(ZIG_WRAPPER_DIR)/zig-cc$(EXE_EXT)
    export CXX_$(TARGET_TRIPLE_UNDERSCORE) := $(ZIG_WRAPPER_DIR)/zig-c++$(EXE_EXT)
    export RANLIB_$(TARGET_TRIPLE_UNDERSCORE) := $(ZIG_WRAPPER_DIR)/zig-ranlib$(EXE_EXT)
    export STRIP_$(TARGET_TRIPLE_UNDERSCORE) := $(ZIG_WRAPPER_DIR)/zig-strip$(EXE_EXT)
    # ARFLAGS, CFLAGS, CXXFLAGS, RANLIBFLAGS, RUSTFLAGS
    override ARFLAGS_$(TARGET_TRIPLE_UNDERSCORE) +=
    export ARFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CFLAGS_$(TARGET_TRIPLE_UNDERSCORE) += $(_zig_target_opt)
    export CFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CXXFLAGS_$(TARGET_TRIPLE_UNDERSCORE) += $(_zig_target_opt)
    export CXXFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override RANLIBFLAGS_$(TARGET_TRIPLE_UNDERSCORE) +=
    export RANLIBFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_RUSTFLAGS += $(addprefix -C link-arg=,$(_zig_target_opt))
    export CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_RUSTFLAGS
else ifeq ($(shell $(TARGET)-gcc -dumpversion >$(NULL) 2>&1 || echo 1),)
    # If the cross compile GCC exists, set the appropriate environment variables for Rust.
    $(call cargo_set_gcc_env_vars)
endif

# Configure the cross compile pkg-config.
ifneq ($(HOST_TRIPLE),$(TARGET_TRIPLE))
    export PKG_CONFIG_ALLOW_CROSS = 1
endif
_k := PKG_CONFIG_PATH_$(TARGET_TRIPLE_UNDERSCORE)
_v := $(CMAKE_TRPILE_DIR)/lib/pkgconfig
ifeq ($(filter $(_v),$(subst $(PS), ,$($(_k)))),)
    export $(_k) := $(_v)$(PS)$($(_k))
endif

# Export environment variables.
export CMAKE_TARGET_PREFIX
export CARGO_WORKSPACE_DIR = $(WORKSPACE_DIR)
ifeq ($(call bool,$(CMAKE_SET_PATH)),ON)
    ifeq ($(HOST):$(findstring windows,$(TARGET_TRIPLE)),Windows:windows)
        export PATH := $(CMAKE_TRPILE_DIR)/bin;$(CMAKE_TRPILE_DIR)/lib;$(PATH)
    else ifeq ($(HOST_TRIPLE),$(TARGET_TRIPLE))
        export PATH := $(CMAKE_TRPILE_DIR)/bin:$(PATH)
        export LD_LIBRARY_PATH := $(CMAKE_TRPILE_DIR)/lib:$(LD_LIBRARY_PATH)
    endif
endif

# Directory of cargo output binaries, as "<workspace_dir>/target/<triple>/<debug|release>"
CARGO_TARGET_OUT_DIR := $(WORKSPACE_DIR)/target/$(if $(filter $(TARGET_TRIPLE),$(HOST_TRIPLE)),,$(TARGET_TRIPLE)/)$(call bsel,$(DEBUG),debug,release)

# Clean the $(CMAKE_TARGET_PREFIX) directory by default.
ifeq ($(call bool,$(CMAKE_AUTO_CLEAN_TARGET)),ON)
    CMAKE_OUTPUT_DIRS += $(CMAKE_TARGET_PREFIX)
endif

# ==============================================================================
# = Rules

_saved_default_goal := $(.DEFAULT_GOAL)

.PHONY: cmake-before-build \
        cmake cmake-init cmake-build cmake-rebuild cmake-install \
        cmake-clean cmake-distclean cmake-clean-root cmake-clean-output \
        cargo-bench cargo-build cargo-check cargo-clean cargo-clippy cargo-lib cargo-test \

cmake: cmake-build

# Do something before building
cmake-before-build:

# Initialize the cmake build directory.
cmake-init $(CMAKE_BUILD_DIR): cmake-before-build
	@$(call cmake_init)

# Build the target 
cmake-build: $(CMAKE_BUILD_DIR)
	@$(call cmake_build)

# Clean the target and rebuild it.
cmake-rebuild: cmake-clean cmake-build

# Install the target.
cmake-install: $(CMAKE_BUILD_DIR)
	@$(call cmake_install)

# Clean the target.
cmake-clean: cmake-clean-output
	@$(call exists,"$(CMAKE_BUILD_DIR)") && $(call cmake_clean) || $(OK)

# Clean the target and erase the build directory.
cmake-distclean: cmake-clean-output
	@$(RM) -rf "$(CMAKE_BUILD_DIR)" || $(OK)

# Clean the root directory of all targets.
cmake-clean-root: cmake-clean-output
	@$(RM) -rf "$(CMAKE_BUILD_ROOT)" || $(OK)

# Clean extra output files.
cmake-clean-output:
	@$(if $(CMAKE_OUTPUT_DIRS),$(call git_remove_ignored,$(CMAKE_OUTPUT_DIRS),$(CMAKE_OUTPUT_FILE_PATTERNS)) || $(OK),$(OK))
	@$(call exists,"$(WORKSPACE_DIR)/CMakeLists.txt") && $(TOUCH) "$(WORKSPACE_DIR)/CMakeLists.txt" || $(OK)

# Cargo command
cargo:
	@$(call cargo_command,$(CARGO_CMD))

# Cargo bench
cargo-bench: cmake-before-build
	@$(call cargo_command,bench)

# Cargo build
cargo-build: cmake-before-build
	@cargo $(CARGO_TOOLCHAIN) build $(CARGO_OPTS)

# Cargo check
cargo-check: cmake-before-build
	@$(call cargo_command,check)

# Clean all Cargo targets
cargo-clean:
	-@cargo clean

# Cargo clippy
cargo-clippy: cmake-before-build
	@$(call cargo_command,clippy)

# Build all Rust libraries
cargo-lib: cmake-before-build
	@$(call cargo_build_lib)

# Cargo test
cargo-test: cmake-before-build
	@$(call cargo_command,test)

# Upgrade dependencies
cargo-upgrade:
	@cargo update
	@$(call cargo_upgrade)

# Execute a shell command
shell:
	$(CMD)

ifeq ($(ZIG),ON)
    .PHONY: zig-init
    cmake-before-build: zig-init
    zig-init: $(ZIG_WRAPPER_COMMANDS)
    $(ZIG_WRAPPER_DIR):
		@$(MKDIR) $(ZIG_WRAPPER_DIR)
    $(ZIG_WRAPPER_DIR)/zig-wrapper$(EXE_EXT): $(CMKABE_HOME)/zig-wrapper.zig $(ZIG_WRAPPER_DIR)
		@zig cc -s -Os -o $@ $<
    $(ZIG_WRAPPER_COMMANDS): $(ZIG_WRAPPER_DIR)/zig-wrapper$(EXE_EXT)
		@$(CP) $< $@
endif

# Disable parallel execution
.NOTPARALLEL:

# Do not change the default goal.
.DEFAULT_GOAL := $(_saved_default_goal)
undefine _saved_default_goal

# Generate common rules for Cargo and CMake.
cargo_cmake_rules = $(eval $(_cargo_cmake_rules_tpl_))
define _cargo_cmake_rules_tpl_
    ifeq ($$(BIN),)
        BIN = $$(call kv_value,$$(firstword $$(CARGO_EXECUTABLES)))
    else
        override BIN := $$(call sel,$$(BIN),$$(CARGO_EXECUTABLES),$$(BIN))
    endif

    .PHONY: build run lib clean clean-cmake upgrade help

    build: cmake-before-build
    ifneq ($$(BIN),)
		@$$(call cargo_build,$$(BIN))
    else
		@$$(call cargo_build_lib)
    endif

    run: cmake-before-build
		@$$(call cargo_run,$$(BIN))

    lib: cargo-lib

    cargo-clean: cmake-clean-output
    clean: cargo-clean
    clean-cmake: cmake-clean-root

    upgrade: cargo-upgrade

    help:
    ifeq ($$(HOST),Windows)
		@cmd /c "$$(CMKABE_HOME)/README.md"
    else
		@$(call less,"$$(CMKABE_HOME)/README.md")
    endif

    $$(foreach I,$$(CARGO_EXECUTABLES),\
        $$(eval $$(call _cargo_build_tpl_,$$(call kv_key,$$I),$$(call kv_value,$$I))))

    $$(foreach I,$$(CARGO_EXECUTABLES),\
        $$(eval $$(call _cargo_run_tpl_,$$(call kv_key,$$I),$$(call kv_value,$$I))))

    $$(foreach I,$$(CARGO_LIBRARIES),\
        $$(eval $$(call _cargo_build_lib_tpl_,$$(call kv_key,$$I),$$(call kv_value,$$I))))
endef
define _cargo_build_tpl_
    ifneq ($(1),$(2))
        .PHONY: $(1)
        $(1): $(2)
    endif
    .PHONY: $(2)
    $(2): cmake-before-build
		@$$(call cargo_build,$(2))
endef
define _cargo_run_tpl_
    ifneq ($(1),$(2))
        .PHONY: run-$(1)
        run-$(1): run-$(2)
    endif
    .PHONY: run-$(2)
    run-$(2): cmake-before-build
		@$$(call cargo_run,$(2))
endef
define _cargo_build_lib_tpl_
    ifneq ($(1),$(2))
        .PHONY: $(1)
        $(1): $(2)
    endif
    .PHONY: $(2)
    $(2): cmake-before-build
		@$$(call cargo_build_lib,-p $(2))
endef

# Download external libraries for CMake.
# cmake_update_libs_rule(
# $(1) Target name, defaults (an empty string) to "update-libs".
#	 target:str=update-libs,
# $(2) Either a URL to the remote source repository or a local path.
#    git_repo_url:str,
# $(3) Path to the local source repository which is used to rebuild the libraries,
#      defaults (an empty string) to "../$(notdir $(basename $(git_repo_url)))".
#    local_repo_dir:str=,
# $(4) Files and directories to be copyed from the source repository to the destination directory.
#    git_sources:list<str>,
# $(5) The destination directory in the local workspace.
#    local_destination_dir:str,
# $(6) The local target file or directory for make, defaults (an empty string) to $(5).
#    local_target_file:str=,
# $(7) The temporary directory.
#    tmp_dir:str=.libs,
# $(8) The Make variable name to determine whether to rebuild the libraries in 
#      the local source repository $(3), leave it empty if you don't want to rebuild.
#    rebuild_var:str=,
# )
cmake_update_libs_rule = $(eval $(call _cmake_update_libs_rule_tpl_,$(call either,$(1),update-libs),$(2),$(3),$(4),$(5),$(6),$(7),$(8)))
define _cmake_update_libs_rule_tpl_
    _saved_default_goal := $(.DEFAULT_GOAL)

    $(1)__target := $(1)
    $(1)__local_repo := $$(call either,$(3),../$$(notdir $$(basename $(2))))
	$(1)__local_file := $$(call either,$(6),$(5))
    $(1)__tmp_dir := $$(call either,$(7),.libs)
    $(1)__rebuild := $$(call bool,$$(if $(8),$$($(8)),))

    cmake-before-build: $$($(1)__local_file)
    .PHONY: $$($(1)__target)
    $$($(1)__target): cmake-clean-output
    $$($(1)__target) $$($(1)__local_file):
		@$$(RM) -rf $$($(1)__tmp_dir)
    ifeq ($$($(1)__rebuild),ON)
		@$$(CD) $$($(1)__local_repo) && make DEBUG=0
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(addprefix $$($(1)__local_repo),$(4)) $(5)/ && $$(FIXLINK) $(5)/
    else ifneq ($$(wildcard $(2)),)
		@echo Copy from "$(2)" ...
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(addprefix $(2)/,$(4)) $(5)/ && $$(FIXLINK) $(5)/
    else
		@git clone --depth 1 --branch master $(2) $$($(1)__tmp_dir)
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(addprefix $$($(1)__tmp_dir)/,$(4)) $(5)/ && $$(FIXLINK) $(5)/
		@$$(RM) -rf $$($(1)__tmp_dir)
    endif

    .DEFAULT_GOAL := $(_saved_default_goal)
    undefine _saved_default_goal
endef

endif # __RULES_MK__
