#!/usr/bin/env python3
# -*- coding: utf-8 -*-

if __name__ == '__main__':
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
    from shlutilib import RsyncMake
    sys.exit(RsyncMake.main(os.path.basename(__file__)))
