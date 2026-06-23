# -*- coding: utf-8 -*-
"""Pure Python ELF file parser and path fixer."""

import os
import re
import shutil
import struct
import sys
import tempfile
from typing import Any, BinaryIO, List, Optional, Tuple


class ElfParser:
    """Pure Python ELF file parser."""

    EI_NIDENT: int = 16
    ET_DYN: int = 3

    DT_NEEDED: int = 1
    DT_RPATH: int = 15
    DT_RUNPATH: int = 29
    DT_STRTAB: int = 5
    DT_STRSZ: int = 10

    def __init__(self, elf_path: str) -> None:
        self.elf_path: str = elf_path
        self.elf_file: Optional[BinaryIO] = None
        self.endian: str = '<'
        self.bits: int = 32
        self.strtab_offset: int = 0
        self.strtab_size: int = 0
        self.dynamic_section: Optional[List[Tuple[int, int]]] = None
        self.string_table: Optional[bytes] = None

    def __enter__(self) -> 'ElfParser':
        self.elf_file = open(self.elf_path, 'rb')
        self._parse_elf_header()
        self._find_dynamic_section()
        self._load_string_table()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self.elf_file:
            self.elf_file.close()

    def _parse_elf_header(self) -> None:
        """Parse the ELF header to determine file characteristics."""
        assert self.elf_file is not None
        self.elf_file.seek(0)

        magic = self.elf_file.read(4)
        if magic != b'\x7fELF':
            raise ValueError('Not a valid ELF file')

        self.elf_file.seek(4)
        ei_class = ord(self.elf_file.read(1))
        self.bits = 64 if ei_class == 2 else 32

        ei_data = ord(self.elf_file.read(1))
        self.endian = '>' if ei_data == 2 else '<'

    def _find_dynamic_section(self) -> None:
        """Find the dynamic section in the ELF file."""
        assert self.elf_file is not None
        self.elf_file.seek(32 if self.bits == 32 else 40)
        e_shoff = struct.unpack(
            f'{self.endian}{"I" if self.bits == 32 else "Q"}',
            self.elf_file.read(4 if self.bits == 32 else 8),
        )[0]

        self.elf_file.seek(46 if self.bits == 32 else 58)
        e_shentsize = struct.unpack(f'{self.endian}H', self.elf_file.read(2))[0]
        e_shnum = struct.unpack(f'{self.endian}H', self.elf_file.read(2))[0]

        for i in range(e_shnum):
            self.elf_file.seek(e_shoff + i * e_shentsize + 4)
            sh_type = struct.unpack(f'{self.endian}I', self.elf_file.read(4))[0]

            if sh_type == 6:  # SHT_DYNAMIC
                self.elf_file.seek(
                    e_shoff + i * e_shentsize + (16 if self.bits == 32 else 24)
                )
                sh_offset = struct.unpack(
                    f'{self.endian}{"I" if self.bits == 32 else "Q"}',
                    self.elf_file.read(4 if self.bits == 32 else 8),
                )[0]
                sh_size = struct.unpack(
                    f'{self.endian}{"I" if self.bits == 32 else "Q"}',
                    self.elf_file.read(4 if self.bits == 32 else 8),
                )[0]

                self.dynamic_section = []
                entry_size = 8 if self.bits == 32 else 16
                num_entries = sh_size // entry_size

                for j in range(num_entries):
                    self.elf_file.seek(sh_offset + j * entry_size)
                    d_tag = struct.unpack(
                        f'{self.endian}{"i" if self.bits == 32 else "q"}',
                        self.elf_file.read(4 if self.bits == 32 else 8),
                    )[0]
                    d_val = struct.unpack(
                        f'{self.endian}{"I" if self.bits == 32 else "Q"}',
                        self.elf_file.read(4 if self.bits == 32 else 8),
                    )[0]

                    self.dynamic_section.append((d_tag, d_val))

                    if d_tag == self.DT_STRTAB:
                        self.strtab_offset = d_val
                    elif d_tag == self.DT_STRSZ:
                        self.strtab_size = d_val
                break

    def _load_string_table(self) -> None:
        """Load the dynamic string table."""
        assert self.elf_file is not None
        if self.strtab_offset and self.strtab_size:
            self.elf_file.seek(self.strtab_offset)
            self.string_table = self.elf_file.read(self.strtab_size)

    def _get_string(self, offset: int) -> Optional[str]:
        """Get a null-terminated string from the string table."""
        if not self.string_table:
            return None

        end = self.string_table.find(b'\0', offset)
        if end == -1:
            return None

        return self.string_table[offset:end].decode('utf-8', errors='replace')

    def get_needed_libraries(self) -> List[Tuple[str, int]]:
        """Get the list of needed libraries with their file offsets."""
        if not self.dynamic_section:
            return []

        needed_libs = []
        for d_tag, d_val in self.dynamic_section:
            if d_tag == self.DT_NEEDED:
                lib_name = self._get_string(d_val)
                if lib_name:
                    needed_libs.append((lib_name, d_val))

        return needed_libs

    def get_rpath_runpath(self) -> List[Tuple[str, int, int]]:
        """Get the RPATH and RUNPATH entries with their file offsets."""
        if not self.dynamic_section:
            return []

        paths = []
        for d_tag, d_val in self.dynamic_section:
            if d_tag in (self.DT_RPATH, self.DT_RUNPATH):
                path = self._get_string(d_val)
                if path:
                    paths.append((path, d_val, d_tag))

        return paths


def modify_elf_file(
    elf_path: str,
    target_patterns: List[str],
    *,
    fix_rpath: bool = False,
    create_backup: bool = True,
    verbose: bool = False,
    quiet: bool = False,
) -> bool:
    """Modify the ELF file to remove directory paths containing the target string."""

    def print_info(message: str, is_verbose: bool = False) -> None:
        if is_verbose or (not quiet and not is_verbose):
            print(f'[INFO] {message}')

    def print_error(message: str) -> None:
        if not quiet:
            print(f'[ERROR] {message}', file=sys.stderr)

    temp_dir = None
    temp_elf = None
    try:
        patterns = [re.compile(pat) for pat in target_patterns]

        with ElfParser(elf_path) as parser:
            needed_libs = parser.get_needed_libraries()
            paths = parser.get_rpath_runpath()
            strtab_offset = parser.strtab_offset

        print_info(f'Found {len(needed_libs)} dynamic libraries in {elf_path}')
        for lib, _ in needed_libs:
            print_info(f'  - {lib}', verbose)

        print_info(f'Found {len(paths)} RUNPATH/RPATH entries')
        for path, _, _ in paths:
            print_info(f'  - {path}', verbose)

        modified_libs = []
        for lib, offset in needed_libs:
            if any(pat.search(lib) is not None for pat in patterns):
                filename = os.path.basename(lib)
                modified_libs.append((lib, filename, offset))

        modified_paths = []
        for path, offset, tag_type in paths:
            if fix_rpath and any(pat.search(path) is not None for pat in patterns):
                new_paths = []
                for p in path.split(':'):
                    if any(pat.search(p) is not None for pat in patterns):
                        print_info(f'  Removing directory path from: {p}')
                    else:
                        new_paths.append(p)

                new_path = ':'.join(new_paths) if new_paths else ''
                modified_paths.append((path, new_path, offset))

        if not modified_libs and not modified_paths:
            print_info('No modifications needed')
            return True

        if create_backup:
            temp_dir = tempfile.mkdtemp()
            temp_elf = os.path.join(temp_dir, os.path.basename(elf_path))
            print_info('Creating temporary copy for backup')
            shutil.copy2(elf_path, temp_elf)

            backup_path = f'{elf_path}.backup'
            print_info(f'Creating backup at {backup_path}')
            shutil.copy2(elf_path, backup_path)

            file_to_modify = temp_elf
        else:
            print_info('Modifying original file directly (no backup)')
            file_to_modify = elf_path

        with open(file_to_modify, 'rb+') as f:
            for old_lib, new_lib, offset in modified_libs:
                abs_offset = strtab_offset + offset
                f.seek(abs_offset)
                actual_bytes = f.read(len(old_lib))
                actual_string = actual_bytes.decode('utf-8', errors='replace')
                if actual_string != old_lib:
                    print_error(
                        f"Verification failed: Expected '{old_lib}' but found '{actual_string}' at offset {abs_offset}"
                    )
                    continue

                print_info(f'Replacing {old_lib} with {new_lib}')
                f.seek(abs_offset)
                new_bytes = new_lib.encode('utf-8') + b'\0'
                old_bytes = old_lib.encode('utf-8') + b'\0'

                if len(new_bytes) > len(old_bytes):
                    print_error(
                        'New library name is longer than old name, cannot replace in-place'
                    )
                    continue

                if len(new_bytes) < len(old_bytes):
                    new_bytes += b'\0' * (len(old_bytes) - len(new_bytes))

                f.write(new_bytes)

            for old_path, new_path, offset in modified_paths:
                abs_offset = strtab_offset + offset
                f.seek(abs_offset)
                actual_string = f.read(len(old_path)).decode('utf-8', errors='replace')
                if actual_string != old_path:
                    print_error(
                        f"Verification failed: Expected '{old_path}' but found '{actual_string}' at offset {abs_offset}"
                    )
                    continue

                print_info(f'Replacing path {old_path} with {new_path}')
                f.seek(abs_offset)
                new_bytes = new_path.encode('utf-8') + b'\0'
                old_bytes = old_path.encode('utf-8') + b'\0'

                if len(new_bytes) > len(old_bytes):
                    print_error(
                        'New path is longer than old path, cannot replace in-place'
                    )
                    continue

                if len(new_bytes) < len(old_bytes):
                    new_bytes += b'\0' * (len(old_bytes) - len(new_bytes))

                f.write(new_bytes)

        if create_backup and temp_elf:
            print_info(f'Updating {elf_path} with modified version')
            shutil.copy2(temp_elf, elf_path)

        print_info('ELF file successfully updated')
        return True

    except Exception as e:
        print_error(f'Failed to modify ELF file: {e}')
        return False

    finally:
        if temp_dir:
            shutil.rmtree(temp_dir)
