# -*- coding: utf-8 -*-
# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe

"""cmkabe python build-support library.

This package provides simulated shell utilities, target triple parsing,
and WSL2 synchronization functions.
"""

from .commands import ShellCmd
from .elf import ElfParser, modify_elf_file
from .rmake import RsyncMake
from .target import TargetParser

__all__ = (
    'ShellCmd',
    'TargetParser',
    'RsyncMake',
    'ElfParser',
    'modify_elf_file',
)
