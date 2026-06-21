#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""The main entry of the shell utility

This file is the part of the `cmkabe` library (https://github.com/spritetong/cmkabe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2024 spritetong@gmail.com.
"""

if __name__ == '__main__':
    import os
    import sys
    # Insert the parent directory of cmk to sys.path
    cmk_parent = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    if cmk_parent not in sys.path:
        sys.path.insert(0, cmk_parent)
    from cmk.pylib.commands import ShellCmd
    try:
        sys.exit(ShellCmd.main())
    except Exception as e:
        if os.environ.get("CMKABE_DEBUG") == "1":
            import traceback
            traceback.print_exc(file=sys.stderr)
        else:
            print("[ERROR] {}".format(e), file=sys.stderr)
        sys.exit(1)
