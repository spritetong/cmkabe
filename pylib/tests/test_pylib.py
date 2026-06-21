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
