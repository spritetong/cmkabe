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

ifndef WORKSPACE_DIR
    $(warning Please insert to the head of `Makefile` in the workspace directory:)
    $(warning    WORKSPACE_DIR := $$(abspath $$(dir $$(lastword $$(MAKEFILE_LIST)))))
    $(error WORKSPACE_DIR is not defined)
endif

_saved_default_goal := $(.DEFAULT_GOAL)

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

# include .host@$(HOST_SYSTEM_LOWER).mk
_X_DOT_HOST_MK = $(TARGET_CMAKE_DIR)/.host@$(HOST_SYSTEM_LOWER).mk
ifneq ($(filter cmake-init,$(if $(wildcard $(_X_DOT_HOST_MK)),,cmake-init) $(MAKECMDGOALS)),)
    ifneq ($(shell $(cmake_build_target_deps) >$(NULL) || echo 1),)
        $(error Failed to build target: $(TARGET))
    endif
endif
include $(_X_DOT_HOST_MK)

_X_DOT_VARS_DIR := $(TARGET_CMAKE_DIR)/$(if $(filter-out native,$(TARGET)),$(TARGET),$(HOST_TARGET).native)
_X_DOT_VARS_MK = $(_X_DOT_VARS_DIR)/.vars@$(HOST_SYSTEM_LOWER).mk
_X_DOT_TOOLCHAIN_MK = $(_X_DOT_VARS_DIR)/.toolchain@$(HOST_SYSTEM_LOWER).mk

# Auto rebuild dependencies.
$(_X_DOT_VARS_MK): $(addprefix $(CMKABE_HOME)/,shlutilib.py zig-wrapper.zig)
	@$(cmake_build_target_deps)

# include .vars@$(HOST_SYSTEM_LOWER).mk
ifeq ($(wildcard $(_X_DOT_VARS_MK)),)
    ifneq ($(shell $(cmake_build_target_deps) >$(NULL) || echo 1),)
        $(error Failed to build target: $(TARGET))
    endif
endif
include $(_X_DOT_VARS_MK)
ifeq ($(CMAKE_TARGET_DIR),)
    $(error Can not parse target: $(TARGET))
endif

# ==============================================================================
# = CMake

#! Debug mode
override DEBUG := $(call bool,$(DEBUG),ON)
#! Generate with minimum size
override MINSIZE := $(call bool,$(MINSIZE),OFF)
#! Generate debug information
override DBGINFO := $(call bool,$(DBGINFO),$(call bsel,$(DEBUG),ON,OFF))
#! Show verbose output
override VERBOSE := $(call bool,$(VERBOSE),OFF)

#! Triple of Zig target
ZIG_TARGET ?=
#! `<workspace directory>/target`
TARGET_DIR ?=
#! CC compiler for the target
TARGET_CC ?=

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

# The CMake output directory include the tailing triple.
CMAKE_PREFIX_TRIPLE ?= $(CMAKE_TARGET_PREFIX)/$(TARGET)
CMAKE_PREFIX_SUBDIRS ?= $(CMAKE_PREFIX_TRIPLE)
# The CMake build directory for the current configuration.
CMAKE_BUILD_DIR ?= $(CMAKE_TARGET_DIR)/$(CMAKE_BUILD_TYPE)

#! The CMake system version
CMAKE_SYSTEM_VERSION ?=
#! The CMake output directory exclude the tailing triple.
CMAKE_TARGET_PREFIX ?= $(TARGET_CMAKE_DIR)/output
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
#! CMake initialization options
CMAKE_INIT_OPTS ?=
#! CMake additional options
CMAKE_OPTS ?=
#! If automatically clean the $(CMAKE_TARGET_PREFIX) directory
CMAKE_AUTO_CLEAN_TARGET ?= ON

_X_CMAKE_INIT = cmake -B "$(CMAKE_BUILD_DIR)"
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

cmake_init = $(_X_CMAKE_INIT) $(CMAKE_INIT_OPTS)
cmake_build = cmake --build "$(CMAKE_BUILD_DIR)" $(addprefix --target ,$(CMAKE_TARGETS)) --config $(CMAKE_BUILD_TYPE) --parallel $(CMAKE_OPTS)
cmake_install = cmake --install "$(CMAKE_BUILD_DIR)" $(addprefix --component ,$(CMAKE_COMPONENTS)) --config $(CMAKE_BUILD_TYPE) $(CMAKE_OPTS)
ifeq ($(if $(filter --prefix,$(CMAKE_OPTS)),1,)$(if $(CMAKE_INSTALL_TARGET_PREFIX),,1),)
    cmake_install += --prefix "$(CMAKE_INSTALL_TARGET_PREFIX)/$(TARGET)"
endif
cmake_clean = $(call cmake_build) --target clean

# ==============================================================================
# = Android NDK

#! Android SDK version (API level), defaults to 21.
ANDROID_SDK_VERSION ?= 21
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
CARGO_RUN_ARGS ?= $(RUN_ARGS)
#! Cargo binary crates
CARGO_EXECUTABLES +=
#! Cargo library crates
CARGO_LIBRARIES +=

_X_CARGO_OPTS = $(call bsel,$(TARGET_IS_NATIVE),,--target $(CARGO_TARGET))
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
CARGO_TARGET_OUT_DIR ?=

# Clean the $(CMAKE_TARGET_PREFIX) directory by default.
ifeq ($(call bool,$(CMAKE_AUTO_CLEAN_TARGET)),ON)
    CMAKE_OUTPUT_DIRS += $(CMAKE_TARGET_PREFIX)
endif

# ==============================================================================
# = Rules

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
	@$(RM) -rf "$(TARGET_CMAKE_DIR)" "$(TARGET_DIR)/.zig" || $(OK)

# Clean extra output files.
cmake-clean-output:
	@$(if $(CMAKE_OUTPUT_DIRS),$(call git_remove_ignored,$(CMAKE_OUTPUT_DIRS),$(CMAKE_OUTPUT_FILE_PATTERNS)) || $(OK),$(OK))
	@$(RM) -rf $(CMAKE_OUTPUT_FILES) "$(WORKSPACE_DIR)/-" || $(OK)
	@$(call exists,"$(WORKSPACE_DIR)/CMakeLists.txt") && $(TOUCH) "$(WORKSPACE_DIR)/CMakeLists.txt" || $(OK)

# Cargo command
cargo:
	@$(call cargo_command,$(CARGO_CMD)) $(_X_CARGO_RUN_ARGS)

# Cargo bench
cargo-bench: cmake-before-build
	@$(call cargo_command,bench) $(_X_CARGO_RUN_ARGS)

# Cargo build
cargo-build: cmake-before-build
	@cargo $(CARGO_TOOLCHAIN) build $(_X_CARGO_OPTS)

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
	@$(call cargo_command,test) $(_X_CARGO_RUN_ARGS)

# Upgrade dependencies
cargo-upgrade:
	@cargo update
	@$(call cargo_upgrade)

zig-patch:
	@$(SHLUTIL) zig_patch

# Execute a shell command
shell:
	$(CMD)

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

    .PHONY: build run lib clean clean-cmake help

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

    help:
    ifeq ($$(HOST_SYSTEM),Windows)
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

    $(1)_x_target := $(1)
    $(1)_x_local_repo := $$(call either,$(3),../$$(notdir $$(basename $(2))))
	$(1)_x_local_file := $$(call either,$(6),$(5))
    $(1)_x_tmp_dir := $$(call either,$(7),.libs)
    $(1)_x_rebuild := $$(call bool,$$(if $(8),$$($(8)),))

    cmake-before-build: $$($(1)_x_local_file)
    .PHONY: $$($(1)_x_target)
    $$($(1)_x_target): cmake-clean-output
    $$($(1)_x_target) $$($(1)_x_local_file):
		@$$(RM) -rf $$($(1)_x_tmp_dir)
    ifeq ($$($(1)_x_rebuild),ON)
		@$$(CD) $$($(1)_x_local_repo) && make DEBUG=0
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(addprefix $$($(1)_x_local_repo),$(4)) $(5)/ && $$(FIXLINK) $(5)/
    else ifneq ($$(wildcard $(2)),)
		@echo Copy from "$(2)" ...
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(addprefix $(2)/,$(4)) $(5)/ && $$(FIXLINK) $(5)/
    else
		@git clone --depth 1 --branch master $(2) $$($(1)_x_tmp_dir)
		@$$(MKDIR) $(5)
		@$$(CP) -rfP $$(addprefix $$($(1)_x_tmp_dir)/,$(4)) $(5)/ && $$(FIXLINK) $(5)/
		@$$(RM) -rf $$($(1)_x_tmp_dir)
    endif

    .DEFAULT_GOAL := $(_saved_default_goal)
    undefine _saved_default_goal
endef

endif # __RULES_MK__
