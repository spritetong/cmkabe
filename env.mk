# * @file       env.mk
# * @brief      This file contains environment and common utilities for CMake.
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

ifndef __ENV_MK__
__ENV_MK__ = $(abspath $(lastword $(MAKEFILE_LIST)))
CMKABE_HOME := $(abspath $(dir $(__ENV_MK__)))

CMKABE_VERSION = 0.8.5

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

# cmkabe_parse_target()
#    Parse the target triplet, compiler and apply to the toolchain.
cmkabe_parse_target = $(eval include $(CMKABE_HOME)/rules.mk)

# cmkabe_update_toolchain()
#    Apply settings to the toolchain of the current target.
cmkabe_update_toolchain = $(eval include $(_X_DOT_ENVIRON_MK))

# If `$(TARGET_IS_NATIVE)` is true, return `native`; otherwise, return `$(TARGET)`.
CMKABE_TARGET = $(call bsel,$(TARGET_IS_NATIVE),native,$(TARGET))

# bool(value:bool,default:bool)
bool = $(call _bool_norm_,$(1),$(if $(2),$(2),OFF))
_bool_upper_ = $(subst a,A,$(subst e,E,$(subst f,F,$(subst l,L,$(subst o,O,$(subst n,N,$(subst r,R,$(subst s,S,$(subst t,T,$(subst u,U,$(1)))))))))))
_bool_norm_ = $(word 2,$(subst =, ,$(filter $(call _bool_upper_,$(1))=%,1=ON ON=ON TRUE=ON 0=OFF OFF=OFF FALSE=OFF)) OFF $(2))

# not(value:bool)
not = $(if $(filter ON,$(call bool,$(1))),OFF,ON)

# either(value1:str,value2:str)
either = $(if $(1),$(1),$(2))

# sel(name:str,<name:str=value:str list>,default)
# e.g. $(call sel,A,A=1 B=2,0) == 1
sel = $(if $(filter $(1)=%,$(2)),$(patsubst $(1)=%,%,$(filter $(1)=%,$(2))),$(3))

# bsel(ON_or_OFF:bool,value_of_ON:str,value_of_OFF:str)
#    e.g. $(call bsel,ON,A,B) == A
bsel = $(if $(filter ON,$(1)),$(2),$(3))

# lower(value:str)
lower = $(subst A,a,$(subst B,b,$(subst C,c,$(subst D,d,$(subst E,e,$(subst F,f,$(subst G,g,$(subst H,h,$(subst I,i,$(subst J,j,$(subst K,k,$(subst L,l,$(subst M,m,$(subst N,n,$(subst O,o,$(subst P,p,$(subst Q,q,$(subst R,r,$(subst S,s,$(subst T,t,$(subst U,u,$(subst V,v,$(subst W,w,$(subst X,x,$(subst Y,y,$(subst Z,z,$(1)))))))))))))))))))))))))))

# upper(value:str)
upper = $(subst a,A,$(subst b,B,$(subst c,C,$(subst d,D,$(subst e,E,$(subst f,F,$(subst g,G,$(subst h,H,$(subst i,I,$(subst j,J,$(subst k,K,$(subst l,L,$(subst m,M,$(subst n,N,$(subst o,O,$(subst p,P,$(subst q,Q,$(subst r,R,$(subst s,S,$(subst t,T,$(subst u,U,$(subst v,V,$(subst w,W,$(subst x,X,$(subst y,Y,$(subst z,Z,$(1)))))))))))))))))))))))))))

# greater_than(x:int[1,100],y:int[1,100])
#     if x > y, return ON, OFF otherwise
# greater_or_equal(x:int[1,100],y:int[1,100])
#     if x >= y, return ON, OFF otherwise
# number_compare(x:int[1,100],y:int[1,100])
#     (x > y) -> +
#     (x == y) -> =
#     (x < y) -> -
greater_than = $(if $(filter $(2),$(call _less_than_subset_,$(1))),ON,OFF)
greater_or_equal = $(if $(filter $(2),$(call _less_than_subset_,$(1)) $(1)),ON,OFF)
number_compare = $(if $(filter $(2),$(call _less_than_subset_,$(1))),+,$(if $(filter $(1),$(2)),=,-))
_less_than_subset_ = $(wordlist 1,$(1),0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 \
31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60 \
61 62 63 64 65 66 67 68 69 70 71 72 73 74 75 76 77 78 79 80 81 82 83 84 85 86 87 88 89 90 91 \
92 93 94 95 96 97 98 99 100)

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
git_remove_ignored = $(call git_ls_ignored,$(1),$(2)) | $(RM) -f --stdin && $(RMDIR) -e $(1)

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
try_rmake = $(call bsel,$(call bool,$(RMAKE)),$(call rmake,$(1)),$(call wsl_run,make $(1)))

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
FIXLINK = $(SHLUTIL) fix_symlink
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
WIN2WSL = $(SHLUTIL) win2wsl_path
WSL2WIN = $(SHLUTIL) wsl2win_path

ifeq ($(HOST_SYSTEM),Windows)
    exists   = (IF NOT EXIST $(subst /,$(SEP),$(1)) $(ERR))
    set_env  = (SET $(1)=$(2))
    wsl_run  = wsl --shell-type login$(if $(WSL_DISTRO), -d "$(WSL_DISTRO)",)$(if $(WSL_USER), -u "$(WSL_USER)",) $(1)
    xargs_do = (FOR /F "tokens=*" %%x IN ('$(1)') DO $(subst {},%%x,$(2)))

    EXE_EXT  = .exe
    PS       = ;

    NULL     = NUL
    OK       = SET _=
    ERR      = cmd.exe /C EXIT 1

    CD       = CD /D
    CP       = $(SHLUTIL) cp
    less     = more $(subst /,$(SEP),$(1))
    MV       = $(SHLUTIL) mv
    PY       = python.exe
    TOUCH    = $(SHLUTIL) touch
    WHICH    = where

    WINREG   = $(SHLUTIL) winreg
endif

# export CMKABE_COMPLETED_PORJECTS which is from command line.
ifeq ($(origin CMKABE_COMPLETED_PORJECTS),command line)
    export CMKABE_COMPLETED_PORJECTS
else
    unexport CMKABE_COMPLETED_PORJECTS
endif

endif # __ENV_MK__
