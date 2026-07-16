#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe

"""The main entry of the `rsync-make` utility

This file is the part of the `cmkabe` library (https://github.com/spritetong/cmkabe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2024 spritetong@gmail.com.
"""

if __name__ == '__main__':
    import os
    import sys

    # Insert the home directory of `cmkabe` to sys.path
    cmkabe_home = os.path.dirname(os.path.realpath(__file__))
    if cmkabe_home not in sys.path:
        sys.path.insert(0, cmkabe_home)
    from pylib.rmake import RsyncMake

    try:
        sys.exit(RsyncMake.main(os.path.basename(__file__)))
    except Exception as e:
        if os.environ.get('CMKABE_DEBUG') in ('1', 'ON'):
            import traceback

            traceback.print_exc(file=sys.stderr)
        else:
            print('[ERROR] {}'.format(e), file=sys.stderr)
        sys.exit(1)
