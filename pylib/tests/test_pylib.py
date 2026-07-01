import os
import sys
import tempfile
import time
import unittest

# Setup sys.path to find cmk package
cmk_parent = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
)
if cmk_parent not in sys.path:
    sys.path.insert(0, cmk_parent)

from .. import sys_utils
from .. import ShellCmd
from .. import TargetParser


class TestSysUtils(unittest.TestCase):
    def test_normpath(self) -> None:
        self.assertEqual(sys_utils.normpath('a/b/../c'), 'a/c')
        self.assertEqual(sys_utils.normpath('a\\b\\c'), 'a/b/c')

    def test_triple_parsing(self) -> None:
        triple = 'x86_64-unknown-linux-gnu'
        arch, vendor, os_name, env, version, version_sep = sys_utils.parse_triple(
            triple
        )
        self.assertEqual(arch, 'x86_64')
        self.assertEqual(vendor, 'unknown')
        self.assertEqual(os_name, 'linux')
        self.assertEqual(env, 'gnu')
        self.assertEqual(version, '')
        self.assertEqual(version_sep, '')

        joined = sys_utils.join_triple(arch, vendor, os_name, env, version, version_sep)
        self.assertEqual(joined, triple)

    def test_path_conversions(self) -> None:
        # Simple verification of return types and structure
        wsl = sys_utils.win2wsl_path('C:\\Users\\test')
        self.assertTrue(wsl.startswith('/mnt/c/') or wsl.startswith('/mnt/'))

        win = sys_utils.wsl2win_path('/mnt/c/Users/test')
        self.assertTrue(win.startswith('C:\\') or win.startswith('c:\\') or ':' in win)

    def test_need_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, 'src.txt')
            dst = os.path.join(tmpdir, 'dst.txt')

            with open(src, 'w') as f:
                f.write('hello')

            # Destination doesn't exist, should need update
            self.assertTrue(sys_utils.need_update(src, dst))

            with open(dst, 'w') as f:
                f.write('world')

            # Destination exists and is newer/same age, should not need update
            self.assertFalse(sys_utils.need_update(src, dst))

            # Make source newer
            time.sleep(0.1)
            with open(src, 'w') as f:
                f.write('hello update')

            self.assertTrue(sys_utils.need_update(src, dst))


class TestCommands(unittest.TestCase):
    def test_relpath(self) -> None:
        import io
        from unittest.mock import patch

        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            code = ShellCmd.main(['relpath', 'a/b/c', 'a'])
            self.assertEqual(code, 0)
            self.assertEqual(fake_out.getvalue().strip().replace('\\', '/'), 'b/c')

    def test_is_wsl_win_path(self) -> None:
        import io
        from unittest.mock import patch

        # Mock os.path.abspath so it doesn't prepend drive letters on Windows
        with patch('os.path.abspath', side_effect=lambda p: p):
            with patch('sys.stdout', new=io.StringIO()) as fake_out:
                code = ShellCmd.main(['is-wsl-win-path', '/mnt/c/test'])
                self.assertEqual(code, 0)
                self.assertEqual(fake_out.getvalue().strip(), 'true')

            with patch('sys.stdout', new=io.StringIO()) as fake_out:
                code = ShellCmd.main(['is-wsl-win-path', '/home/user'])
                self.assertEqual(code, 0)
                self.assertEqual(fake_out.getvalue().strip(), 'false')

    def test_cmpver(self) -> None:
        import io
        from unittest.mock import patch

        # 1.2.3 vs 1.2.4: 1.2.3 is smaller, so result is (2, "-")
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            code = ShellCmd.main(['cmpver', '1.2.3', '1.2.4'])
            self.assertEqual(code, 2)
            self.assertEqual(fake_out.getvalue().strip(), '-')

        # 2.0.0 vs 1.9.9: 2.0.0 is larger, so result is (1, "+")
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            code = ShellCmd.main(['cmpver', '2.0.0', '1.9.9'])
            self.assertEqual(code, 1)
            self.assertEqual(fake_out.getvalue().strip(), '+')

        # 1.0.0 vs 1.0.0: equal, so result is (0, "0")
        with patch('sys.stdout', new=io.StringIO()) as fake_out:
            code = ShellCmd.main(['cmpver', '1.0.0', '1.0.0'])
            self.assertEqual(code, 0)
            self.assertEqual(fake_out.getvalue().strip(), '0')

    def test_clone_libs(self) -> None:
        import io
        from unittest.mock import patch

        with (
            tempfile.TemporaryDirectory() as tmp_src,
            tempfile.TemporaryDirectory() as tmp_dst,
        ):
            # Create src structure
            ext_dir = os.path.join(tmp_src, 'ext')
            lib_dir = os.path.join(tmp_src, 'lib')
            os.makedirs(ext_dir, exist_ok=True)
            os.makedirs(lib_dir, exist_ok=True)

            with open(os.path.join(ext_dir, 'file1.txt'), 'w') as f:
                f.write('content1')
            with open(os.path.join(ext_dir, 'file2.txt'), 'w') as f:
                f.write('content2')
            with open(os.path.join(lib_dir, 'file3.txt'), 'w') as f:
                f.write('content3')

            # Run clone-libs
            # We map ext/* to dest root, and lib/file3.txt to target_lib
            files_arg = 'ext/*;lib/file3.txt:target_lib'
            code = ShellCmd.main(
                [
                    'clone-libs',
                    '--url',
                    tmp_src,
                    '--dest-dir',
                    tmp_dst,
                    '--files',
                    files_arg,
                ]
            )
            self.assertEqual(code, 0)

            # Check files in destination
            self.assertTrue(os.path.exists(os.path.join(tmp_dst, 'file1.txt')))
            self.assertTrue(os.path.exists(os.path.join(tmp_dst, 'file2.txt')))
            self.assertTrue(
                os.path.exists(os.path.join(tmp_dst, 'target_lib', 'file3.txt'))
            )

            with open(os.path.join(tmp_dst, 'file1.txt'), 'r') as f:
                self.assertEqual(f.read(), 'content1')
            with open(os.path.join(tmp_dst, 'file2.txt'), 'r') as f:
                self.assertEqual(f.read(), 'content2')
            with open(os.path.join(tmp_dst, 'target_lib', 'file3.txt'), 'r') as f:
                self.assertEqual(f.read(), 'content3')

    def test_clone_libs_rebuild(self) -> None:
        import io
        from unittest.mock import patch

        with (
            tempfile.TemporaryDirectory() as tmp_src,
            tempfile.TemporaryDirectory() as tmp_dst,
        ):
            # Create src structure
            ext_dir = os.path.join(tmp_src, 'ext')
            os.makedirs(ext_dir, exist_ok=True)
            with open(os.path.join(ext_dir, 'file1.txt'), 'w') as f:
                f.write('content1')

            # Mock subprocess.call
            with patch('subprocess.call', return_value=0) as mock_call:
                code = ShellCmd.main(
                    [
                        'clone-libs',
                        '--url',
                        tmp_src,
                        '--dest-dir',
                        tmp_dst,
                        '--files',
                        'ext/*',
                        '--local-repo',
                        tmp_src,
                        '--rebuild',
                    ]
                )
                self.assertEqual(code, 0)
                mock_call.assert_called_once_with(
                    'make DEBUG=0', shell=True, cwd=tmp_src
                )

            # Also check copied files
            self.assertTrue(os.path.exists(os.path.join(tmp_dst, 'file1.txt')))
            with open(os.path.join(tmp_dst, 'file1.txt'), 'r') as f:
                self.assertEqual(f.read(), 'content1')

    def test_find_shell_command(self) -> None:
        import io
        from unittest.mock import patch

        # Mock sys.platform to 'win32'
        with patch('sys.platform', 'win32'):
            # 1. Test pwsh.exe detection
            with patch.object(ShellCmd, '_detect_win_shell', return_value='pwsh.exe'):
                with patch('sys.stdout', new=io.StringIO()) as fake_out:
                    code = ShellCmd.main(['find-shell'])
                    self.assertEqual(code, 0)
                    self.assertEqual(fake_out.getvalue(), 'pwsh.exe')

                # Check exit-code mode
                code = ShellCmd.main(['find-shell', '--exit-code'])
                self.assertEqual(code, 2)

            # 2. Test powershell.exe detection
            with patch.object(
                ShellCmd, '_detect_win_shell', return_value='powershell.exe'
            ):
                with patch('sys.stdout', new=io.StringIO()) as fake_out:
                    code = ShellCmd.main(['find-shell'])
                    self.assertEqual(code, 0)
                    self.assertEqual(fake_out.getvalue(), 'powershell.exe')

                # Check exit-code mode
                code = ShellCmd.main(['find-shell', '--exit-code'])
                self.assertEqual(code, 1)

            # 3. Test cmd.exe default/fallback
            with patch.object(ShellCmd, '_detect_win_shell', return_value='cmd.exe'):
                with patch('sys.stdout', new=io.StringIO()) as fake_out:
                    code = ShellCmd.main(['find-shell'])
                    self.assertEqual(code, 0)
                    self.assertEqual(fake_out.getvalue(), 'cmd.exe')

                # Check exit-code mode
                code = ShellCmd.main(['find-shell', '--exit-code'])
                self.assertEqual(code, 0)

    def test_zig_clean_cache_verbose(self) -> None:
        import io
        from unittest.mock import patch, MagicMock

        # Mock stdout of subprocess.run for "zig env"
        mock_stdout = '{"global_cache_dir": "/mock/zig/cache"}'
        mock_res = MagicMock()
        mock_res.stdout = mock_stdout

        with (
            patch('subprocess.run', return_value=mock_res),
            patch('shutil.rmtree') as mock_rmtree,
            patch('os.path.isdir', return_value=True),
            patch('sys.stdout', new=io.StringIO()) as fake_out,
        ):
            # Run without -v
            code = ShellCmd.main(['zig-clean-cache'])
            self.assertEqual(code, 0)
            self.assertEqual(fake_out.getvalue().strip(), '')
            mock_rmtree.assert_called_once_with('/mock/zig/cache', ignore_errors=True)

        # Reset and run with -v
        with (
            patch('subprocess.run', return_value=mock_res),
            patch('shutil.rmtree') as mock_rmtree,
            patch('os.path.isdir', return_value=True),
            patch('sys.stdout', new=io.StringIO()) as fake_out,
        ):
            code = ShellCmd.main(['zig-clean-cache', '-v'])
            self.assertEqual(code, 0)
            self.assertEqual(
                fake_out.getvalue().strip().replace('\\', '/'),
                'Removing /mock/zig/cache',
            )
            mock_rmtree.assert_called_once_with('/mock/zig/cache', ignore_errors=True)

        # Run with --verbose
        with (
            patch('subprocess.run', return_value=mock_res),
            patch('shutil.rmtree') as mock_rmtree,
            patch('os.path.isdir', return_value=True),
            patch('sys.stdout', new=io.StringIO()) as fake_out,
        ):
            code = ShellCmd.main(['zig-clean-cache', '--verbose'])
            self.assertEqual(code, 0)
            self.assertEqual(
                fake_out.getvalue().strip().replace('\\', '/'),
                'Removing /mock/zig/cache',
            )


class TestElfPathFixer(unittest.TestCase):
    def _create_mock_elf(self, is_64bit: bool = True, is_le: bool = True) -> bytes:
        import struct

        endian = '<' if is_le else '>'
        bits = 64 if is_64bit else 32

        # 1. ELF Header
        header = bytearray(b'\x7fELF')
        header.append(2 if is_64bit else 1)  # class
        header.append(1 if is_le else 2)  # endianness
        header.extend(b'\x01\x00' + b'\x00' * 8)  # version + pad

        sh_offset = 128
        sh_entsize = 40 if bits == 32 else 64
        sh_num = 2  # Undefined section, and SHT_DYNAMIC section

        if bits == 32:
            # e_type, e_machine, e_version
            header.extend(struct.pack(f'{endian}HHI', 3, 62, 1))  # ET_DYN
            # e_entry, e_phoff
            header.extend(struct.pack(f'{endian}II', 0, 0))
            # e_shoff
            header.extend(struct.pack(f'{endian}I', sh_offset))
            # e_flags, e_ehsize, e_phentsize, e_phnum
            header.extend(struct.pack(f'{endian}IHHH', 0, 52, 0, 0))
            # e_shentsize, e_shnum, e_shstrndx
            header.extend(struct.pack(f'{endian}HHH', sh_entsize, sh_num, 0))
        else:
            # e_type, e_machine, e_version
            header.extend(struct.pack(f'{endian}HHI', 3, 62, 1))  # ET_DYN
            # e_entry, e_phoff
            header.extend(struct.pack(f'{endian}QQ', 0, 0))
            # e_shoff
            header.extend(struct.pack(f'{endian}Q', sh_offset))
            # e_flags, e_ehsize, e_phentsize, e_phnum
            header.extend(struct.pack(f'{endian}IHHH', 0, 64, 0, 0))
            # e_shentsize, e_shnum, e_shstrndx
            header.extend(struct.pack(f'{endian}HHH', sh_entsize, sh_num, 0))

        # Pad header to sh_offset
        header.extend(b'\x00' * (sh_offset - len(header)))

        # 2. Section Headers
        sh_null = b'\x00' * sh_entsize
        dyn_offset = 256
        dyn_size = 8 * 16 if bits == 32 else 16 * 16

        sh_dyn = bytearray()
        if bits == 32:
            sh_dyn.extend(struct.pack(f'{endian}IIII', 0, 6, 3, 0))
            sh_dyn.extend(struct.pack(f'{endian}IIII', dyn_offset, dyn_size, 0, 0))
            sh_dyn.extend(struct.pack(f'{endian}II', 4, 8))
        else:
            sh_dyn.extend(struct.pack(f'{endian}IIQQ', 0, 6, 3, 0))
            sh_dyn.extend(struct.pack(f'{endian}QQII', dyn_offset, dyn_size, 0, 0))
            sh_dyn.extend(struct.pack(f'{endian}QQ', 8, 16))

        sections = sh_null + sh_dyn

        # 3. Dynamic Section (starts at 256)
        strtab_offset = 512
        strtab_data = b'\x00/usr/lib/libtest.so\x00/path/to/runpath\x00'
        strtab_size = len(strtab_data)

        dyn_entries = [
            (5, strtab_offset),  # DT_STRTAB
            (10, strtab_size),  # DT_STRSZ
            (1, 1),  # DT_NEEDED -> "/usr/lib/libtest.so"
            (29, 21),  # DT_RUNPATH -> "/path/to/runpath"
            (0, 0),  # DT_NULL
        ]

        dyn_data = bytearray()
        for tag, val in dyn_entries:
            if bits == 32:
                dyn_data.extend(struct.pack(f'{endian}iI', tag, val))
            else:
                dyn_data.extend(struct.pack(f'{endian}qQ', tag, val))

        # Build full data
        full_data = bytearray(header)
        full_data[sh_offset : sh_offset + len(sections)] = sections

        if len(full_data) < dyn_offset:
            full_data.extend(b'\x00' * (dyn_offset - len(full_data)))
        full_data[dyn_offset : dyn_offset + len(dyn_data)] = dyn_data

        if len(full_data) < strtab_offset:
            full_data.extend(b'\x00' * (strtab_offset - len(full_data)))
        full_data[strtab_offset : strtab_offset + strtab_size] = strtab_data

        return bytes(full_data)

    def test_elf_parser_and_modifier(self) -> None:
        from ..elf import ElfParser, modify_elf_file

        mock_elf = self._create_mock_elf(is_64bit=True, is_le=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            elf_file = os.path.join(tmpdir, 'test.elf')
            with open(elf_file, 'wb') as f:
                f.write(mock_elf)

            # Test parsing
            with ElfParser(elf_file) as parser:
                libs = parser.get_needed_libraries()
                self.assertEqual(len(libs), 1)
                self.assertEqual(libs[0][0], '/usr/lib/libtest.so')
                paths = parser.get_rpath_runpath()
                self.assertEqual(len(paths), 1)
                self.assertEqual(paths[0][0], '/path/to/runpath')

            # Modify ELF
            res = modify_elf_file(
                elf_file,
                ['/usr/lib', '/path/to'],
                fix_rpath=True,
                create_backup=False,
                quiet=True,
            )
            self.assertTrue(res)

            # Verify changes
            with ElfParser(elf_file) as parser:
                libs = parser.get_needed_libraries()
                self.assertEqual(len(libs), 1)
                # Should be modified to "libtest.so"
                self.assertEqual(libs[0][0], 'libtest.so')
                paths = parser.get_rpath_runpath()
                # Since "/path/to/runpath" was the only element and matched target_patterns,
                # it was cleared to an empty string, which get_rpath_runpath() filters out.
                self.assertEqual(len(paths), 0)

    def test_elf_path_fixer_subcommand(self) -> None:
        mock_elf = self._create_mock_elf(is_64bit=True, is_le=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            elf_file = os.path.join(tmpdir, 'test.elf')
            with open(elf_file, 'wb') as f:
                f.write(mock_elf)

            # Run subcommand
            code = ShellCmd.main(
                [
                    'elf-path-fixer',
                    elf_file,
                    '-t',
                    '/usr/lib',
                    '-t',
                    '/path/to',
                    '--fix-rpath',
                    '--no-backup',
                    '--quiet',
                ]
            )
            self.assertEqual(code, 0)

            # Run again, should return 0 (no modifications needed)
            code = ShellCmd.main(
                [
                    'elf-path-fixer',
                    elf_file,
                    '-t',
                    '/usr/lib',
                    '-t',
                    '/path/to',
                    '--fix-rpath',
                    '--no-backup',
                    '--quiet',
                ]
            )
            self.assertEqual(code, 0)

    def test_elf_path_fixer_standalone_script(self) -> None:
        import subprocess

        mock_elf = self._create_mock_elf(is_64bit=True, is_le=True)
        with tempfile.TemporaryDirectory() as tmpdir:
            elf_file = os.path.join(tmpdir, 'test.elf')
            with open(elf_file, 'wb') as f:
                f.write(mock_elf)

            script_path = os.path.join(
                os.path.dirname(
                    os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
                ),
                'shlutil.py',
            )

            res = subprocess.run(
                [
                    sys.executable,
                    script_path,
                    'elf-path-fixer',
                    elf_file,
                    '-t',
                    '/usr/lib',
                    '--fix-rpath',
                    '--no-backup',
                    '--quiet',
                ],
                capture_output=True,
            )
            self.assertEqual(res.returncode, 0)


class TestTargetParser(unittest.TestCase):
    def test_parser_init(self) -> None:
        parser = TargetParser(
            target='x86_64-pc-windows-msvc',
        )
        self.assertEqual(parser.target, 'x86_64-pc-windows-msvc')
        self.assertEqual(
            parser.host.host_system, sys_utils.HostTargetInfo.host().host_system
        )

    def test_riscv_and_wasm_targets(self) -> None:
        # 1. riscv64 Linux
        parser = TargetParser(target='riscv64gc-unknown-linux-gnu')
        parser.parse()
        self.assertEqual(parser.arch, 'riscv64gc')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.zig_target, 'riscv64-linux-gnu')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 2. riscv64 Android NDK
        parser = TargetParser(target='riscv64-linux-android')
        parser.parse()
        self.assertEqual(parser.arch, 'riscv64gc')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.android_arch, 'riscv64')
        self.assertEqual(parser.android_abi, 'riscv64')
        self.assertEqual(parser.android_target, 'riscv64-linux-android')
        self.assertTrue(parser.android)
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 3. wasm32-unknown-unknown
        parser = TargetParser(target='wasm32-unknown-unknown')
        parser.parse()
        self.assertEqual(parser.arch, 'wasm32')
        self.assertEqual(parser.os, 'unknown')
        self.assertEqual(parser.zig_target, 'wasm32-freestanding')
        self.assertTrue(parser.wasm)
        self.assertFalse(parser.unix)

        # 4. wasm32-wasip1
        parser = TargetParser(target='wasm32-wasip1')
        parser.parse()
        self.assertEqual(parser.arch, 'wasm32')
        self.assertEqual(parser.os, 'wasip1')
        self.assertEqual(parser.zig_target, 'wasm32-wasi')
        self.assertTrue(parser.wasm)
        self.assertFalse(parser.unix)

        # 5. wasm32-wasip2
        parser = TargetParser(target='wasm32-wasip2')
        parser.parse()
        self.assertEqual(parser.arch, 'wasm32')
        self.assertEqual(parser.os, 'wasip2')
        self.assertEqual(parser.zig_target, 'wasm32-wasi')
        self.assertEqual(parser.cargo_target, 'wasm32-wasip2')
        self.assertTrue(parser.wasm)
        self.assertFalse(parser.unix)

        # 6. thumbv7neon-linux-androideabi
        parser = TargetParser(target='thumbv7neon-linux-androideabi')
        parser.parse()
        self.assertEqual(parser.arch, 'thumbv7neon')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.android_arch, 'armv7a')
        self.assertEqual(parser.android_abi, 'armeabi-v7a')
        self.assertEqual(parser.android_target, 'armv7a-linux-androideabi')
        self.assertEqual(parser.cargo_target, 'thumbv7neon-linux-androideabi')
        self.assertTrue(parser.android)
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 7. Linux with custom vendor (4 parts)
        parser = TargetParser(target='x86_64-myvendor-linux-gnu')
        parser.parse()
        self.assertEqual(parser.arch, 'x86_64')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.vendor, 'myvendor')
        self.assertEqual(parser.cargo_target, 'x86_64-unknown-linux-gnu')
        self.assertEqual(parser.zig_target, 'x86_64-linux-gnu')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 8. Linux with custom vendor (3 parts)
        parser = TargetParser(target='x86_64-myvendor-linux')
        parser.parse()
        self.assertEqual(parser.arch, 'x86_64')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.vendor, 'myvendor')
        self.assertEqual(parser.cargo_target, 'x86_64-unknown-linux')
        self.assertEqual(parser.zig_target, 'x86_64-linux')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 9. wasm32-wasip1-threads (multi-threaded WASI)
        parser = TargetParser(target='wasm32-wasip1-threads')
        parser.parse()
        self.assertEqual(parser.arch, 'wasm32')
        self.assertEqual(parser.os, 'wasip1')
        self.assertEqual(parser.env, 'threads')
        self.assertEqual(parser.zig_target, 'wasm32-wasi')
        self.assertEqual(parser.cargo_target, 'wasm32-wasip1-threads')
        self.assertTrue(parser.wasm)
        self.assertFalse(parser.unix)

        # 10. aarch64-unknown-none (freestanding/bare-metal)
        parser = TargetParser(target='aarch64-unknown-none')
        parser.parse()
        self.assertEqual(parser.arch, 'aarch64')
        self.assertEqual(parser.os, 'none')
        self.assertEqual(parser.zig_target, 'aarch64-none')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 11. riscv64gc-unknown-none-elf
        parser = TargetParser(target='riscv64gc-unknown-none-elf')
        parser.parse()
        self.assertEqual(parser.arch, 'riscv64gc')
        self.assertEqual(parser.os, 'none')
        self.assertEqual(parser.env, 'elf')
        self.assertEqual(parser.cargo_target, 'riscv64gc-unknown-none-elf')
        self.assertEqual(parser.zig_target, 'riscv64-none-elf')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 12. thumbv6m-none-eabi (embedded thumb ARM)
        parser = TargetParser(target='thumbv6m-none-eabi')
        parser.parse()
        self.assertEqual(parser.arch, 'thumbv6m')
        self.assertEqual(parser.os, 'none')
        self.assertEqual(parser.env, 'eabi')
        self.assertEqual(parser.cargo_target, 'thumbv6m-none-eabi')
        self.assertEqual(parser.zig_target, 'thumbv6m-none-eabi')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 13. x86_64-fortanix-unknown-sgx
        parser = TargetParser(target='x86_64-fortanix-unknown-sgx')
        parser.parse()
        self.assertEqual(parser.arch, 'x86_64')
        self.assertEqual(parser.vendor, 'fortanix')
        self.assertEqual(parser.os, 'unknown')
        self.assertEqual(parser.env, 'sgx')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 14. Linux with custom vendor and musl environment
        parser = TargetParser(target='aarch64-custom-linux-musl')
        parser.parse()
        self.assertEqual(parser.arch, 'aarch64')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.vendor, 'custom')
        self.assertEqual(parser.env, 'musl')
        self.assertEqual(parser.cargo_target, 'aarch64-unknown-linux-musl')
        self.assertEqual(parser.zig_target, 'aarch64-linux-musl')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 15. Linux with glibc version suffix
        parser = TargetParser(target='x86_64-unknown-linux-gnu.2.28', target_cc='zig')
        parser.parse()
        self.assertEqual(parser.arch, 'x86_64')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.vendor, 'unknown')
        self.assertEqual(parser.env, 'gnu')
        self.assertEqual(parser.version, '2.28')
        self.assertEqual(parser.version_sep, '.')
        self.assertEqual(parser.cargo_target, 'x86_64-unknown-linux-gnu')
        self.assertEqual(parser.zig_target, 'x86_64-linux-gnu.2.28')
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)

        # 16. Android with API version suffix
        parser = TargetParser(target='aarch64-linux-android24', target_cc='zig')
        parser.parse()
        self.assertEqual(parser.arch, 'aarch64')
        self.assertEqual(parser.os, 'linux')
        self.assertEqual(parser.vendor, '')
        self.assertEqual(parser.env, 'android')
        self.assertEqual(parser.version, '24')
        self.assertEqual(parser.version_sep, '')
        self.assertEqual(parser.cargo_target, 'aarch64-linux-android')
        self.assertEqual(parser.zig_target, 'aarch64-linux-android.24')
        self.assertEqual(parser.android_target, 'aarch64-linux-android')
        self.assertEqual(parser.android_arch, 'aarch64')
        self.assertEqual(parser.android_abi, 'arm64-v8a')
        self.assertTrue(parser.android)
        self.assertTrue(parser.unix)
        self.assertFalse(parser.wasm)


if __name__ == '__main__':
    unittest.main()
