#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""The main entry of the `rsync-make` utility

This file is the part of the `cmkabe` library (https://github.com/spritetong/cmkabe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2024 spritetong@gmail.com.
"""

if __name__ == '__main__':
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    from rmakelib import RsyncMake
    sys.exit(RsyncMake.main(os.path.basename(__file__)))
