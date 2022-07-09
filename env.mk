#** @file       env.mk
#*  @brief      This file contains environment and common utilities for CMake.
#*  @details    Copyright (C) 2022 spritetong@gmail.com.\n
#*              All rights reserved.\n
#*  @author     spritetong@gmail.com
#*  @date       2014
#*  @version    1.0, 7/9/2022, Tong
#*              - Initial revision.
#**

ifndef __ENV_MK__
__ENV_MK__ = $(abspath $(lastword $(MAKEFILE_LIST)))
CMKHLP_HOME := $(abspath $(dir $(__ENV_MK__)))

# ==============================================================================
# = Environment Variables

# HOST: Windows, Linux, Darwin
override HOST := $(if $(filter Windows_NT,$(OS)),Windows,$(shell uname -s))

# ==============================================================================
# = Utilities

# not(<value:bool>)
not = $(if $(filter $(ON_VALUES),$(1)),OFF,ON)

# bool(<value:bool>,<default:bool>)
bool = $(call either,$(call _bool_norm_,$(call upper,$(1)),),$(call _bool_norm_,$(call upper,$(2)),OFF))
_bool_norm_ = $(if $(filter 1 TRUE ON,$(1)),ON,$(if $(filter 0 FALSE OFF,$(1)),OFF,$(2)))

# either(<value1:str>,<value2:str>)
either = $(if $(1),$(1),$(2))

# sel(<name>, <name=value list>, <default>)
sel = $(if $(filter $(1)=%,$(2)),$(patsubst $(1)=%,%,$(filter $(1)=%,$(2))),$(3))

# bsel(<:bool>,<value for ON>,<value for OFF>)
bsel = $(if $(filter ON,$(1)),$(2),$(3))

# lower(<value:str>)
lower = $(subst A,a,$(subst B,b,$(subst C,c,$(subst D,d,$(subst E,e,$(subst F,f,$(subst G,g,$(subst H,h,$(subst I,i,$(subst J,j,$(subst K,k,$(subst L,l,$(subst M,m,$(subst N,n,$(subst O,o,$(subst P,p,$(subst Q,q,$(subst R,r,$(subst S,s,$(subst T,t,$(subst U,u,$(subst V,v,$(subst W,w,$(subst X,x,$(subst Y,y,$(subst Z,z,$(1)))))))))))))))))))))))))))

# upper(<value:str>)
upper = $(subst a,A,$(subst b,B,$(subst c,C,$(subst d,D,$(subst e,E,$(subst f,F,$(subst g,G,$(subst h,H,$(subst i,I,$(subst j,J,$(subst k,K,$(subst l,L,$(subst m,M,$(subst n,N,$(subst o,O,$(subst p,P,$(subst q,Q,$(subst r,R,$(subst s,S,$(subst t,T,$(subst u,U,$(subst v,V,$(subst w,W,$(subst x,X,$(subst y,Y,$(subst z,Z,$(1)))))))))))))))))))))))))))

# kv_key(<key>=<value>)
kv_key = $(firstword $(subst =, ,$(1)))

# kv_value(<key>=<value>)
kv_value = $(lastword $(subst =, ,$(1)))

# git_ls_untracked(<directory:str>)
git_ls_untracked = git ls-files --others --exclude-standard $(1)

# git_ls_ignored(<directory:str>)
git_ls_ignored = git ls-files --others --exclude-standard -i $(1)

# git_remove_ignored(<directories:str>)
git_remove_ignored = $(call xargs_do,$(call git_ls_ignored,$(1)),$(RM) -f {})

# Check existence of a file or a directory 
# exists(<file or directory:str>)
exists = test -e $(1)

# Run command with arguments read from input.
# xargs_do(<input:str>, <command:str>)
xargs_do = $(1) | xargs -I {} $(2)

COMMA   = ,
ESC    := $(strip \)# Shell's escape character
PS      = :# PATH variable's separator
SPACE  := $(subst :,,: :)

NULL    = /dev/null
OK      = test 1 == 1
ERR     = test 0 == 1

PY      = python
PY3     = python3

CMPVER  = $(PY) "$(CMKHLP_HOME)/shellutil.py" cmpver
CP      = cp
CWD     = $(PY) "$(CMKHLP_HOME)/shellutil.py" cwd
less    = less
MKDIR   = $(PY) "$(CMKHLP_HOME)/shellutil.py" mkdir
MV      = mv
RELPATH = $(PY) "$(CMKHLP_HOME)/shellutil.py" relpath
RM      = rm
RMDIR   = $(PY) "$(CMKHLP_HOME)/shellutil.py" rmdir -f
TOUCH   = touch
WHICH   = which

ifeq ($(HOST),Windows)
    PS       = ;
    NULL     = NUL
    OK       = SET _=
    ERR      = cmd.exe /C EXIT 1
    PY       = python.exe
    PY3      = py.exe -3
    CP       = $(PY) "$(CMKHLP_HOME)/shellutil.py" cp
    less     = more $(subst /,\\,$(1))
    MV       = $(PY) "$(CMKHLP_HOME)/shellutil.py" mv
    RM       = $(PY) "$(CMKHLP_HOME)/shellutil.py" rm
    TOUCH    = $(PY) "$(CMKHLP_HOME)/shellutil.py" touch
    WHICH    = where

    exists   = (IF NOT EXIST $(subst /,\\,$(1)) $(ERR))
    xargs_do = (FOR /F "tokens=*" %%x IN ('$(1)') DO $(subst {},%%x,$(2)))
    WINREG   = $(PY) "$(CMKHLP_HOME)/shellutil.py" winreg
endif

endif # __ENV_MK__
