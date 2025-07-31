# * @file       rules.mk
# * @brief      This file contains common rules to build cmake targets.
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

ifndef __RULES_MK__
__RULES_MK__ = $(abspath $(lastword $(MAKEFILE_LIST)))

ifeq ($(CMKABE_HOME),)
    include $(dir $(__RULES_MK__))env.mk
endif

ifndef WORKSPACE_DIR
    $(warning Please insert to the head of `Makefile` in the workspace directory:)
    $(warning    WORKSPACE_DIR := $$(abspath $$(dir $$(lastword $$(MAKEFILE_LIST)))))
    $(error WORKSPACE_DIR is not defined)
endif

_x_saved_default_goal := $(.DEFAULT_GOAL)

# ==============================================================================
# = CMake build type

#! Debug mode
override DEBUG := $(call bool,$(DEBUG),ON)
#! Generate with minimum size
override MINSIZE := $(call bool,$(MINSIZE),OFF)
#! Generate debug information
override DBGINFO := $(call bool,$(DBGINFO),$(call bsel,$(DEBUG),ON,OFF))
#! Show verbose output
override VERBOSE := $(call bool,$(VERBOSE),OFF)

# The current configuration of CMake build: Debug, Release, RelWithDebInfo or MinSizeRel.
ifeq ($(DEBUG),ON)
    override CMAKE_BUILD_TYPE = Debug
else ifeq ($(MINSIZE),ON)
    override CMAKE_BUILD_TYPE = MinSizeRel
else ifeq ($(DBGINFO),ON)
    override CMAKE_BUILD_TYPE = RelWithDebInfo
else
    override CMAKE_BUILD_TYPE = Release
endif

# ==============================================================================
# = Compiler Flags

#! `ar` flags
TARGET_ARFLAGS +=
#! `cc` flags
TARGET_CFLAGS +=
#! `c++` flags
TARGET_CXXFLAGS +=
#! `ranlib` flags
TARGET_RANLIBFLAGS +=
#! `rust` flags
TARGET_RUSTFLAGS +=

# ==============================================================================
# Target definitions

#! Target triple or `native` for the current system
override TARGET := $(strip $(TARGET))
#! Default value of `CARGO_TARGET_DIR`
TARGET_DIR ?= $(WORKSPACE_DIR)/target
#! The root of CMake build directories.
TARGET_CMAKE_DIR ?= $(TARGET_DIR)/.cmake

# ==============================================================================
# Build target dependencies and apply.
cmake_build_target_deps = $(SHLUTIL) build_target_deps \
    WORKSPACE_DIR=$(WORKSPACE_DIR) \
    TARGET=$(CMKABE_TARGET) \
    TARGET_DIR=$(TARGET_DIR) \
    TARGET_CMAKE_DIR=$(TARGET_CMAKE_DIR) \
    CMAKE_TARGET_PREFIX=$(CMAKE_TARGET_PREFIX) \
    TARGET_CC=$(TARGET_CC) \
    CARGO_TARGET=$(CARGO_TARGET) \
    ZIG_TARGET=$(ZIG_TARGET)
ifneq ($(filter clean,$(MAKECMDGOALS)),)
    cmake_build_target_deps += MAKE_CLEAN=ON
endif

# include .host.mk
_X_DOT_HOST_MK = $(TARGET_CMAKE_DIR)/$(HOST_SYSTEM)/.host.mk
_X_CMAKE_TARGET_DEPS_BUILT = OFF
ifneq ($(filter cmake-init,$(if $(wildcard $(_X_DOT_HOST_MK)),,cmake-init) $(MAKECMDGOALS)),)
    ifneq ($(shell $(cmake_build_target_deps) >$(NULL) || echo 1),)
        $(error Failed to build target: $(TARGET))
    endif
    _X_CMAKE_TARGET_DEPS_BUILT = ON
endif
include $(_X_DOT_HOST_MK)

_X_DOT_TARGET_DIR := $(TARGET_CMAKE_DIR)/$(HOST_SYSTEM)/$(if $(filter-out native,$(TARGET)),$(TARGET),native)
_X_DOT_SETTINGS_MK = $(_X_DOT_TARGET_DIR)/.settings.mk
_X_DOT_ENVIRON_MK = $(_X_DOT_TARGET_DIR)/.environ.mk

# Auto rebuild dependencies.
ifneq ($(_X_CMAKE_TARGET_DEPS_BUILT),ON)
    $(_X_DOT_SETTINGS_MK): $(addprefix $(CMKABE_HOME)/,shlutilib.py zig-wrapper.zig)
		@$(cmake_build_target_deps)
endif

# include .settings.mk
ifeq ($(wildcard $(_X_DOT_SETTINGS_MK)),)
    ifneq ($(shell $(cmake_build_target_deps) >$(NULL) || echo 1),)
        $(error Failed to build target: $(TARGET))
    endif
endif
include $(_X_DOT_SETTINGS_MK)
ifeq ($(CMAKE_TARGET_DIR),)
    $(error Can not parse target: $(TARGET))
endif

# ==============================================================================
# = CMake

#! Triple of Zig target
ZIG_TARGET ?=
#! `<workspace directory>/target`
TARGET_DIR ?=
#! CC compiler for the target
TARGET_CC ?=

# The CMake output directory include the tailing triple.
CMAKE_PREFIX_DIR ?= $(CMAKE_TARGET_PREFIX)/$(TARGET)
CMAKE_PREFIX_SUBDIRS ?= $(CMAKE_PREFIX_DIR)
CMAKE_INSTALL_TARGET_PREFIX ?= $(CMAKE_TARGET_PREFIX)
# The CMake build directory for the current configuration.
CMAKE_BUILD_DIR ?= $(CMAKE_TARGET_DIR)/$(CMAKE_BUILD_TYPE)

#! The CMake system version
CMAKE_SYSTEM_VERSION ?=
#! The CMake output directory exclude the tailing triple.
CMAKE_TARGET_PREFIX ?= $(WORKSPACE_DIR)/installed
#! The CMake components to be installed.
CMAKE_COMPONENTS +=
#! The CMake targets (libraries and executables) to be built.
CMAKE_TARGETS +=
#! CMake output directories to be cleaned.
CMAKE_OUTPUT_DIRS +=
#! CMake output file patterns to be cleaned.
CMAKE_OUTPUT_FILE_PATTERNS +=
#! CMake definitions, such as `FOO=bar`
CMAKE_DEFS +=
#! CMake initialization options
CMAKE_INIT_OPTS +=
#! CMake additional options
CMAKE_OPTS +=
#! If automatically clean the $(CMAKE_TARGET_PREFIX) directory
CMAKE_AUTO_CLEAN_TARGET ?= ON

_X_CMAKE_INIT = cmake --toolchain "$(CMKABE_HOME)/toolchain.cmake" -B "$(CMAKE_BUILD_DIR)"
_X_CMAKE_INIT += $(if $(CMAKE_GENERATOR),-G "$(CMAKE_GENERATOR)",)
_X_CMAKE_INIT += -D "TARGET:STRING=$(CMKABE_TARGET)"
_X_CMAKE_INIT += -D "TARGET_DIR:FILEPATH=$(TARGET_DIR)"
_X_CMAKE_INIT += -D "TARGET_CMAKE_DIR:FILEPATH=$(TARGET_CMAKE_DIR)"
# _X_CMAKE_INIT += -D "TARGET_PREFIX:FILEPATH=$(CMAKE_TARGET_PREFIX)"
# _X_CMAKE_INIT += -D "TARGET_CC:STRING=$(TARGET_CC)"
# _X_CMAKE_INIT += -D "CARGO_TARGET:STRING=$(CARGO_TARGET)"
# _X_CMAKE_INIT += -D "ZIG_TARGET:STRING=$(ZIG_TARGET)"
_X_CMAKE_INIT += -D "CMAKE_BUILD_TYPE:STRING=$(CMAKE_BUILD_TYPE)"
_X_CMAKE_INIT += -D "CMAKE_VERBOSE_MAKEFILE:BOOL=$(VERBOSE)"
_X_CMAKE_INIT += $(if $(CMAKE_SYSTEM_VERSION),-D "CMAKE_SYSTEM_VERSION:STRING=$(CMAKE_SYSTEM_VERSION)",)
_X_CMAKE_INIT += $(if $(TARGET_CC),-D "TARGET_CC:STRING=$(TARGET_CC)",)
ifeq ($(TARGET_IS_ANDROID),ON)
    _X_CMAKE_INIT += -D "ANDROID_SDK_VERSION:STRING=$(ANDROID_SDK_VERSION)"
    _X_CMAKE_INIT += $(if $(ANDROID_ARM_MODE),-D "ANDROID_ARM_MODE:STRING=$(call bool,$(ANDROID_ARM_MODE))",)
    _X_CMAKE_INIT += $(if $(ANDROID_ARM_NEON),-D "ANDROID_ARM_NEON:BOOL=$(ANDROID_ARM_NEON)",)
    _X_CMAKE_INIT += $(if $(ANDROID_STL),-D "ANDROID_STL:STRING=$(ANDROID_STL)",)
endif
_X_CMAKE_INIT += $(addprefix -D,$(CMAKE_DEFS))

CMAKE_BUILD_DEPS += $(CMAKE_BUILD_DIR)
CMAKE_CLEAN_DEPS += cmake-clean-output

# cmake_init()
cmake_init = $(_X_CMAKE_INIT) $(CMAKE_INIT_OPTS)

# cmake_build(<targets:list<str>>)
cmake_build = cmake --build "$(CMAKE_BUILD_DIR)" \
    $(addprefix --target ,$(if $(1),$(1),$(subst ;,$(SPACE),$(CMAKE_TARGETS)))) \
    --config $(CMAKE_BUILD_TYPE) --parallel $(CMAKE_OPTS)

# cmake_install(<components:list<str>>,<install_target_prefix:str>)
cmake_install = cmake --install "$(CMAKE_BUILD_DIR)" \
    $(addprefix --component ,$(if $(1),$(1),$(subst ;,$(SPACE),$(CMAKE_COMPONENTS)))) \
    --config $(CMAKE_BUILD_TYPE) \
    --prefix "$(if $(2),$(2),$(CMAKE_INSTALL_TARGET_PREFIX))/$(TARGET)" $(CMAKE_OPTS)

# cmake_clean()
cmake_clean = $(call cmake_build) --target clean

# ==============================================================================
# = Android NDK

#! Android SDK version (API level), defaults to 24.
ANDROID_SDK_VERSION ?= 24
#! Specifies whether to generate arm or thumb instructions for armeabi-v7a: arm, thumb
ANDROID_ARM_MODE ?=
#! Enables or disables NEON for armeabi-v7a: ON, OFF
ANDROID_ARM_NEON ?=
#! NDK STL: c++_shared, c++_static (default), none, system
ANDROID_STL ?=

# ==============================================================================
# = Cargo

#! Triple of Cargo target
CARGO_TARGET ?=
#! Cargo toolchain
CARGO_TOOLCHAIN +=
#! Extra options passed to "cargo build" or "cargo run"
CARGO_OPTS +=
#! Arguments passed "cargo run", "cargo test" or "cargo bench"
CARGO_RUN_ARGS ?= $(ARGS)
#! Cargo binary crates
CARGO_EXECUTABLES +=
#! Cargo library crates
CARGO_LIBRARIES +=

_X_CARGO_OPTS = $(if $(filter $(HOST_CARGO_TARGET),$(CARGO_TARGET)),,--target $(CARGO_TARGET))
_X_CARGO_OPTS += $(call bsel,$(DEBUG),,--release)
_X_CARGO_OPTS += --target-dir $(CARGO_TARGET_DIR)
_X_CARGO_OPTS += $(CARGO_OPTS)
_X_CARGO_RUN_ARGS = $(if $(CARGO_RUN_ARGS),-- $(CARGO_RUN_ARGS),)

# cargo_command(<command:str>)
cargo_command = cargo $(CARGO_TOOLCHAIN) $(1) $(_X_CARGO_OPTS)

# cargo_build(<crate:str>,<options:str>)
cargo_build = cargo $(CARGO_TOOLCHAIN) build --bin $(1) $(_X_CARGO_OPTS) $(2)

# cargo_build_lib(<options:str>)
cargo_build_lib = cargo $(CARGO_TOOLCHAIN) build --lib $(_X_CARGO_OPTS) $(1)

# cargo_run(<crate:str>,<options:str>)
cargo_run = cargo $(CARGO_TOOLCHAIN) run --bin $(1) $(_X_CARGO_OPTS) $(2) $(_X_CARGO_RUN_ARGS)

# cargo_upgrade(<excludes:str>,<options:str>)
cargo_upgrade = cargo upgrade --incompatible $(1)

# Set crosss compile tools for Rust
$(call cmkabe_update_toolchain)

# Directory of Cargo output binaries, normally is "<workspace_dir>/target/<triple>/<debug|release>"
CARGO_OUT_DIR ?=

# Clean the $(CMAKE_TARGET_PREFIX) directory by default.
ifeq ($(call bool,$(CMAKE_AUTO_CLEAN_TARGET)),ON)
    CMAKE_OUTPUT_DIRS += $(CMAKE_TARGET_PREFIX)
endif

# ==============================================================================
# = Rules

.PHONY: cmake
cmake: cmake-build

# Do something before building
.PHONY: cmake-before-build
cmake-before-build:

# Initialize the cmake build directory.
.PHONY: cmake-init
cmake-init $(CMAKE_BUILD_DIR): cmake-before-build
	@$(call cmake_init)

# Build the target
.PHONY: cmake-build
cmake-build: $(CMAKE_BUILD_DEPS)
	@$(call cmake_build)

# Clean the target and rebuild it.
.PHONY: cmake-rebuild
cmake-rebuild: cmake-clean cmake-build

# Install the target.
.PHONY: cmake-install
cmake-install: $(CMAKE_BUILD_DEPS)
	@$(call cmake_install)

# Clean the target.
.PHONY: cmake-clean
cmake-clean: $(CMAKE_CLEAN_DEPS)
	@$(call exists,"$(CMAKE_BUILD_DIR)") && $(call cmake_clean) || $(OK)

# Clean the target and erase the build directory.
.PHONY: cmake-distclean
cmake-distclean: $(CMAKE_CLEAN_DEPS)
	@$(RM) -rf "$(CMAKE_BUILD_DIR)" || $(OK)

# Clean the root directory of all targets.
.PHONY: cmake-clean-root
cmake-clean-root: $(CMAKE_CLEAN_DEPS)
	@$(RM) -rf "$(TARGET_CMAKE_DIR)" "$(TARGET_DIR)/.zig" || $(OK)

# Clean extra output files.
.PHONY: cmake-clean-output
cmake-clean-output:
	@$(if $(CMAKE_OUTPUT_DIRS),$(call git_remove_ignored,$(CMAKE_OUTPUT_DIRS),$(CMAKE_OUTPUT_FILE_PATTERNS)) || $(OK),$(OK))
	@$(RM) -rf $(CMAKE_OUTPUT_FILES) "$(WORKSPACE_DIR)/-" || $(OK)
	@$(call exists,"$(WORKSPACE_DIR)/CMakeLists.txt") && $(TOUCH) "$(WORKSPACE_DIR)/CMakeLists.txt" || $(OK)

# Cargo command
.PHONY: cargo
cargo:
	@$(call cargo_command,$(CARGO_CMD)) $(_X_CARGO_RUN_ARGS)

# Cargo bench
.PHONY: cargo-bench
cargo-bench: cmake-before-build
	@$(call cargo_command,bench) $(_X_CARGO_RUN_ARGS)

# Cargo build
.PHONY: cargo-build
cargo-build: cmake-before-build
	@cargo $(CARGO_TOOLCHAIN) build $(_X_CARGO_OPTS)

# Cargo check
.PHONY: cargo-check
cargo-check: cmake-before-build
	@$(call cargo_command,check)

# Clean all Cargo targets
.PHONY: cargo-clean
cargo-clean:
	-@cargo clean
	@$(RM) -rf "$(TARGET_DIR)" || $(OK)

# Cargo clippy
.PHONY: cargo-clippy
cargo-clippy: cmake-before-build
	@$(call cargo_command,clippy)

# Build all Rust libraries
.PHONY: cargo-lib
cargo-lib: cmake-before-build
	@$(call cargo_build_lib)

# Cargo test
.PHONY: cargo-test
cargo-test: cmake-before-build
	@$(call cargo_command,test) $(_X_CARGO_RUN_ARGS)

# Upgrade dependencies
.PHONY: cargo-upgrade
cargo-upgrade:
	@cargo update
	@$(call cargo_upgrade)

# Patch Zig source files
.PHONY: zig-patch
zig-patch:
	@$(SHLUTIL) zig_patch

# Clean Zig cache
.PHONY: zig-clean-cache
zig-clean-cache:
	@$(SHLUTIL) zig_clean_cache || $(OK)
	@$(RM) -rf "$(TARGET_DIR)/.zig" || $(OK)
	@$(cmake_build_target_deps)

# Execute a shell command
.PHONY: shell
shell:
    ifeq ($(HOST_SYSTEM),Windows)
		-@cmd.exe /k set PROMPT=(make) %PROMPT%
    else
		-@bash --norc
    endif

# Show target information
.PHONY: target
target:
	@echo "TARGET:                      $(TARGET)"
	@echo "CARGO_TARGET:                $(CARGO_TARGET)"
	@echo "TARGET_CC:                   $(TARGET_CC)"
	@echo "CMAKE_BUILD_TYPE:            $(CMAKE_BUILD_TYPE)"
	@echo "WORKSPACE_DIR:               $(WORKSPACE_DIR)"
	@echo "TARGET_DIR:                  $(TARGET_DIR)"
	@echo "TARGET_CMAKE_DIR:            $(TARGET_CMAKE_DIR)"
	@echo "CMAKE_BUILD_DIR:             $(CMAKE_BUILD_DIR)"
	@echo "CMAKE_INSTALL_TARGET_PREFIX: $(CMAKE_INSTALL_TARGET_PREFIX)"
	@echo "CMAKE_TARGET_PREFIX:         $(CMAKE_TARGET_PREFIX)"
	@echo "CMAKE_PREFIX_DIR:            $(CMAKE_PREFIX_DIR)"
	@echo "CARGO_OUT_DIR:               $(CARGO_OUT_DIR)"


# Disable parallel execution
.NOTPARALLEL:

# Do not change the default goal.
.DEFAULT_GOAL := $(_x_saved_default_goal)
undefine _x_saved_default_goal

# Generate common rules for Cargo and CMake.
cmkabe_cargo_rules = $(eval $(_x_cmkabe_cargo_rules_tpl))
define _x_cmkabe_cargo_rules_tpl
    ifeq ($$(BIN),)
        BIN = $$(call kv_value,$$(firstword $$(CARGO_EXECUTABLES)))
    else
        override BIN := $$(call sel,$$(BIN),$$(CARGO_EXECUTABLES),$$(BIN))
    endif

    .PHONY: build
    build: cmake-before-build
    ifneq ($$(BIN),)
		@$$(call cargo_build,$$(BIN))
    else
		@$$(call cargo_build_lib)
    endif

    .PHONY: run
    run: cmake-before-build
		@$$(call cargo_run,$$(BIN))

    .PHONY: lib
    lib: cargo-lib

    .PHONY: clean clean-cmake
    cargo-clean: $$(CMAKE_CLEAN_DEPS)
    clean: cargo-clean
    clean-cmake: cmake-clean-root

    .PHONY: help
    help:
    ifeq ($$(HOST_SYSTEM),Windows)
		@cmd.exe /c "$$(CMKABE_HOME)/README.md"
    else
		@$(call less,"$$(CMKABE_HOME)/README.md")
    endif

    $$(foreach I,$$(CARGO_EXECUTABLES),\
        $$(eval $$(call _x_cargo_build_tpl,$$(call kv_key,$$I),$$(call kv_value,$$I))))

    $$(foreach I,$$(CARGO_EXECUTABLES),\
        $$(eval $$(call _x_cargo_run_tpl,$$(call kv_key,$$I),$$(call kv_value,$$I))))

    $$(foreach I,$$(CARGO_LIBRARIES),\
        $$(eval $$(call _x_cargo_build_lib_tpl,$$(call kv_key,$$I),$$(call kv_value,$$I))))
endef
define _x_cargo_build_tpl
    ifneq ($(1),$(2))
        .PHONY: $(1)
        $(1): $(2)
    endif
    .PHONY: $(2)
    $(2): cmake-before-build
		@$$(call cargo_build,$(2))
endef
define _x_cargo_run_tpl
    ifneq ($(1),$(2))
        .PHONY: run-$(1)
        run-$(1): run-$(2)
    endif
    .PHONY: run-$(2)
    run-$(2): cmake-before-build
		@$$(call cargo_run,$(2))
endef
define _x_cargo_build_lib_tpl
    ifneq ($(1),$(2))
        .PHONY: $(1)
        $(1): $(2)
    endif
    .PHONY: $(2)
    $(2): cmake-before-build
		@$$(call cargo_build_lib,-p $(2))
endef

# Download external libraries for CMake.
# cmkabe_update_libs(
# NAME=<make_target_name:str>
#    Target name, defaults (an empty string) to "update-libs".
# URL=<git_repo_url:str>
#    Either a URL to the remote source repository or a local path.
# LOCAL_REPO=<local_repo_dir:str>
#    Path to the local source repository which is used to rebuild the libraries,
#    defaults (an empty string) to "../$(notdir $(basename $(git_repo_url)))".
# FILES=<git_source_files:list<str>>
#    Files (and directories) to be copyed from the source repository to the destination directory.
# DEST_DIR=<local_destination_dir:str>
#    The destination directory in the local workspace.
# TARGET_FILE=<local_target_file:str>
#    The local target file or directory for make, defaults (an empty string) to `<DEST_DIR>`.
# TMP_DIR=<tmp_dir:str>
#    The temporary directory, defaults to `.libs`
# REBUILD=<rebuild_var_name:str>
#    The Make variable name to determine whether to rebuild the libraries in 
#    the local source repository `<LOCAL_REPO>`, leave it empty if you don't want to rebuild.
# )
cmkabe_update_libs = $(eval $(call _x_cmkabe_update_libs_tpl,$(call sel,NAME,$(word 1,$(1)),update-libs),$(1)))
_x_cmkabe_update_lib_cp = $(OK) $(foreach I,$(3),&& $(MKDIR) $(2)/$(word 2,$(subst :, ,$I)) && \
	$(CP) -rfP $(addprefix $(1)/,$(word 1,$(subst :, ,$I))) $(2)/$(word 2,$(subst :, ,$I)) && \
	$(FIXLINK) $(2)/$(word 2,$(subst :, ,$I)))
define _x_cmkabe_update_libs_tpl
    _x_saved_default_goal := $(.DEFAULT_GOAL)

    $$(foreach I,$(2),$$(eval $(1)_x_$$(I)))
    $(1)_x_FILES := $$(subst ;, ,$$($(1)_x_FILES))

    $(1)_x_target := $(1)
    $(1)_x_local_repo := $$(call either,$$($(1)_x_LOCAL_REPO),../$$(notdir $$(basename $$($(1)_x_URL))))
    $(1)_x_local_file := $$(call either,$$($(1)_x_TARGET_FILE),$$($(1)_x_DEST_DIR))
    $(1)_x_tmp_dir := $$(call either,$$($(1)_x_TMP_DIR),.libs)
    $(1)_x_rebuild := $$(call bool,$$(if $$($(1)_x_REBUILD),$$($$($(1)_x_REBUILD)),))

    cmake-before-build: $$($(1)_x_local_file)
    .PHONY: $$($(1)_x_target)
    $$($(1)_x_target): $$(CMAKE_CLEAN_DEPS)
    $$($(1)_x_target) $$($(1)_x_local_file):
		@$$(RM) -rf $$($(1)_x_tmp_dir)
    ifeq ($$($(1)_x_rebuild),ON)
		@$$(CD) $$($(1)_x_local_repo) && make DEBUG=0
		@$$(call _x_cmkabe_update_lib_cp,$$($(1)_x_local_repo),$$($(1)_x_DEST_DIR),$$($(1)_x_FILES))
    else ifneq ($$(wildcard $$($(1)_x_URL)),)
		@echo Copy from "$$($(1)_x_URL)" ...
		@$$(call _x_cmkabe_update_lib_cp,$$($(1)_x_URL),$$($(1)_x_DEST_DIR),$$($(1)_x_FILES))
    else
		@git clone --depth 1 --branch master $$($(1)_x_URL) $$($(1)_x_tmp_dir)
		@$$(call _x_cmkabe_update_lib_cp,$$($(1)_x_tmp_dir),$$($(1)_x_DEST_DIR),$$($(1)_x_FILES))
		@$$(RM) -rf $$($(1)_x_tmp_dir)
    endif

    .DEFAULT_GOAL := $(_x_saved_default_goal)
    undefine _x_saved_default_goal
endef

endif # __RULES_MK__
