# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe


ifndef __ENV_MK__
__ENV_MK__ = $(abspath $(lastword $(MAKEFILE_LIST)))
CMKABE_HOME := $(abspath $(dir $(__ENV_MK__))/..)

CMKABE_VERSION = 0.9.1

# all clean goal names
CMKABE_CLEAN_GOALS = clean distclean cargo-clean
CMAKE_BUILD_DEPS =
CMAKE_CLEAN_DEPS =
CMAKE_PURGE_DEPS =
TARGET_DEPENDENCY_PREFIXES =
# internal variable
_X_DOT_SETTING_DEPS =
unexport MAKE_RESTARTS

# Disable parallel execution
.NOTPARALLEL:

# ==============================================================================
# = Environment Variables

# HOST_SYSTEM: Windows, Linux, Darwin
override HOST_SYSTEM := $(if $(filter Windows_NT,$(OS)),Windows,$(shell uname -s))

# ==============================================================================
# = Utilities

# cmkabe_version_required(version:str)
cmkabe_version_required = $(eval $(call _x_cmkabe_version_check,$(1)))
define _x_cmkabe_version_check
    ifeq ($$(call version_compare,$(1),$$(CMKABE_VERSION)),+)
        $$(error Please upgrade `cmkabe` to >=$(1). Try: git submodule update --init)
    endif
endef

# Download external libraries for CMake.
# cmkabe_clone_libs(
# <target_name:str>
#    The Make target name used to clone/download the libraries.
# <local_destination_dir:str>
#    The destination directory in the local workspace.
# --url <git_repo_url:str>
#    Either a URL to the remote source repository or a local path.
# --local-repo <local_repo_dir:str>
#    Path to the local source repository which is used to rebuild the libraries,
#    defaults (an empty string) to "../$(notdir $(basename $(git_repo_url)))".
# --files <git_source_files:list<str>>
#    Files (and directories) to be copyed from the source repository to the destination directory.
# --target-file=<local_target_file:str>
#    The local target file or directory for make, defaults (an empty string) to `<DEST_DIR>`.
# --tmp-dir=<tmp_dir:str>
#    The temporary directory, defaults to `.libs`
# --rebuild=<rebuild_target_name:str>
#    The Make target name used to rebuild the libraries in the local source repository `<LOCAL_REPO>`.
# )
cmkabe_clone_libs = $(eval $(call _x_cmkabe_clone_libs_tpl,$(1),$(2),$(3)))
define _x_cmkabe_clone_libs_tpl
    _x_saved_default_goal := $$(.DEFAULT_GOAL)
    ifneq ($$(__RULES_MK__),)
        $$(error Error: `cmkabe_clone_libs` should not be called before `cmkabe_parse_target`)
    endif

    ifeq ($(1),)
        $$(error Error: `cmkabe_clone_libs` requires a target name as the first argument)
    endif
    CMKABE_CLEAN_GOALS += $(1)
    CMAKE_PURGE_DEP_DIRS += $(2)
    TARGET_DEPENDENCY_PREFIXES += $(2)
    $$(call cmkabe_add_setting_deps,$(2))

    .PHONY: $(1)
    $(1) $(2):
		@$$(RM) -rf "$(2)" || $$(OK)
		@$$(SHLUTIL) clone-libs --dest-dir "$(2)" $(3)

    .DEFAULT_GOAL := $$(_x_saved_default_goal)
    undefine _x_saved_default_goal
endef
define _x_cmkabe_add_deps_tpl
    ifneq ($(2),)
        _x_saved_default_goal := $$(.DEFAULT_GOAL)
        $(3): $(1)
        .DEFAULT_GOAL := $$(_x_saved_default_goal)
        undefine _x_saved_default_goal
    else
        $(4) += $(1)
    endif
endef

# cmkabe_parse_target()
#    Parse the target triplet, compiler and apply to the toolchain.
cmkabe_parse_target = $(eval include $(CMKABE_HOME)/mk/rules.mk)

# cmkabe_update_toolchain()
#    Apply settings to the toolchain of the current target.
cmkabe_update_toolchain = $(eval $(if $(filter $(CMKABE_IS_CLEANING),OFF),,-)include $(_X_DOT_ENVIRON_MK))

# cmkabe_add_setting_deps(<targets>)
#    Register the targets as dependencies of the settings files initialization.
cmkabe_add_setting_deps = $(eval $(call _x_cmkabe_add_deps_tpl,$(1),$(_X_DOT_SETTINGS_MK),$(_X_DOT_SETTINGS_MK),_X_DOT_SETTING_DEPS))

# cmkabe_add_build_deps(<targets>)
#    Register the targets as dependencies of the build target.
cmkabe_add_build_deps = $(eval $(call _x_cmkabe_add_deps_tpl,$(1),$(__RULES_MK__),cmake-before-build,CMAKE_BUILD_DEPS))

# cmkabe_add_clean_deps(<targets>)
#    Register the targets as dependencies of the clean targets.
cmkabe_add_clean_deps = $(eval $(call _x_cmkabe_add_deps_tpl,$(1),$(__RULES_MK__),cmake-clean-output,CMAKE_CLEAN_DEPS))

# cmkabe_add_purge_deps(<targets>)
#    Register the targets as dependencies of the purge targets.
cmkabe_add_purge_deps = $(eval $(call _x_cmkabe_add_deps_tpl,$(1),$(__RULES_MK__),cmake-purge-deps,CMAKE_PURGE_DEPS))

# If `$(TARGET_IS_NATIVE)` is true, return `native`; otherwise, return `$(TARGET)`.
CMKABE_TARGET = $(call bsel,$(TARGET_IS_NATIVE),native,$(TARGET))

# bool(value:bool,default:bool)
bool = $(call _x_bool_norm,$(1),$(if $(2),$(2),OFF))
_X_BOOL_MAP = a,A e,E f,F l,L o,O n,N r,R s,S t,T u,U
_x_bool_upper = $(strip $(eval __x := $(1))$(foreach __y,$(_X_BOOL_MAP),$(eval __x := $$(subst $(__y),$$(__x))))$(__x))
_x_bool_norm = $(word 2,$(subst =, ,$(filter $(call _x_bool_upper,$(1))=%,1=ON ON=ON TRUE=ON 0=OFF OFF=OFF FALSE=OFF)) OFF $(2))

# not(value:bool)
not = $(if $(filter ON,$(call bool,$(1))),OFF,ON)

# either(value1:str,value2:str)
either = $(if $(1),$(1),$(2))

# sel(name:str,<name:str=value:str list>,default)
# e.g. $(call sel,A,A=1 B=2,0) == 1
sel = $(if $(filter $(1)=%,$(2)),$(patsubst $(1)=%,%,$(filter $(1)=%,$(2))),$(3))

# bsel(ON_or_OFF:bool,value_of_ON:str,value_of_OFF:str)
#    e.g. $(call bsel,ON,A,B) == A
bsel = $(if $(filter ON,$(call bool,$(1))),$(2),$(3))

# lower(value:str)
lower = $(subst ~!@"',,$(eval __x := ~!@"'$(1)~!@"')$(strip $(foreach __y,$(_X_LWR_MAP),$(eval __x := $$(subst $(__y),$$(__x)))))$(__x))
_X_LWR_MAP = A,a B,b C,c D,d E,e F,f G,g H,h I,i J,j K,k L,l M,m N,n O,o P,p Q,q R,r S,s T,t U,u V,v W,w X,x Y,y Z,z

# upper(value:str)
upper = $(subst ~!@"',,$(eval __x := ~!@"'$(1)~!@"')$(strip $(foreach __y,$(_X_UPR_MAP),$(eval __x := $$(subst $(__y),$$(__x)))))$(__x))
_X_UPR_MAP = a,A b,B c,C d,D e,E f,F g,G h,H i,I j,J k,K l,L m,M n,N o,O p,P q,Q r,R s,S t,T u,U v,V w,W x,X y,Y z,Z

# greater_than(x:int[0,99999999],y:int[0,99999999])
#     if x > y, return ON, OFF otherwise
# greater_or_equal(x:int[0,99999999],y:int[0,99999999])
#     if x >= y, return ON, OFF otherwise
# number_compare(x:int[0,99999999],y:int[0,99999999])
#     (x > y) -> +
#     (x == y) -> =
#     (x < y) -> -
greater_than = $(if $(filter $(1),$(2)),OFF,$(if $(filter $(call _compare_pad8,$(1)),$(firstword $(sort $(call _compare_pad8,$(1)) $(call _compare_pad8,$(2))))),OFF,ON))
greater_or_equal = $(if $(filter $(1),$(2)),ON,$(if $(filter $(call _compare_pad8,$(1)),$(firstword $(sort $(call _compare_pad8,$(1)) $(call _compare_pad8,$(2))))),OFF,ON))
number_compare = $(if $(filter $(1),$(2)),=,$(if $(filter $(call _compare_pad8,$(1)),$(firstword $(sort $(call _compare_pad8,$(1)) $(call _compare_pad8,$(2))))),-,+))
_compare_to_x = $(subst 0,x ,$(subst 1,x ,$(subst 2,x ,$(subst 3,x ,$(subst 4,x ,$(subst 5,x ,$(subst 6,x ,$(subst 7,x ,$(subst 8,x ,$(subst 9,x ,$(1)))))))))))
_compare_to_chars = $(subst 0,0 ,$(subst 1,1 ,$(subst 2,2 ,$(subst 3,3 ,$(subst 4,4 ,$(subst 5,5 ,$(subst 6,6 ,$(subst 7,7 ,$(subst 8,8 ,$(subst 9,9 ,$(1)))))))))))
_compare_pad8 = $(subst $(SPACE),,$(wordlist $(words x $(call _compare_to_x,$(1))),$(words x x x x x x x x $(call _compare_to_x,$(1))),0 0 0 0 0 0 0 0 $(call _compare_to_chars,$(1))))

# version_compare(x:str,y:str)
#     (x > y) -> +
#     (x == y) -> =
#     (x < y) -> -
version_compare = $(if $(call _ver_greater_,$(1),$(2)),+,$(if $(call _ver_greater_,$(2),$(1)),-,=))
_ver_num_at_ = $(word $(1),$(subst ., ,$(2)) 0 0 0 0)
_ver_greater_results_ = $(subst $(SPACE),,$(foreach I,1 2 3 4,$(call number_compare,$(call _ver_num_at_,$I,$(1)),$(call _ver_num_at_,$I,$(2)))))
_ver_greater_ = $(filter 1,$(foreach I,:+ :=+ :==+ :===+,$(if $(findstring $I,:$(call _ver_greater_results_,$(1),$(2))),1,)))

# kv_key(key=value)
kv_key = $(firstword $(subst =, ,$(1)))

# kv_value(key=value)
kv_value = $(lastword $(subst =, ,$(1)))

# git_ls_untracked(directory:str,patterns:List<str>)
git_ls_untracked = git ls-files --others $(if $(2),$(addprefix -x ,$(2)),--exclude-standard) $(1)

# git_ls_ignored(directory:str,patterns:List<str>)
git_ls_ignored = git ls-files --others -i $(if $(2),$(addprefix -x ,$(2)),--exclude-standard) $(1)

# git_remove_ignored(directories:str,patterns:List<str>)
git_remove_ignored = $(call git_ls_ignored,$(1),$(2)) | $(RM) -f --stdin && $(RMDIR) -p $(1)

# Check existence of a file or a directory in command line.
# exists(file_or_directory:str)
exists = test -e $(1)

# Join paths with $(PATHSEP).
# join_paths(paths:str,subdirs:str)
join_paths = $(subst $(SPACE)$(PATHSEP),$(PATHSEP),$(foreach I,$(1),$(foreach J,$(2),$(PATHSEP)$I/$J)))

# Call rmake with options.
# rmake(options:str)
rmake = $(PY) rmake.py $(1)
# If RMAKE is on, call rmake; otherwise, call make directly.
# try_rmake(options:str)
try_rmake = $(call bsel,$(RMAKE),$(call rmake,$(1)),$(call wsl_run,make $(1)))

# Set an environment variable in command line.
# set_env(key:str,value:str)
set_env = export $(1)="$(2)"

# Run a command on WSL Linux.
# wsl_run(cmd:str)
wsl_run = $(1)

# Run a command with arguments read from input in command line.
# xargs_do(input:str,command:str)
xargs_do = $(1) | xargs -I {} $(2)

# Extension name of executable files, ".exe" on Windows or "" on other systems.
EXE_EXT =
# Directory separator, "\\" on Windows or "/" on other systems.
SEP    := $(if $(filter Windows,$(HOST_SYSTEM)),\,/)
# Path Separator, ";" on Windows or ":" on other systems.
PATHSEP:= $(if $(filter Windows,$(HOST_SYSTEM)),;,:)

# ','
COMMA   = ,
# '\\'
ESC    := $(strip \)# Shell's escape character
# ' '
SPACE  := $(subst :,,: :)
# '\t'
TAB := $(subst :,,:	:)

NULL    = /dev/null
OK      = true
ERR     = false

SHLUTIL = $(PY) "$(CMKABE_HOME)/shlutil.py"

CARGO_EXEC = $(SHLUTIL) cargo-exec
CD      = cd
CMPVER  = $(SHLUTIL) cmpver
CP      = cp
CWD     = $(SHLUTIL) cwd
FIXLINK = $(SHLUTIL) fix-symlink
less    = less $(1)
MKDIR   = $(SHLUTIL) mkdir
MKLINK  = $(SHLUTIL) mklink
MV      = mv
PY      = python3
RELPATH = $(SHLUTIL) relpath
RM      = $(SHLUTIL) rm
RMDIR   = $(SHLUTIL) rmdir -f
TOUCH   = touch
UPLOAD  = $(SHLUTIL) upload
WHICH   = which
WIN2WSL = $(SHLUTIL) win2wsl-path
WSL2WIN = $(SHLUTIL) wsl2win-path

ifeq ($(HOST_SYSTEM),Windows)
    exists   = (IF NOT EXIST $(subst /,$(SEP),$(1)) $(ERR))
    set_env  = (SET $(1)=$(2))
    wsl_run  = wsl.exe --shell-type login$(if $(WSL_DISTRO), -d "$(WSL_DISTRO)",)$(if $(WSL_USER), -u "$(WSL_USER)",) $(1)
    xargs_do = (FOR /F "tokens=*" %%x IN ('$(1)') DO $(subst {},%%x,$(2)))

    EXE_EXT  = .exe
    PS       = ;

    NULL     = NUL
    OK       = CD .
    ERR      = (CALL)

    CD       = CD /D
    CP       = $(SHLUTIL) cp
    less     = more $(subst /,$(SEP),$(1))
    MV       = $(SHLUTIL) mv
    PY       = python.exe
    TOUCH    = $(SHLUTIL) touch
    WHICH    = where.exe

    WINREG   = $(SHLUTIL) winreg
endif

endif # __ENV_MK__
