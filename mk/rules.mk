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

CMKABE_CLEAN_GOALS += cmake-clean-all cmake-clean cmake-distclean cmake-clean-output
CMKABE_CLEAN_GOALS += zig-patch zig-clean-cache

CMKABE_IS_CLEANING := $(if $(filter $(CMKABE_CLEAN_GOALS),$(MAKECMDGOALS)),ON,OFF)
ifeq ($(CMKABE_IS_CLEANING),ON)
    ifneq ($(filter-out $(CMKABE_CLEAN_GOALS),$(MAKECMDGOALS)),)
        $(warning Cannot execute `clean` and other goals at the same time!)
        $(error Please run `make $(filter $(CMKABE_CLEAN_GOALS),$(MAKECMDGOALS))` first, then run `make ...`)
    endif
endif

# Set a sentinel goal to force CMake initialization when `cmake-init` is specified.
ifneq ($(filter cmake-init,$(MAKECMDGOALS)),)
    _X_CMAKE_FORCE_INIT = _x_cmake_force_init_goal
    .PHONY: _x_cmake_force_init_goal
    _x_cmake_force_init_goal: ;
else
    _X_CMAKE_FORCE_INIT =
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
cmake_build_target_deps = $(SHLUTIL) build-target-deps \
    WORKSPACE_DIR=$(WORKSPACE_DIR) \
    TARGET=$(CMKABE_TARGET) \
    TARGET_DIR=$(TARGET_DIR) \
    TARGET_CMAKE_DIR=$(TARGET_CMAKE_DIR) \
    TARGET_DEPENDENCY_PREFIXES="$(subst $(SPACE),;,$(strip $(TARGET_DEPENDENCY_PREFIXES)))" \
    TARGET_CC=$(TARGET_CC) \
    CARGO_TARGET=$(CARGO_TARGET) \
    ZIG_TARGET=$(ZIG_TARGET)

# Phase 1: Build host info if it is missing
_X_DOT_HOST_MK = $(TARGET_CMAKE_DIR)/$(HOST_SYSTEM)/.host.mk
ifeq ($(CMKABE_IS_CLEANING),OFF)
    ifeq ($(wildcard $(_X_DOT_HOST_MK)),)
        ifneq ($(shell $(cmake_build_target_deps) >$(NULL) || echo 1),)
            $(error Failed to build target: $(TARGET))
        endif
    endif
    include $(_X_DOT_HOST_MK)
else
    -include $(_X_DOT_HOST_MK)
endif

# Define target paths (HOST_SYSTEM might have been overridden by .host.mk)
_X_DOT_TARGET_DIR := $(TARGET_CMAKE_DIR)/$(HOST_SYSTEM)/$(if $(filter-out native,$(TARGET)),$(TARGET),native)
_X_DOT_SETTINGS_MK = $(_X_DOT_TARGET_DIR)/.settings.mk
_X_DOT_ENVIRON_MK = $(_X_DOT_TARGET_DIR)/.environ.mk

# Phase 2: Build target settings if missing and we didn't build them in Phase 1
ifeq ($(CMKABE_IS_CLEANING),OFF)
    include $(_X_DOT_SETTINGS_MK)
else
    -include $(_X_DOT_SETTINGS_MK)
endif

ifeq ($(CMAKE_TARGET_DIR),)
    ifeq ($(CMKABE_IS_CLEANING),OFF)
        ifneq ($(wildcard $(_X_DOT_SETTINGS_MK)),)
            $(error Can not parse target: $(TARGET))
        endif
    else
        override CMAKE_TARGET_DIR = $(TARGET_CMAKE_DIR)/$(HOST_SYSTEM)/$(TARGET)
        override CMAKE_BUILD_DIR = $(CMAKE_TARGET_DIR)/$(CMAKE_BUILD_TYPE)
    endif
endif

# Auto rebuild dependencies.
ifeq ($(CMKABE_IS_CLEANING),OFF)
    _X_DOT_SETTINGS_DEPS += $(wildcard $(CMKABE_HOME)/cmake/*.cmake)
    _X_DOT_SETTINGS_DEPS += $(wildcard $(CMKABE_HOME)/mk/*.mk)
    _X_DOT_SETTINGS_DEPS += $(wildcard $(CMKABE_HOME)/pylib/*.py)
    _X_DOT_SETTINGS_DEPS += $(wildcard $(CMKABE_HOME)/zig-wrapper/*.zig)
    _X_DOT_SETTINGS_DEPS += $(filter-out $(subst \,/,$(TARGET_CMAKE_DIR))/%,$(subst \,/,$(MAKEFILE_LIST)))
    $(_X_DOT_ENVIRON_MK): $(_X_DOT_SETTINGS_MK) ;
    $(_X_DOT_SETTINGS_MK): $(_X_DOT_SETTINGS_DEPS) $(_X_CMAKE_FORCE_INIT)
		@$(cmake_build_target_deps)
endif

# ==============================================================================
# = CMake

#! Triple of Zig target
ZIG_TARGET ?=
#! `<workspace directory>/target`
TARGET_DIR ?=
#! The CMake installation directory exclude the tailing triple.
TARGET_INSTALL_PREFIX ?= $(WORKSPACE_DIR)/installed
#! The CMake output directory exclude the tailing triple.
TARGET_DEPENDENCY_PREFIXES +=
#! CC compiler for the target
TARGET_CC ?=

# The CMake build directory for the current configuration.
CMAKE_BUILD_DIR ?= $(CMAKE_TARGET_DIR)/$(CMAKE_BUILD_TYPE)
#! The CMake system version
CMAKE_SYSTEM_VERSION ?=
#! The CMake components to be installed.
CMAKE_COMPONENTS +=
#! The CMake targets (libraries and executables) to be built.
CMAKE_TARGETS +=
#! CMake output directories to be cleaned.
CMAKE_OUTPUT_DIRS +=
CMAKE_OUTPUT_FILES +=
#! CMake output file patterns to be cleaned.
CMAKE_OUTPUT_FILE_PATTERNS +=
#! CMake definitions, such as `FOO=bar`
CMAKE_DEFS +=
#! CMake initialization options
CMAKE_INIT_OPTS +=
#! CMake additional options
CMAKE_OPTS +=

_X_CMAKE_INIT = cmake --toolchain "$(CMKABE_HOME)/cmake/toolchain.cmake" -B "$(CMAKE_BUILD_DIR)"
_X_CMAKE_INIT += $(if $(CMAKE_GENERATOR),-G "$(CMAKE_GENERATOR)",)
_X_CMAKE_INIT += -D "WORKSPACE_DIR:FILEPATH=$(WORKSPACE_DIR)"
_X_CMAKE_INIT += -D "TARGET:STRING=$(CMKABE_TARGET)"
_X_CMAKE_INIT += -D "TARGET_DIR:FILEPATH=$(TARGET_DIR)"
_X_CMAKE_INIT += -D "TARGET_CMAKE_DIR:FILEPATH=$(TARGET_CMAKE_DIR)"
# _X_CMAKE_INIT += -D "TARGET_DEPENDENCY_PREFIXES:STRING=$(subst $(SPACE),;,$(strip $(TARGET_DEPENDENCY_PREFIXES)))"
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

CMAKE_BUILD_DEPS += $(CMAKE_BUILD_DIR)/.dirstamp
CMAKE_CLEAN_DEPS += cmake-clean-output

# cmake_init()
cmake_init = $(_X_CMAKE_INIT) $(CMAKE_INIT_OPTS)

# cmake_build(<targets:list<str>>)
cmake_build = cmake --build "$(CMAKE_BUILD_DIR)" \
    $(addprefix --target ,$(if $(1),$(1),$(subst ;,$(SPACE),$(CMAKE_TARGETS)))) \
    --config $(CMAKE_BUILD_TYPE) --parallel $(CMAKE_OPTS)

# cmake_install(<components:list<str>>,<target_install_prefix:str>)
cmake_install = cmake --install "$(CMAKE_BUILD_DIR)" \
    $(addprefix --component ,$(if $(1),$(1),$(subst ;,$(SPACE),$(CMAKE_COMPONENTS)))) \
    --config $(CMAKE_BUILD_TYPE) \
    --prefix "$(if $(2),$(2),$(TARGET_INSTALL_PREFIX))/$(TARGET)" $(CMAKE_OPTS)

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

#! Cargo toolchain
CARGO_TOOLCHAIN +=
#! Triple of Cargo target
CARGO_TARGET ?=
#! Cargo manifest path
CARGO_MANIFEST_PATH ?=
#! Cargo package to build
CARGO_PACKAGE ?=
#! Extra options passed to "cargo"
CARGO_OPTS +=
#! Arguments passed "cargo run", "cargo test" or "cargo bench"
CARGO_RUN_ARGS ?= $(ARGS)
#! Cargo binary crates
CARGO_EXECUTABLES +=
#! Cargo library crates
CARGO_LIBRARIES +=

_X_CARGO_OPTS = $(if $(filter $(HOST_CARGO_TARGET),$(CARGO_TARGET)),,--target $(CARGO_TARGET))
_X_CARGO_OPTS += $(if $(CARGO_MANIFEST_PATH),--manifest-path $(CARGO_MANIFEST_PATH),)
_X_CARGO_OPTS += $(if $(CARGO_PACKAGE),-p $(CARGO_PACKAGE),)
_X_CARGO_OPTS += --target-dir $(CARGO_TARGET_DIR)
_X_CARGO_OPTS += $(call bsel,$(DEBUG),,--release)
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
cargo_upgrade = cargo $(CARGO_TOOLCHAIN) upgrade --incompatible $(1)

# Set crosss compile tools for Rust
$(call cmkabe_update_toolchain)

# Directory of Cargo output binaries, normally is "<workspace_dir>/target/<triple>/<debug|release>"
CARGO_OUT_DIR ?=

# ==============================================================================
# = Rules

.PHONY: cmake
cmake: cmake-build

# Do something before building
.PHONY: cmake-before-build
cmake-before-build: ;

# Initialize the cmake build directory.
.PHONY: cmake-init
cmake-init: $(CMAKE_BUILD_DIR)/.dirstamp cmake-before-build
$(CMAKE_BUILD_DIR)/.dirstamp: $(_X_DOT_HOST_MK) $(_X_DOT_ENVIRON_MK) $(_X_DOT_SETTINGS_MK)
	@$(call cmake_init)
	@$(TOUCH) "$(CMAKE_BUILD_DIR)/.dirstamp"

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

# Clean the CMake root directory of all targets.
.PHONY: cmake-clean-all
cmake-clean-all: $(CMAKE_CLEAN_DEPS)
	@$(RM) -rf "$(TARGET_CMAKE_DIR)" "$(TARGET_DIR)/.zig" || $(OK)

# Clean the target.
.PHONY: cmake-clean
cmake-clean: $(CMAKE_CLEAN_DEPS)
	@$(call exists,"$(CMAKE_BUILD_DIR)") && $(call cmake_clean) || $(OK)

# Clean the target and erase the build directory.
.PHONY: cmake-distclean
cmake-distclean: $(CMAKE_CLEAN_DEPS)
	@$(RM) -rf "$(CMAKE_BUILD_DIR)" || $(OK)

# Clean extra output files.
.PHONY: cmake-clean-output
cmake-clean-output:
	@$(RM) -rf $(CMAKE_OUTPUT_DIRS) && $(RMDIR) -p $(CMAKE_OUTPUT_DIRS) || $(OK)
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
	-@cargo $(CARGO_TOOLCHAIN) clean
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
	@cargo $(CARGO_TOOLCHAIN) update
	@$(call cargo_upgrade)

# Patch Zig source files
.PHONY: zig-patch
zig-patch:
	@$(SHLUTIL) zig-patch "$(ZIG_ROOT)"

# Clean Zig cache
.PHONY: zig-clean-cache
zig-clean-cache:
	@$(SHLUTIL) zig-clean-cache -v "$(ZIG_ROOT)" || $(OK)
	@$(RM) -rf "$(TARGET_DIR)/.zig" || $(OK)

# Execute a shell command
.PHONY: shell
shell:
    ifeq ($(HOST_SYSTEM),Windows)
		-@$(SHLUTIL) find-shell --exit-code & if errorlevel 2 (pwsh.exe -NoLogo) else if errorlevel 1 (powershell.exe -NoLogo) else (cmd.exe /k set "PROMPT=(make) %PROMPT%")
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
	@echo "TARGET_DEPENDENCY_PREFIXES:  $(TARGET_DEPENDENCY_PREFIXES)"
	@echo "CMAKE_BUILD_DIR:             $(CMAKE_BUILD_DIR)"
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

    .PHONY: clean
    cargo-clean: $$(CMAKE_CLEAN_DEPS)
    clean: cargo-clean

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

endif # __RULES_MK__
