#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""The main entry of the shell utility

This file is the part of the cmake-abe library (https://github.com/spritetong/cmake-abe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2022 spritetong@gmail.com.
"""

if __name__ == '__main__':
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    from shlutilib import ShellCmd
    sys.exit(ShellCmd.main())
