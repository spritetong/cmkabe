import os
import sys
import tempfile
import time
import unittest
from typing import List

# Setup sys.path to find cmk package
cmk_parent = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__)))))
if cmk_parent not in sys.path:
    sys.path.insert(0, cmk_parent)

from cmk.pylib import sys_utils
from cmk.pylib.commands import ShellCmd
from cmk.pylib.target import TargetParser

class TestSysUtils(unittest.TestCase):
    def test_normpath(self) -> None:
        self.assertEqual(sys_utils.normpath("a/b/../c"), "a/c")
        self.assertEqual(sys_utils.normpath("a\\b\\c"), "a/b/c")

    def test_triple_parsing(self) -> None:
        triple = "x86_64-unknown-linux-gnu"
        arch, vendor, os_name, env = sys_utils.parse_triple(triple)
        self.assertEqual(arch, "x86_64")
        self.assertEqual(vendor, "unknown")
        self.assertEqual(os_name, "linux")
        self.assertEqual(env, "gnu")

        joined = sys_utils.join_triple(arch, vendor, os_name, env)
        self.assertEqual(joined, triple)

    def test_path_conversions(self) -> None:
        # Simple verification of return types and structure
        wsl = sys_utils.win2wsl_path("C:\\Users\\test")
        self.assertTrue(wsl.startswith("/mnt/c/") or wsl.startswith("/mnt/"))

        win = sys_utils.wsl2win_path("/mnt/c/Users/test")
        self.assertTrue(win.startswith("C:\\") or win.startswith("c:\\") or ":" in win)

    def test_need_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            src = os.path.join(tmpdir, "src.txt")
            dst = os.path.join(tmpdir, "dst.txt")

            with open(src, "w") as f:
                f.write("hello")

            # Destination doesn't exist, should need update
            self.assertTrue(sys_utils.need_update(src, dst))

            with open(dst, "w") as f:
                f.write("world")

            # Destination exists and is newer/same age, should not need update
            self.assertFalse(sys_utils.need_update(src, dst))

            # Make source newer
            time.sleep(0.1)
            with open(src, "w") as f:
                f.write("hello update")

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
                code = ShellCmd.main(['is_wsl_win_path', '/mnt/c/test'])
                self.assertEqual(code, 0)
                self.assertEqual(fake_out.getvalue().strip(), 'true')

            with patch('sys.stdout', new=io.StringIO()) as fake_out:
                code = ShellCmd.main(['is_wsl_win_path', '/home/user'])
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

    def test_update_libs(self) -> None:
        import io
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_dst:
            # Create src structure
            ext_dir = os.path.join(tmp_src, "ext")
            lib_dir = os.path.join(tmp_src, "lib")
            os.makedirs(ext_dir, exist_ok=True)
            os.makedirs(lib_dir, exist_ok=True)

            with open(os.path.join(ext_dir, "file1.txt"), "w") as f:
                f.write("content1")
            with open(os.path.join(ext_dir, "file2.txt"), "w") as f:
                f.write("content2")
            with open(os.path.join(lib_dir, "file3.txt"), "w") as f:
                f.write("content3")

            # Run update-libs
            # We map ext/* to dest root, and lib/file3.txt to target_lib
            files_arg = "ext/*;lib/file3.txt:target_lib"
            code = ShellCmd.main([
                'update-libs',
                '--url', tmp_src,
                '--dest-dir', tmp_dst,
                '--files', files_arg
            ])
            self.assertEqual(code, 0)

            # Check files in destination
            self.assertTrue(os.path.exists(os.path.join(tmp_dst, "file1.txt")))
            self.assertTrue(os.path.exists(os.path.join(tmp_dst, "file2.txt")))
            self.assertTrue(os.path.exists(os.path.join(tmp_dst, "target_lib", "file3.txt")))

            with open(os.path.join(tmp_dst, "file1.txt"), "r") as f:
                self.assertEqual(f.read(), "content1")
            with open(os.path.join(tmp_dst, "file2.txt"), "r") as f:
                self.assertEqual(f.read(), "content2")
            with open(os.path.join(tmp_dst, "target_lib", "file3.txt"), "r") as f:
                self.assertEqual(f.read(), "content3")

    def test_update_libs_rebuild(self) -> None:
        import io
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmp_src, tempfile.TemporaryDirectory() as tmp_dst:
            # Create src structure
            ext_dir = os.path.join(tmp_src, "ext")
            os.makedirs(ext_dir, exist_ok=True)
            with open(os.path.join(ext_dir, "file1.txt"), "w") as f:
                f.write("content1")

            # Mock subprocess.call
            with patch('subprocess.call', return_value=0) as mock_call:
                code = ShellCmd.main([
                    'update-libs',
                    '--url', tmp_src,
                    '--dest-dir', tmp_dst,
                    '--files', 'ext/*',
                    '--local-repo', tmp_src,
                    '--rebuild'
                ])
                self.assertEqual(code, 0)
                mock_call.assert_called_once_with('make DEBUG=0', shell=True, cwd=tmp_src)

            # Also check copied files
            self.assertTrue(os.path.exists(os.path.join(tmp_dst, "file1.txt")))
            with open(os.path.join(tmp_dst, "file1.txt"), "r") as f:
                self.assertEqual(f.read(), "content1")

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
                code = ShellCmd.main(['find-shell', 'exit-code'])
                self.assertEqual(code, 2)

            # 2. Test powershell.exe detection
            with patch.object(ShellCmd, '_detect_win_shell', return_value='powershell.exe'):
                with patch('sys.stdout', new=io.StringIO()) as fake_out:
                    code = ShellCmd.main(['find-shell'])
                    self.assertEqual(code, 0)
                    self.assertEqual(fake_out.getvalue(), 'powershell.exe')

                # Check exit-code mode
                code = ShellCmd.main(['find-shell', 'exit-code'])
                self.assertEqual(code, 1)

            # 3. Test cmd.exe default/fallback
            with patch.object(ShellCmd, '_detect_win_shell', return_value='cmd.exe'):
                with patch('sys.stdout', new=io.StringIO()) as fake_out:
                    code = ShellCmd.main(['find-shell'])
                    self.assertEqual(code, 0)
                    self.assertEqual(fake_out.getvalue(), 'cmd.exe')

                # Check exit-code mode
                code = ShellCmd.main(['find-shell', 'exit-code'])
                self.assertEqual(code, 0)


class TestTargetParser(unittest.TestCase):
    def test_parser_init(self) -> None:
        parser = TargetParser(
            target="x86_64-pc-windows-msvc",
            cmake_build_type="Release",
            cmake_build_dir="build",
            toolchain="msvc",
            rust_target="x86_64-pc-windows-msvc"
        )
        self.assertEqual(parser.target, "x86_64-pc-windows-msvc")
        self.assertEqual(parser.host_system, sys_utils.host_target_info()["host_system"])


if __name__ == '__main__':
    unittest.main()
