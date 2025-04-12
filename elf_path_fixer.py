#!/usr/bin/env python3
import sys
import os
import struct
import tempfile
import shutil
import re


def print_info(message, verbose=False):
    """Print information message with formatting."""
    if verbose or (not QUIET and not verbose):
        print(f"[INFO] {message}")


def print_error(message):
    """Print error message with formatting."""
    if not QUIET:
        print(f"[ERROR] {message}", file=sys.stderr)


class ElfParser:
    """Pure Python ELF file parser."""

    # ELF file header constants
    EI_NIDENT = 16
    ET_DYN = 3

    # Dynamic section entry types
    DT_NEEDED = 1
    DT_RPATH = 15
    DT_RUNPATH = 29
    DT_STRTAB = 5
    DT_STRSZ = 10

    def __init__(self, elf_path):
        self.elf_path = elf_path
        self.elf_file = None
        self.endian = '<'  # Default to little-endian
        self.bits = 32     # Default to 32-bit
        self.strtab_offset = 0
        self.strtab_size = 0
        self.dynamic_section = None
        self.string_table = None

    def __enter__(self):
        self.elf_file = open(self.elf_path, 'rb')
        self._parse_elf_header()
        self._find_dynamic_section()
        self._load_string_table()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.elf_file:
            self.elf_file.close()

    def _parse_elf_header(self):
        """Parse the ELF header to determine file characteristics."""
        self.elf_file.seek(0)

        # Check ELF magic number
        magic = self.elf_file.read(4)
        if magic != b'\x7fELF':
            raise ValueError("Not a valid ELF file")

        # Read EI_CLASS to determine 32/64 bit
        self.elf_file.seek(4)
        ei_class = ord(self.elf_file.read(1))
        self.bits = 64 if ei_class == 2 else 32

        # Read EI_DATA to determine endianness
        ei_data = ord(self.elf_file.read(1))
        self.endian = '>' if ei_data == 2 else '<'

    def _find_dynamic_section(self):
        """Find the dynamic section in the ELF file."""
        # Read section header table offset
        self.elf_file.seek(32 if self.bits == 32 else 40)
        e_shoff = struct.unpack(f"{self.endian}{'I' if self.bits == 32 else 'Q'}",
                                self.elf_file.read(4 if self.bits == 32 else 8))[0]

        # Read section header size and number
        self.elf_file.seek(46 if self.bits == 32 else 58)
        e_shentsize = struct.unpack(
            f"{self.endian}H", self.elf_file.read(2))[0]
        e_shnum = struct.unpack(f"{self.endian}H", self.elf_file.read(2))[0]

        # Read section header string table index
        e_shstrndx = struct.unpack(f"{self.endian}H", self.elf_file.read(2))[0]

        # Find the dynamic section
        for i in range(e_shnum):
            self.elf_file.seek(e_shoff + i * e_shentsize)

            # Read section type
            self.elf_file.seek(e_shoff + i * e_shentsize + 4)
            sh_type = struct.unpack(
                f"{self.endian}I", self.elf_file.read(4))[0]

            if sh_type == 6:  # SHT_DYNAMIC
                # Read section offset and size
                self.elf_file.seek(e_shoff + i * e_shentsize +
                                   (16 if self.bits == 32 else 24))
                sh_offset = struct.unpack(f"{self.endian}{'I' if self.bits == 32 else 'Q'}",
                                          self.elf_file.read(4 if self.bits == 32 else 8))[0]
                sh_size = struct.unpack(f"{self.endian}{'I' if self.bits == 32 else 'Q'}",
                                        self.elf_file.read(4 if self.bits == 32 else 8))[0]

                # Parse dynamic section
                self.dynamic_section = []
                entry_size = 8 if self.bits == 32 else 16
                num_entries = sh_size // entry_size

                for j in range(num_entries):
                    self.elf_file.seek(sh_offset + j * entry_size)

                    d_tag = struct.unpack(f"{self.endian}{'i' if self.bits == 32 else 'q'}",
                                          self.elf_file.read(4 if self.bits == 32 else 8))[0]
                    d_val = struct.unpack(f"{self.endian}{'I' if self.bits == 32 else 'Q'}",
                                          self.elf_file.read(4 if self.bits == 32 else 8))[0]

                    self.dynamic_section.append((d_tag, d_val))

                    # Find string table offset and size
                    if d_tag == self.DT_STRTAB:
                        self.strtab_offset = d_val
                    elif d_tag == self.DT_STRSZ:
                        self.strtab_size = d_val

                break

    def _load_string_table(self):
        """Load the dynamic string table."""
        if self.strtab_offset and self.strtab_size:
            # For simplicity, we're assuming the virtual address is the file offset
            # This is not always true, but works for many ELF files
            self.elf_file.seek(self.strtab_offset)
            self.string_table = self.elf_file.read(self.strtab_size)

    def _get_string(self, offset):
        """Get a null-terminated string from the string table."""
        if not self.string_table:
            return None

        end = self.string_table.find(b'\0', offset)
        if end == -1:
            return None

        return self.string_table[offset:end].decode('utf-8', errors='replace')

    def get_needed_libraries(self):
        """Get the list of needed libraries with their file offsets."""
        if not self.dynamic_section:
            return []

        needed_libs = []
        for d_tag, d_val in self.dynamic_section:
            if d_tag == self.DT_NEEDED:
                lib_name = self._get_string(d_val)
                if lib_name:
                    # Store the library name and its offset in the string table
                    needed_libs.append((lib_name, d_val))

        return needed_libs

    def get_rpath_runpath(self):
        """Get the RPATH and RUNPATH entries with their file offsets."""
        if not self.dynamic_section:
            return []

        paths = []
        for d_tag, d_val in self.dynamic_section:
            if d_tag in (self.DT_RPATH, self.DT_RUNPATH):
                path = self._get_string(d_val)
                if path:
                    # Store the path, its offset, and the tag type
                    paths.append((path, d_val, d_tag))

        return paths


def modify_elf_file(elf_path, target_patterns, create_backup=True, verbose=False):
    """Modify the ELF file to remove directory paths containing the target string."""
    try:
        temp_dir = None
        temp_elf = None

        # Compile the regular expression pattern
        patterns = [re.compile(pat) for pat in target_patterns]

        # First, analyze the original ELF file
        with ElfParser(elf_path) as parser:
            needed_libs = parser.get_needed_libraries()
            paths = parser.get_rpath_runpath()
            # Get string table offset for direct modifications
            strtab_offset = parser.strtab_offset

        print_info(f"Found {len(needed_libs)} dynamic libraries in {elf_path}")
        for lib, _ in needed_libs:
            print_info(f"  - {lib}", verbose)

        print_info(f"Found {len(paths)} RUNPATH/RPATH entries")
        for path, _, _ in paths:
            print_info(f"  - {path}", verbose)

        # Check if any modifications are needed
        modified_libs = []
        for lib, offset in needed_libs:
            if any(pat.search(lib) is not None for pat in patterns):
                filename = os.path.basename(lib)
                modified_libs.append((lib, filename, offset))

        modified_paths = []
        for path, offset, tag_type in paths:
            if any(pat.search(path) is not None for pat in patterns):
                new_paths = []
                for p in path.split(':'):
                    if any(pat.search(p) is not None for pat in patterns):
                        print_info(f"  Removing directory path from: {p}")
                    else:
                        new_paths.append(p)

                if new_paths:
                    new_path = ':'.join(new_paths)
                else:
                    new_path = ''

                modified_paths.append((path, new_path, offset))

        if not modified_libs and not modified_paths:
            print_info("No modifications needed")
            return True

        # Create a temporary file only if backup is requested
        if create_backup:
            temp_dir = tempfile.mkdtemp()
            temp_elf = os.path.join(temp_dir, os.path.basename(elf_path))
            print_info(f"Creating temporary copy for backup")
            shutil.copy2(elf_path, temp_elf)

            # Backup the original file
            backup_path = f"{elf_path}.backup"
            print_info(f"Creating backup at {backup_path}")
            shutil.copy2(elf_path, backup_path)

            # Now modify the temporary file
            file_to_modify = temp_elf
        else:
            # Modify the original file directly
            print_info("Modifying original file directly (no backup)")
            file_to_modify = elf_path

        # Now modify the ELF file directly at the string table offsets
        with open(file_to_modify, 'rb+') as f:
            # Replace library names
            for old_lib, new_lib, offset in modified_libs:
                # Calculate the absolute file offset in the string table
                abs_offset = strtab_offset + offset

                # Verify the old string before modification
                f.seek(abs_offset)
                actual_bytes = f.read(len(old_lib))
                actual_string = actual_bytes.decode('utf-8', errors='replace')
                if actual_string != old_lib:
                    print_error(
                        f"Verification failed: Expected '{old_lib}' but found '{actual_string}' at offset {abs_offset}")
                    continue

                print_info(f"Replacing {old_lib} with {new_lib}")

                # Seek to the position and write the new name
                f.seek(abs_offset)

                # Write the new library name with null terminator
                new_bytes = new_lib.encode('utf-8') + b'\0'
                old_bytes = old_lib.encode('utf-8') + b'\0'

                # Ensure we don't write beyond the original string's length
                if len(new_bytes) > len(old_bytes):
                    print_error(
                        f"New library name is longer than old name, cannot replace in-place")
                    continue

                # Pad with null bytes to maintain the same length
                if len(new_bytes) < len(old_bytes):
                    new_bytes += b'\0' * (len(old_bytes) - len(new_bytes))

                f.write(new_bytes)

            # Replace paths
            for old_path, new_path, offset in modified_paths:
                # Calculate the absolute file offset in the string table
                abs_offset = strtab_offset + offset

                # Verify the old string before modification
                f.seek(abs_offset)
                actual_string = f.read(len(old_path)).decode(
                    'utf-8', errors='replace')
                if actual_string != old_path:
                    print_error(
                        f"Verification failed: Expected '{old_path}' but found '{actual_string}' at offset {abs_offset}")
                    continue

                print_info(f"Replacing path {old_path} with {new_path}")

                # Seek to the position and write the new path
                f.seek(abs_offset)

                # Write the new path with null terminator
                new_bytes = new_path.encode('utf-8') + b'\0'
                old_bytes = old_path.encode('utf-8') + b'\0'

                # Ensure we don't write beyond the original string's length
                if len(new_bytes) > len(old_bytes):
                    print_error(
                        f"New path is longer than old path, cannot replace in-place")
                    continue

                # Pad with null bytes to maintain the same length
                if len(new_bytes) < len(old_bytes):
                    new_bytes += b'\0' * (len(old_bytes) - len(new_bytes))

                f.write(new_bytes)

        # If we created a temporary file, replace the original with it
        if create_backup and temp_elf:
            print_info(f"Updating {elf_path} with modified version")
            shutil.copy2(temp_elf, elf_path)

        print_info("ELF file successfully updated")
        return True

    except Exception as e:
        print_error(f"Failed to modify ELF file: {e}")
        return False

    finally:
        # Clean up temporary files
        if temp_dir:
            shutil.rmtree(temp_dir)


def main():
    # Use argparse for command line argument parsing
    import argparse

    parser = argparse.ArgumentParser(
        description='Fix ELF dynamic library paths by removing directory paths and keeping only filenames.',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        'elf_file', help='Path to the ELF executable file to process')
    parser.add_argument('--target', '-t',
                        required=True, dest="targets", action='append',
                        help='Regular expression pattern to match in library paths (e.g. "aarch64-.*-linux-gnu/lib")')
    parser.add_argument('--no-backup', dest='backup', action='store_false', default=True,
                        help='Do not create a backup of the original file')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('--quiet', '-q', action='store_true',
                        help='Suppress all output except errors')

    args = parser.parse_intermixed_args()

    # Set global quiet flag
    global QUIET
    QUIET = args.quiet

    # Check if the file exists
    if not os.path.isfile(args.elf_file):
        print_error(f"File not found: {args.elf_file}")
        sys.exit(1)

    # Check if the file is an ELF file
    try:
        with open(args.elf_file, 'rb') as f:
            magic = f.read(4)
            if magic != b'\x7fELF':
                print_error(f"Not an ELF file: {args.elf_file}")
                sys.exit(1)
    except Exception as e:
        print_error(f"Failed to read file: {e}")
        sys.exit(1)

    print_info(f"Processing ELF file: {args.elf_file}")
    print_info(f"Target patterns: {args.targets}")

    # Modify the ELF file
    if modify_elf_file(args.elf_file, args.targets, args.backup, args.verbose):
        sys.exit(0)
    else:
        sys.exit(1)


# Define global quiet flag
QUIET = False

if __name__ == "__main__":
    main()
