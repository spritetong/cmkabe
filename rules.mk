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
    #! Insert to the head of Makefile in the workspace directory:
    #!    WORKSPACE_DIR := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
    $(error WORKSPACE_DIR is not defined)
endif

# ==============================================================================
# = CMake

override DEBUG := $(call bool,$(DEBUG),ON)
override VERBOSE := $(call bool,$(VERBOSE),OFF)

#! The current configuration of CMake build.
CMAKE_BUILD_TYPE ?= $(call bsel,$(DEBUG),Debug,Release)
#! The root of CMake build directories.
CMAKE_BUILD_ROOT ?= $(WORKSPACE_DIR)/target/cmake
#! The CMake build directory for the current configuration.
CMAKE_BUILD_DIR ?= $(CMAKE_BUILD_ROOT)/$(TARGET_TRIPLE)/$(CMAKE_BUILD_TYPE)
#! The CMake output directory exclude the tailing triple.
CMAKE_TARGET_PREFIX ?= $(WORKSPACE_DIR)
#! The CMake targets (libraries and executables) to build.
CMAKE_TARGETS +=
#! CMake output directories to clean.
CMAKE_OUTPUT_DIRS +=
#! CMake output file patterns to clean.
CMAKE_OUTPUT_FILE_PATTERNS +=

CMAKE_INIT = cmake -B "$(CMAKE_BUILD_DIR)"
CMAKE_INIT += $(if $(MSVC_ARCH),-A $(MSVC_ARCH),)
CMAKE_INIT += -D "TARGET:STRING=$(TARGET)" -D "TARGET_TRIPLE:STRING=$(TARGET_TRIPLE)"
CMAKE_INIT += -D "CMAKE_BUILD_TYPE:STRING=$(CMAKE_BUILD_TYPE)"
CMAKE_INIT += -D "CMAKE_VERBOSE_MAKEFILE:BOOL=$(VERBOSE)"
CMAKE_INIT += $(foreach I,$(CMAKE_DEFS), -D$I)

# FIXME: repeat 3 times to work around the cache problem of cross compilation on Linux.
cmake_init = $(CMAKE_INIT) $(CMAKE_INIT_OPTS)
cmake_build = cmake --build "$(CMAKE_BUILD_DIR)"$(foreach I,$(CMAKE_TARGETS), --target $I) --config $(CMAKE_BUILD_TYPE) --parallel $(CMAKE_OPTS)
cmake_install = cmake --install "$(CMAKE_BUILD_DIR)" --config $(CMAKE_BUILD_TYPE) $(CMAKE_OPTS)
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

#! Anroid SDK version
ANROID_SDK_VERSION ?= 23

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
    ifeq ($(ANDROID_NDK_ROOT),)
        $(error `ANDROID_NDK_ROOT` is not defined)
    endif
    _exe := $(if $(filter Windows,$(HOST)),.exe,)
    _ndk_bin_dir := $(ANDROID_NDK_ROOT)/toolchains/llvm/prebuilt/$(call lower,$(HOST))-$(HOST_ARCH)/bin
    _ndk_target_opt := --target=$(ANROID_TRIPLE)$(ANROID_SDK_VERSION)
    # LINKER
    export CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_LINKER := $(_ndk_bin_dir)/clang$(_exe)
    # AR, CC, CXX, RANLIB, STRIP
    export AR_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/llvm-ar$(_exe)
    export CC_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/clang$(_exe)
    export CXX_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/clang++$(_exe)
    export RANLIB_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/llvm-ranlib$(_exe)
    export STRIP_$(TARGET_TRIPLE_UNDERSCORE) := $(_ndk_bin_dir)/llvm-strip$(_exe)
    # CFLAGS, CXXFLAGS, RUSTFLAGS
    override CFLAGS_$(TARGET_TRIPLE_UNDERSCORE) += $(_ndk_target_opt)
    export CFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CXXFLAGS_$(TARGET_TRIPLE_UNDERSCORE) += $(_ndk_target_opt)
    export CXXFLAGS_$(TARGET_TRIPLE_UNDERSCORE)
    override CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_RUSTFLAGS += -C link-arg=$(_ndk_target_opt)
    export CARGO_TARGET_$(TARGET_TRIPLE_UNDERSCORE_UPPER)_RUSTFLAGS
    # Check if the NDK CC exists.
    ifeq ($(wildcard $(CC_$(TARGET_TRIPLE_UNDERSCORE))),)
        $(error "$(CC_$(TARGET_TRIPLE_UNDERSCORE))" does not exist)
    endif
else ifeq ($(shell $(TARGET)-gcc -dumpversion >$(NULL) 2>&1 || echo 1),)
    # If the cross compile GCC exists, set the appropriate environment variables for Rust.
    $(call cargo_set_gcc_env_vars)
endif

# Configure the cross compile pkg-config.
ifneq ($(HOST_TRIPLE),$(TARGET_TRIPLE))
    export PKG_CONFIG_ALLOW_CROSS = 1
endif
_k := PKG_CONFIG_PATH_$(TARGET_TRIPLE_UNDERSCORE)
_v := $(CMAKE_TARGET_PREFIX)/$(TARGET_TRIPLE)/lib/pkgconfig
ifeq ($(filter $(_v),$(subst $(PS), ,$($(_k)))),)
    export $(_k) := $(_v)$(PS)$($(_k))
endif

# Export environment variables.
export CMAKE_TARGET_PREFIX
export CARGO_WORKSPACE_DIR = $(WORKSPACE_DIR)

# Directory of cargo output binaries, as "<workspace_dir>/target/<triple>/<debug|release>"
CARGO_TARGET_OUT_DIR := $(WORKSPACE_DIR)/target/$(if $(filter $(TARGET_TRIPLE),$(HOST_TRIPLE)),,$(TARGET_TRIPLE)/)$(call bsel,$(DEBUG),debug,release)

# ==============================================================================
# = Rules

_saved_default_goal := $(.DEFAULT_GOAL)

.PHONY: before-build \
        cmake cmake-init cmake-build cmake-rebuild cmake-install \
        cmake-clean cmake-distclean cmake-clean-root cmake-clean-output \
        cargo-bench cargo-build cargo-check cargo-clean cargo-clippy cargo-lib cargo-test \

cmake: cmake-build

# Do something before building
before-build:

# Initialize the cmake build directory.
cmake-init $(CMAKE_BUILD_DIR): before-build
	@$(call cmake_init)

# Build the target 
cmake-build: $(CMAKE_BUILD_DIR)
	@$(call cmake_build)

# Clean the target and rebuild it.
cmake-rebuild: cmake-clean cmake-build

# Install the target.
cmake-install:
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
cargo-bench: before-build
	@$(call cargo_command,bench)

# Cargo build
cargo-build: before-build
	@cargo $(CARGO_TOOLCHAIN) build $(CARGO_OPTS)

# Cargo check
cargo-check: before-build
	@$(call cargo_command,check)

# Clean all Cargo targets
cargo-clean:
	-@cargo clean

# Cargo clippy
cargo-clippy: before-build
	@$(call cargo_command,clippy)

# Build all Rust libraries
cargo-lib: before-build
	@$(call cargo_build_lib)

# Cargo test
cargo-test: before-build
	@$(call cargo_command,test)

# Upgrade dependencies
cargo-upgrade:
	@cargo update
	@$(call cargo_upgrade)

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

    build: before-build
		@$$(call cargo_build,$$(BIN))

    run: before-build
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
    $(2): before-build
		@$$(call cargo_build,$(2))
endef
define _cargo_run_tpl_
    ifneq ($(1),$(2))
        .PHONY: run-$(1)
        run-$(1): run-$(2)
    endif
    .PHONY: run-$(2)
    run-$(2): before-build
		@$$(call cargo_run,$(2))
endef
define _cargo_build_lib_tpl_
    ifneq ($(1),$(2))
        .PHONY: $(1)
        $(1): $(2)
    endif
    .PHONY: $(2)
    $(2): before-build
		@$$(call cargo_build_lib,-p $(2))
endef

# Download external libraries for CMake
# cmake_update_libs_rule(target:str=update-libs,git_path_url:str,local_repo_dir:str=,git_sources:str,
#    local_destination_dir:str,local_target_file:str=,tmp_dir:str=.libs,rebuild_flag:bool=)
cmake_update_libs_rule = $(eval $(call _cmake_update_libs_rule_tpl_,$(1),$(2),$(3),$(4),$(5),$(6),$(7),$(8)))
define _cmake_update_libs_rule_tpl_
    $(1)__target := $$(if $(1),$(1),update-libs)
    $(1)__local_repo := $$(if $(3),$(3),../$$(notdir $$(basename $(2))))
	$(1)__local_file := $$(if $(6),$(6),$(5))
    $(1)__tmp_dir := $$(if $(7),$(7),.libs)
    $(1)__rebuild := $$(if $(8),$$($(8)),OFF)

    before-build: $$($(1)__local_file)
    .PHONY: $$($(1)__target)
    $$($(1)__target): cmake-clean-output
    $$($(1)__target) $$($(1)__local_file):
		@$$(RM) -rf $$($(1)__tmp_dir)
    ifeq ($$(call bool,$$($(1)__rebuild)),OFF)
		@git clone --depth 1 --branch master $(2) $$($(1)__tmp_dir)
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(foreach I,$(4),$$($(1)__tmp_dir)/$$I) $(5)/ && $$(FIXLINK) $(5)/
		@$$(RM) -rf $$($(1)__tmp_dir)
    else
		@$$(CD) $$($(1)__local_repo) && make DEBUG=0 && $$(CD) $$(WORKSPACE_DIR)
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(foreach I,$(4),$$($(1)__local_repo)/$$I) $(5)/ && $$(FIXLINK) $(5)/
    endif
endef

endif # __RULES_MK__
