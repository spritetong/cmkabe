# * @file       env.mk
# * @brief      This file contains environment and common utilities for CMake.
# * @details    Copyright (C) 2022 spritetong@gmail.com.\n
# *             All rights reserved.\n
# * @author     spritetong@gmail.com
# * @date       2014
# * @version    1.0, 7/9/2022, Tong
# *             - Initial revision.
# *

ifndef __ENV_MK__
__ENV_MK__ = $(abspath $(lastword $(MAKEFILE_LIST)))
CMKABE_HOME := $(abspath $(dir $(__ENV_MK__)))

CMAKEABE_VERSION = 0.3.0

# ==============================================================================
# = Environment Variables

# HOST: Windows, Linux, Darwin
override HOST := $(if $(filter Windows_NT,$(OS)),Windows,$(shell uname -s))

# ==============================================================================
# = Utilities

# cmakeabe_version_required(version:str)
cmakeabe_version_required = $(eval $(call _cmakeabe_version_check_,$(1)))
define _cmakeabe_version_check_
    ifeq ($$(call version_compare,$(1),$$(CMAKEABE_VERSION)),+)
        $$(error Please upgrade cmake-abe to >=$(1). Try: git submodule update --init))
    endif
endef

# not(value:bool)
not = $(if $(filter $(ON_VALUES),$(1)),OFF,ON)

# bool(value:bool,default:bool)
bool = $(call either,$(call _bool_norm_,$(call upper,$(1)),),$(call _bool_norm_,$(call upper,$(2)),OFF))
_bool_norm_ = $(if $(filter 1 TRUE ON,$(1)),ON,$(if $(filter 0 FALSE OFF,$(1)),OFF,$(2)))

# either(value1:str,value2:str)
either = $(if $(1),$(1),$(2))

# sel(name:str,<name:str=value:str list>,default)
# e.g. $(call sel,A,A=1 B=2,0) == 1
sel = $(if $(filter $(1)=%,$(2)),$(patsubst $(1)=%,%,$(filter $(1)=%,$(2))),$(3))

# bsel(ON_or_OFF:bool,for_ON:str,for_OFF:str)
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
git_remove_ignored = $(call git_ls_ignored,$(1),$(2)) | $(RM) -f --stdin

# Check existence of a file or a directory in command line.
# exists(file_or_directory:str,patterns:List<str>)
exists = test -e $(1)

# Set an environment variable in command line.
# set_env(key:str,value:str)
set_env = export $(1)=$(2)

# Run command with arguments read from input in command line.
# xargs_do(input:str,command:str)
xargs_do = $(1) | xargs -I {} $(2)

COMMA   = ,
ESC    := $(strip \)# Shell's escape character
PS      = :# PATH variable's separator
SPACE  := $(subst :,,: :)

NULL    = /dev/null
OK      = test 1 == 1
ERR     = test 0 == 1

CARGO_EXEC = $(PY) "$(CMKABE_HOME)/shlutil.py" cargo-exec
CD      = cd
CMPVER  = $(PY) "$(CMKABE_HOME)/shlutil.py" cmpver
CP      = cp
CWD     = $(PY) "$(CMKABE_HOME)/shlutil.py" cwd
FIXLINK = $(PY) "$(CMKABE_HOME)/shlutil.py" fix_symlink
less    = less $(1)
MKDIR   = $(PY) "$(CMKABE_HOME)/shlutil.py" mkdir
MV      = mv
PY      = python3
RELPATH = $(PY) "$(CMKABE_HOME)/shlutil.py" relpath
RM      = $(PY) "$(CMKABE_HOME)/shlutil.py" rm
RMDIR   = $(PY) "$(CMKABE_HOME)/shlutil.py" rmdir -f
TOUCH   = touch
UPLOAD  = $(PY) "$(CMKABE_HOME)/shlutil.py" upload
WHICH   = which

ifeq ($(HOST),Windows)
    exists   = (IF NOT EXIST $(subst /,\\,$(1)) $(ERR))
    set_env  = set $(1)=$(2)
    xargs_do = (FOR /F "tokens=*" %%x IN ('$(1)') DO $(subst {},%%x,$(2)))

    PS       = ;

    NULL     = NUL
    OK       = SET _=
    ERR      = cmd.exe /C EXIT 1

    CD       = cd /d
    CP       = $(PY) "$(CMKABE_HOME)/shlutil.py" cp
    less     = more $(subst /,\\,$(1))
    MV       = $(PY) "$(CMKABE_HOME)/shlutil.py" mv
    PY       = python.exe
    TOUCH    = $(PY) "$(CMKABE_HOME)/shlutil.py" touch
    WHICH    = where

    WINREG   = $(PY) "$(CMKABE_HOME)/shlutil.py" winreg
endif

endif # __ENV_MK__
