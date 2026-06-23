#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix ELF dynamic library paths by removing directory paths and keeping only filenames.

This file is the part of the `cmkabe` library (https://github.com/spritetong/cmkabe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2024 spritetong@gmail.com.
"""

import os
import sys

# Ensure pylib can be imported if running directly or via symlink
script_dir = os.path.dirname(os.path.realpath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)

from pylib.elf import modify_elf_file


def main() -> None:
    """Main CLI entrypoint for elf_path_fixer."""
    import argparse

    parser = argparse.ArgumentParser(
        description='Fix ELF dynamic library paths by removing directory paths and keeping only filenames.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('elf_file', help='Path to the ELF executable file to process')
    parser.add_argument(
        '--target',
        '-t',
        required=True,
        dest='targets',
        action='append',
        help='Regular expression pattern to match in library paths (e.g. "aarch64-.*-linux-gnu/lib")',
    )
    parser.add_argument(
        '--fix-rpath',
        dest='fix_rpath',
        action='store_true',
        default=False,
        help='fix both RPATH and RUNPATH (default is False)',
    )
    parser.add_argument(
        '--no-backup',
        dest='backup',
        action='store_false',
        default=True,
        help='Do not create a backup of the original file',
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        default=False,
        help='Enable verbose output',
    )
    parser.add_argument(
        '--quiet',
        '-q',
        action='store_true',
        help='Suppress all output except errors',
    )

    args = parser.parse_intermixed_args()

    if not os.path.isfile(args.elf_file):
        if not args.quiet:
            print(f'[ERROR] File not found: {args.elf_file}', file=sys.stderr)
        sys.exit(1)

    try:
        with open(args.elf_file, 'rb') as f:
            magic = f.read(4)
            if magic != b'\x7fELF':
                if not args.quiet:
                    print(f'[ERROR] Not an ELF file: {args.elf_file}', file=sys.stderr)
                sys.exit(1)
    except Exception as e:
        if not args.quiet:
            print(f'[ERROR] Failed to read file: {e}', file=sys.stderr)
        sys.exit(1)

    if not args.quiet:
        print(f'[INFO] Processing ELF file: {args.elf_file}')
        print(f'[INFO] Target patterns: {args.targets}')

    success = modify_elf_file(
        args.elf_file,
        args.targets,
        fix_rpath=args.fix_rpath,
        create_backup=args.backup,
        verbose=args.verbose,
        quiet=args.quiet,
    )
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        if os.environ.get('CMKABE_DEBUG') == '1':
            import traceback

            traceback.print_exc(file=sys.stderr)
        else:
            print('[ERROR] {}'.format(e), file=sys.stderr)
        sys.exit(1)
