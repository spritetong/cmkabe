# -*- coding: utf-8 -*-
# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe

"""Simulated shell utilities for Makefile compatibility on Windows."""

import glob
import os
import sys
import time
from typing import Any, Generator, List, Optional

from .sys_utils import (
    HostTargetInfo,
    cmkabe_home,
    ndk_root,
    win2wsl_path,
    wsl2win_path,
)
from .zig import zig_build_wrapper, zig_clean_cache, zig_dll2lib, zig_patch


class ShellCmd:
    """Implement platform-independent shell commands."""

    EFAIL: int = 1
    ENOENT: int = 7
    EINVAL: int = 8
    EINTERRUPT: int = 254

    def __init__(self) -> None:
        pass

    def rm(
        self,
        paths: List[str],
        *,
        recursive: bool = False,
        force: bool = False,
        args_from_stdin: bool = False,
    ) -> int:
        """Simulate rm / rm -rf.

        Removes files, directories, or glob patterns. Automatically handles Windows read-only file system permissions.
        """

        def read_arg() -> Generator[str, None, None]:
            if args_from_stdin:
                import shlex

                while True:
                    try:
                        line = input()
                        lexer = shlex.shlex(line, posix=True)
                        lexer.whitespace_split = True
                        for arg in lexer:
                            yield arg
                    except EOFError:
                        break
            else:
                for arg in paths:
                    yield arg

        status = 0
        if not recursive:
            for pattern in read_arg():
                files = glob.glob(pattern)
                if not files and not force:
                    print(f'Can not find file {pattern}', file=sys.stderr)
                    return self.EFAIL
                for file in files:
                    try:
                        if os.path.isfile(file) or os.path.islink(file):
                            os.remove(file)
                        elif os.path.isdir(file):
                            os.rmdir(file)
                        else:
                            # On Windows, a link like a bad <JUNCTION> can't be accessed.
                            os.remove(file)
                    except OSError:
                        status = self.EFAIL
                        if force:
                            continue
                        print(f'Can not remove file {file}', file=sys.stderr)
                        return status
        else:
            for pattern in read_arg():
                files = glob.glob(pattern)
                if not files and not force:
                    print(f'Can not find file {pattern}', file=sys.stderr)
                    return self.EFAIL
                for file in files:
                    try:
                        if os.path.isfile(file) or os.path.islink(file):
                            os.remove(file)
                        elif os.path.isdir(file):
                            self._rmtree_try_chmod(file)
                        else:
                            # On Windows, a link like a bad <JUNCTION> can't be accessed.
                            os.remove(file)
                    except OSError:
                        status = self.EFAIL
                        if force:
                            continue
                        print(f'Can not remove tree {file}', file=sys.stderr)
                        return status
        return status

    def mkdir(self, paths: List[str], *, force: bool = False) -> int:
        """Simulate mkdir / mkdir -p.

        Creates directory paths. Always acts like Unix `mkdir -p` (creates parent directories, ignores existing paths).
        """
        status = 0
        for path in paths:
            ok = False
            for _ in range(100):
                try:
                    if not os.path.isdir(path):
                        os.makedirs(path, exist_ok=True)
                    ok = True
                except OSError as e:
                    import errno

                    if e.errno == errno.EEXIST:
                        if os.path.isdir(path):
                            ok = True
                            break
                        else:
                            time.sleep(0.001)
                            continue
                break
            if not ok:
                status = self.EFAIL
                if force:
                    continue
                print(f'Can not make directory {path}', file=sys.stderr)
                return status
        return status

    def rmdir(
        self,
        paths: List[str],
        *,
        remove_parents: bool = False,
        force: bool = False,
    ) -> int:
        """Simulate rmdir.

        Removes directory paths.
        """
        status = 0
        for path in paths:
            if not remove_parents:
                try:
                    os.rmdir(path)
                except OSError:
                    status = self.EFAIL
                    if force:
                        continue
                    print(f'Can not remove directory {path}', file=sys.stderr)
                    return status
            else:
                # If path is a directory, keep the original logic of "downward recursion" to
                # clean up empty subdirectories.
                if os.path.isdir(path):

                    def remove_parents_recur(p: str) -> None:
                        try:
                            for item in os.listdir(p):
                                directory = os.path.join(p, item)
                                if os.path.isdir(directory):
                                    remove_parents_recur(directory)
                                    if not os.listdir(directory):
                                        os.rmdir(directory)
                        except OSError:
                            pass

                    remove_parents_recur(path)

                curr: str = os.path.normpath(path)
                while curr:
                    # Once the source is traced back to the current directory '.' or
                    # the root directory '/', immediately cut it off and never delete it.
                    if curr in ('.', '..', '/'):
                        break
                    try:
                        os.rmdir(curr)
                    except OSError:
                        pass
                    parent = os.path.normpath(os.path.dirname(curr))
                    # Defense against infinite loops (e.g., when unable to split at the top level)
                    if parent == curr:
                        break
                    curr = parent
        return status

    def mv(self, paths: List[str], *, force: bool = False) -> int:
        """Simulate mv.

        Moves files, directories, or glob patterns to a destination path.
        """
        import shutil

        status = 0
        if len(paths) < 2:
            print(f'Invalid parameter {paths} for mv', file=sys.stderr)
            return self.EFAIL
        dst = paths[-1]
        files: List[str] = []
        for pattern in paths[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            print(f'{dst} is not a directory', file=sys.stderr)
            return self.EFAIL
        if not files and not force:
            print(f'Can not find file {paths[:-1]}', file=sys.stderr)
            return self.EFAIL
        for file in files:
            try:
                shutil.move(file, dst)
            except OSError:
                status = self.EFAIL
                if not force:
                    print(f'Can not move {file} to {dst}', file=sys.stderr)
                return status
        return status

    def cp(
        self,
        paths: List[str],
        *,
        recursive: bool = False,
        follow_symlinks: bool = True,
        force: bool = False,
    ) -> int:
        """Simulate cp.

        Copies files, directories, or glob patterns to a destination path.
        """
        import shutil

        def copy_file(src: str, dst: str) -> None:
            if os.path.islink(src) and not follow_symlinks:
                if os.path.isdir(dst):
                    dst = os.path.join(dst, os.path.basename(src))
                if os.path.lexists(dst):
                    os.unlink(dst)
                linkto = os.readlink(src)
                os.symlink(linkto, dst)
            else:
                shutil.copy2(src, dst)

        status = 0
        if len(paths) < 1:
            print(f'Invalid parameter {paths} for cp', file=sys.stderr)
            return self.EFAIL
        args_copy = list(paths)
        if len(args_copy) == 1:
            args_copy.append('.')
        dst = args_copy[-1]
        files: List[str] = []
        for pattern in args_copy[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            print(f'{dst} is not a directory', file=sys.stderr)
            return self.EFAIL
        if not files and not force:
            print(f'Can not find file {args_copy[:-1]}', file=sys.stderr)
            return self.EFAIL
        for file in files:
            try:
                if os.path.isfile(file):
                    copy_file(file, dst)
                elif recursive:
                    shutil.copytree(
                        file,
                        os.path.join(dst, os.path.basename(file)),
                        copy_function=copy_file,
                        dirs_exist_ok=True,
                    )
            except OSError:
                status = self.EFAIL
                if not force:
                    print(f'Can not copy {file} to {dst}', file=sys.stderr)
                return status
        return status

    def mklink(
        self,
        link: str,
        target: str,
        *,
        symlinkd: bool = False,
        force: bool = False,
    ) -> int:
        """Simulate symlink creation.

        Creates file or directory symbolic links.
        """
        status = 0
        try:
            target = target.replace('/', os.sep).replace('\\', os.sep)
            os.symlink(
                target,
                link,
                target_is_directory=symlinkd or os.path.isdir(target),
            )
        except OSError:
            status = self.EFAIL
            if not force:
                print(
                    f'Can not create symbolic link: {link} -> {target}',
                    file=sys.stderr,
                )
        return status

    def fix_symlink(self, patterns: List[str]) -> int:
        """Fix Windows/WSL broken symbolic links."""
        is_wsl = 'WSL_DISTRO_NAME' in os.environ

        def walk(pattern: str) -> None:
            for file in glob.glob(pattern):
                try:
                    if os.path.isdir(file):
                        walk(os.path.join(file, '*'))
                        continue
                    is_link = os.path.islink(file)
                    if is_link and is_wsl:
                        # On WSL Linux, rebuild all file links.
                        target = os.readlink(file)
                        os.unlink(file)
                        os.symlink(target, file)
                    elif not is_link and not os.path.isfile(file):
                        # On Windows, a link like a bad <JUNCTION> can't be accessed.
                        # Try to find its target and rebuild it.
                        for target in glob.glob(os.path.splitext(file)[0] + '.*'):
                            if os.path.isfile(target) and not os.path.islink(target):
                                os.unlink(file)
                                os.symlink(os.path.basename(target), file)
                                break
                except OSError:
                    print(
                        f'Can not fix the bad symbolic link {file}',
                        file=sys.stderr,
                    )
                    raise

        try:
            for pattern in patterns:
                walk(pattern)
            return 0
        except OSError:
            return self.EFAIL

    def cwd(self) -> int:
        """Print current working directory in Unix format (forward slashes)."""
        print(os.getcwd().replace('\\', '/'), end='')
        return 0

    def mydir(self) -> int:
        """Print the directory of `cmkabe` utility in Unix format (forward slashes)."""
        path = cmkabe_home()
        if os.path.isdir(path):
            path = os.path.realpath(path)
        else:
            path = os.getcwd()
        print(path.replace('\\', '/'), end='')
        return 0

    def relpath(self, path: str, start: Optional[str] = None) -> int:
        """Print relative path."""
        try:
            res = os.path.relpath(path, start)
        except (IndexError, ValueError, OSError):
            res = path
        print(res.replace('\\', '/'), end='')
        return 0

    def win2wsl_path(self, path: Optional[str] = None) -> int:
        """Convert Windows path to WSL."""
        res = win2wsl_path(path if path else os.getcwd())
        print(res, end='')
        return 0

    def wsl2win_path(self, path: Optional[str] = None) -> int:
        """Convert WSL path to Windows."""
        res = wsl2win_path(path if path else os.getcwd())
        print(res, end='')
        return 0

    def is_wsl_win_path(self, path: Optional[str] = None) -> int:
        """Check if path is a WSL mapped Windows drive path (/mnt/*)."""
        p = os.path.abspath(path) if path else os.getcwd()
        p = p.replace('\\', '/')
        if len(p) >= 6 and p.startswith('/mnt/') and p[5].isalpha():
            if len(p) == 6 or p[6] == '/':
                print('true', end='')
                return 0
        print('false', end='')
        return 0

    def touch(self, paths: List[str], *, force: bool = False) -> int:
        """Simulate touch."""
        status = 0
        for pattern in paths:
            files = glob.glob(pattern)
            if not files:
                try:
                    open(pattern, 'ab').close()
                except OSError:
                    status = self.EFAIL
                    if force:
                        continue
                    print(f'Can not create file {pattern}', file=sys.stderr)
                    return status
            for file in files:
                try:
                    os.utime(file, None)
                except OSError:
                    status = self.EFAIL
                    if force:
                        continue
                    print(f'Can not touch file {file}', file=sys.stderr)
                    return status
        return status

    def timestamp(self) -> int:
        """Print current epoch timestamp."""
        print(time.time(), end='')
        return 0

    def cmpver(self, v1: str, v2: str, *, force: bool = False) -> int:
        """Compare two version strings."""
        try:
            parsed_v1 = [int(x) for x in (v1 + '.0.0.0').split('.')[:4]]
            parsed_v2 = [int(x) for x in (v2 + '.0.0.0').split('.')[:4]]
            if parsed_v1 > parsed_v2:
                result = (1, '+')
            elif parsed_v1 == parsed_v2:
                result = (0, '0')
            else:
                result = (2, '-')
        except (IndexError, ValueError):
            result = (self.EINVAL, '')
            print('Invalid arguments', file=sys.stderr)
        print(result[1], end='')
        return 0 if force else result[0]

    def winreg(self, keys: List[str]) -> int:
        """Query registry value on Windows."""
        try:
            value = None
            try:
                import winreg as _winreg

                root_keys = {
                    'HKEY_CLASSES_ROOT': _winreg.HKEY_CLASSES_ROOT,
                    'HKEY_CURRENT_USER': _winreg.HKEY_CURRENT_USER,
                    'HKEY_LOCAL_MACHINE': _winreg.HKEY_LOCAL_MACHINE,
                    'HKEY_USERS': _winreg.HKEY_USERS,
                    'HKEY_PERFORMANCE_DATA': _winreg.HKEY_PERFORMANCE_DATA,
                    'HKEY_CURRENT_CONFIG': _winreg.HKEY_CURRENT_CONFIG,
                }
                for arg in keys:
                    keys_split = arg.split('\\')
                    key = root_keys[keys_split[0]]
                    sub_key = '\\'.join(keys_split[1:-1])
                    value_name = keys_split[-1]
                    try:
                        with _winreg.OpenKey(
                            key, sub_key, 0, _winreg.KEY_READ | _winreg.KEY_WOW64_64KEY
                        ) as rkey:
                            value = _winreg.QueryValueEx(rkey, value_name)[0]
                            if value:
                                break
                    except OSError:
                        pass
            except ImportError:
                pass
            print(value or '', end='')
            return 0
        except (NameError, AttributeError):
            return self.EFAIL

    def ndk_root(self) -> int:
        """Print Android NDK root directory path."""
        root_dir = ndk_root()
        if root_dir:
            print(root_dir, end='')
            return 0
        return self.ENOENT

    def cargo_exec(self, cargo_toml_path: str, command: List[str]) -> int:
        """Simulate cargo build environment execution."""
        import subprocess

        ws_dir = os.environ.get('CARGO_WORKSPACE_DIR', '.')
        cfg_file = (
            cargo_toml_path
            if cargo_toml_path.endswith('.toml')
            else os.path.join(cargo_toml_path, 'Cargo.toml')
        )
        cargo_toml = (
            os.path.join(ws_dir, cfg_file)
            if os.path.isfile(os.path.join(ws_dir, cfg_file))
            else cfg_file
        )
        try:
            import toml

            cargo = toml.load(cargo_toml)
        except ImportError:
            try:
                tomllib = __import__('tomllib')
                with open(cargo_toml, mode='rb') as fp:
                    cargo = tomllib.load(fp)
            except ImportError:
                print(
                    'toml is not installed. Please execute: pip install toml',
                    file=sys.stderr,
                )
                return self.EFAIL
        package = cargo['package']
        os.environ['CARGO_CRATE_NAME'] = package['name']
        os.environ['CARGO_PKG_NAME'] = package['name']
        os.environ['CARGO_PKG_VERSION'] = package['version']
        os.environ['CARGO_MAKE_TIMESTAMP'] = f'{time.time()}'
        return subprocess.call(' '.join(command), shell=True)

    def upload(self, ftp_path: str, files: List[str]) -> int:
        """Upload file via FTP or SFTP."""
        import urllib.parse

        parsed = urllib.parse.urlparse(ftp_path)
        if not parsed.hostname:
            print(f'No hostname in {ftp_path}', file=sys.stderr)
            return self.EINVAL
        scheme = parsed.scheme
        hostname = parsed.hostname
        port = int(parsed.port) if parsed.port else 0
        url = scheme + '://' + (f'{hostname}:{port}' if port else hostname)
        username = parsed.username or ''
        password = parsed.password or ''
        remote_dir = parsed.path or '/'

        ftp = None
        ssh = None
        sftp = None
        if scheme in ['ftp', 'ftps']:
            import ftplib

            ftp = ftplib.FTP()
            ftp.connect(hostname, port or 21)
            ftp.login(username, password)
            if scheme == 'ftps':
                ftp.prot_p()  # pyright: ignore[reportAttributeAccessIssue]
            ftp.set_pasv(True)
        elif scheme == 'sftp':
            try:
                import paramiko
            except ImportError:
                print(
                    'paramiko is not installed. Please execute: pip install paramiko',
                    file=sys.stderr,
                )
                return self.EFAIL
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname, port or 22, username, password)
            sftp = ssh.open_sftp()
        else:
            print(f'Unsupported protocol: {scheme}', file=sys.stderr)
            return self.EINVAL

        for item in files:
            pair = item.split('=')
            for local_path in glob.glob(pair[-1]):
                if not os.path.isdir(local_path):
                    remote_path = (
                        os.path.basename(local_path) if len(pair) == 1 else pair[0]
                    )
                    if not remote_path.startswith('/'):
                        remote_path = '/'.join([remote_dir, remote_path])
                    if remote_path.endswith('/'):
                        remote_path = '/'.join(
                            [remote_path, os.path.basename(local_path)]
                        )
                    while '//' in remote_path:
                        remote_path = remote_path.replace('//', '/')

                    print(f'Upload "{local_path}"')
                    print(
                        f'    to "{url}{remote_path}" ...',
                        end='',
                        flush=True,
                    )
                    if ftp is not None:
                        with open(local_path, 'rb') as fp:
                            ftp.storbinary(
                                f'STOR {remote_path}',
                                fp,
                                32 * 1024,
                                callback=lambda _sent: print('.', end='', flush=True),
                            )
                    elif sftp is not None:
                        sftp.put(local_path, remote_path)
                    print('')
        print('Done.', flush=True)

        if ftp is not None:
            ftp.quit()
        if sftp is not None:
            sftp.close()
        if ssh is not None:
            ssh.close()
        return 0

    def build_target_deps(self, params: List[str]) -> int:
        """Call TargetParser to build target dependencies."""
        from .target import TargetParser

        try:
            args = {
                k.strip().lower(): v
                for (k, v) in map(lambda x: x.split('=', 1), params)
            }
            TargetParser(**args).parse().build()
        except Exception as e:
            if os.environ.get('CMKABE_DEBUG') == '1':
                import traceback

                traceback.print_exc(file=sys.stderr)
            else:
                print(
                    f'[ERROR] Failed to build target dependencies: {e}',
                    file=sys.stderr,
                )
            return 1
        return 0

    def dll2lib(
        self, dll_path: str, out_path: Optional[str] = None, force: bool = False
    ) -> int:
        """Call dll2lib to generate MSVC import libraries from DLLs."""
        return zig_dll2lib(
            dll_path,
            out_path=out_path,
            force=force,
        )

    def zig_patch(self, zig_root: Optional[str] = None) -> int:
        """Call zig_patch to patch Zig source libraries to hide runtime exports."""
        zig_patch(zig_root)
        return 0

    def zig_clean_cache(
        self, zig_root: Optional[str] = None, verbose: bool = False
    ) -> int:
        """Call zig_clean_cache to clean Zig global cache."""
        zig_clean_cache(zig_root, verbose=verbose)
        return 0

    def zig_build_wrapper(
        self,
        zig_root: Optional[str] = None,
        out_dir: Optional[str] = None,
        prefix: str = 'zig',
        force: bool = False,
        vcpkg: bool = False,
    ) -> int:
        return zig_build_wrapper(
            zig_root=zig_root,
            out_dir=out_dir,
            prefix=prefix,
            force=force,
            vcpkg=vcpkg,
        )

    def vcpkg_host_triplet(self) -> int:
        print(HostTargetInfo.vcpkg_host_triplet(), end='')
        return 0

    def vcpkg_create_triplet_cache(
        self,
        vcpkg_root: Optional[str] = None,
        triplet_cache_dir: Optional[str] = None,
        triplets: Optional[List[str]] = None,
        debug: bool = False,
        static_crt: bool = False,
        static_lib: bool = False,
    ) -> int:
        xpatch_dir = os.path.join(vcpkg_root, 'xpatch') if vcpkg_root else cmkabe_home()
        cache_dir = triplet_cache_dir or os.path.join(xpatch_dir, '.cache', 'triplets')
        found_any = False
        for triplet in triplets or [HostTargetInfo.vcpkg_host_triplet()]:
            triplet_cmake = triplet + '.cmake'
            found_triplet = False
            for dir in ['triplets', '../triplets', '../triplets/community']:
                path = os.path.join(xpatch_dir, dir, triplet_cmake)
                if os.path.isfile(path):
                    with open(path) as f:
                        lines = [x.rstrip() for x in f.readlines()]
                    lines.append('# XPATCH: {{{')
                    if debug:
                        lines.append('unset(VCPKG_BUILD_TYPE)')
                    else:
                        lines.append('set(VCPKG_BUILD_TYPE release)')
                    lines.append(
                        'set(VCPKG_CRT_LINKAGE {})'.format(
                            'static' if static_crt else 'dynamic'
                        )
                    )
                    lines.append(
                        'set(VCPKG_LIBRARY_LINKAGE {})'.format(
                            'static' if static_lib else 'dynamic'
                        )
                    )
                    lines.append('include("${VCPKG_ROOT_DIR}/xpatch/.triplet.cmake")')
                    lines.append('# }}}')
                    content = '\n'.join(lines).encode('utf-8')

                    cache_path = os.path.join(cache_dir, triplet_cmake)
                    try:
                        with open(cache_path, 'rb') as f:
                            existent = f.read()
                    except OSError:
                        existent = b''
                    if content != existent:
                        try:
                            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
                            with open(cache_path, 'wb') as f:
                                f.write(content)
                        except OSError:
                            return self.EFAIL
                    found_triplet = True
                    found_any = True
                    break
            if not found_triplet and triplets:
                print(
                    f"Warning: Triplet file '{triplet_cmake}' not found.",
                    file=sys.stderr,
                )
        return 0 if found_any else self.ENOENT

    def _detect_win_shell(self) -> str:
        """Detect the parent/ancestor shell on Windows."""
        import ctypes
        from ctypes import wintypes

        try:
            kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
            ntdll = ctypes.WinDLL('ntdll', use_last_error=True)
        except (AttributeError, OSError):
            return 'cmd.exe'

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        ProcessBasicInformation = 0

        class PROCESS_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ('ExitStatus', ctypes.c_long),
                ('PebBaseAddress', ctypes.c_void_p),
                ('AffinityMask', ctypes.c_void_p),
                ('BasePriority', ctypes.c_long),
                ('UniqueProcessId', ctypes.c_void_p),
                ('InheritedFromUniqueProcessId', ctypes.c_void_p),
            ]

        try:
            ntdll.NtQueryInformationProcess.argtypes = [
                wintypes.HANDLE,
                ctypes.c_int,
                ctypes.c_void_p,
                wintypes.ULONG,
                ctypes.POINTER(wintypes.ULONG),
            ]
            ntdll.NtQueryInformationProcess.restype = ctypes.c_long

            kernel32.OpenProcess.argtypes = [
                wintypes.DWORD,
                wintypes.BOOL,
                wintypes.DWORD,
            ]
            kernel32.OpenProcess.restype = wintypes.HANDLE

            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE,
                wintypes.DWORD,
                wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD),
            ]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        except (AttributeError, TypeError):
            return 'cmd.exe'

        def get_process_parent_and_name(pid):
            h_process = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION, False, pid
            )
            if not h_process:
                return None, None
            ppid = None
            exe_name = ''
            try:
                pbi = PROCESS_BASIC_INFORMATION()
                return_length = wintypes.ULONG(0)
                status = ntdll.NtQueryInformationProcess(
                    h_process,
                    ProcessBasicInformation,
                    ctypes.byref(pbi),
                    ctypes.sizeof(pbi),
                    ctypes.byref(return_length),
                )
                if status == 0:
                    ppid = pbi.InheritedFromUniqueProcessId

                size = wintypes.DWORD(1024)
                buffer = ctypes.create_unicode_buffer(size.value)
                if kernel32.QueryFullProcessImageNameW(
                    h_process, 0, buffer, ctypes.byref(size)
                ):
                    exe_name = os.path.basename(buffer.value).lower()
            finally:
                kernel32.CloseHandle(h_process)
            return ppid, exe_name

        chain = []
        try:
            current_pid = kernel32.GetCurrentProcessId()
            visited = set()

            ppid, _ = get_process_parent_and_name(current_pid)
            current_pid = ppid

            while current_pid and current_pid not in visited and current_pid > 4:
                visited.add(current_pid)
                next_ppid, name = get_process_parent_and_name(current_pid)
                if not name:
                    break
                chain.append((current_pid, name))
                if name in ['explorer.exe', 'services.exe', 'wininit.exe']:
                    break
                current_pid = next_ppid
        except Exception:
            return 'cmd.exe'

        topmost_make_idx = -1
        for i, (pid, name) in enumerate(chain):
            if name == 'make.exe' or name == 'gmake.exe' or name.endswith('make.exe'):
                topmost_make_idx = i

        if topmost_make_idx != -1:
            upper_ancestors = chain[topmost_make_idx + 1 :]
            for pid, name in upper_ancestors:
                if name in ['pwsh.exe', 'powershell.exe']:
                    return name
            return 'cmd.exe'
        else:
            for pid, name in chain:
                if name in ['pwsh.exe', 'powershell.exe']:
                    return name
            return 'cmd.exe'

    def find_shell(self, exit_code: bool = False) -> int:
        """Find the shell matching the parent/ancestor terminal environment."""
        is_exit_code_mode = exit_code

        if sys.platform != 'win32':
            if is_exit_code_mode:
                return 0
            print(os.environ.get('SHELL', 'bash'), end='')
            return 0

        shell_exe = self._detect_win_shell()

        if is_exit_code_mode:
            if shell_exe == 'pwsh.exe':
                return 2
            elif shell_exe == 'powershell.exe':
                return 1
            else:
                return 0

        print(shell_exe, end='')
        return 0

    def elf_path_fixer(
        self,
        elf_file: str,
        targets: List[str],
        *,
        fix_rpath: bool = False,
        create_backup: bool = True,
        verbose: bool = False,
        quiet: bool = False,
    ) -> int:
        """Fix ELF dynamic library paths by removing directory paths."""
        from .elf import modify_elf_file

        success = modify_elf_file(
            elf_file,
            targets,
            fix_rpath=fix_rpath,
            create_backup=create_backup,
            verbose=verbose,
            quiet=quiet,
        )
        return 0 if success else self.EFAIL

    def clone_libs(
        self,
        *,
        dest_dir: str,
        url: str = '',
        local_repo: str = '',
        files: str = '',
        tmp_dir: str = '.libs',
        rebuild: Optional[str] = None,
    ) -> int:
        """Download or rebuild external libraries and copy files."""
        import shutil
        import subprocess

        if not dest_dir:
            print('Error: --dest-dir is required', file=sys.stderr)
            return self.EINVAL

        if not local_repo and url:
            base = os.path.basename(url)
            if base.endswith('.git'):
                base = base[:-4]
            local_repo = os.path.join('..', base)

        if os.path.exists(tmp_dir):
            try:
                self._rmtree_try_chmod(tmp_dir)
            except Exception:
                pass

        src_dir = None
        need_cleanup = False

        if rebuild is not None:
            print(f"Rebuilding in local repository '{local_repo}'...")
            ret = subprocess.call(
                ' '.join(filter(None, ['make', rebuild, 'DEBUG=0'])),
                shell=True,
                cwd=local_repo,
            )
            if ret != 0:
                print(
                    f"Error: rebuild in '{local_repo}' failed with exit code {ret}",
                    file=sys.stderr,
                )
                return self.EFAIL
            src_dir = local_repo
        elif url and glob.glob(url):
            matched = glob.glob(url)
            src_dir = matched[0]
            print(f"Copying from local path '{src_dir}'...")
        else:
            print(f"Cloning from '{url}' to '{tmp_dir}'...")
            ret = subprocess.call(
                f'git clone --depth 1 --branch master "{url}" "{tmp_dir}"', shell=True
            )
            if ret != 0:
                print(f'Error: git clone failed with exit code {ret}', file=sys.stderr)
                return self.EFAIL
            src_dir = tmp_dir
            need_cleanup = True

        def copy_item(src: str, dst_dir: str) -> None:
            name = os.path.basename(src)
            dst = os.path.join(dst_dir, name)
            if os.path.islink(src):
                if os.path.lexists(dst):
                    try:
                        os.unlink(dst)
                    except OSError:
                        try:
                            os.remove(dst)
                        except OSError:
                            shutil.rmtree(dst, ignore_errors=True)
                linkto = os.readlink(src)
                os.symlink(linkto, dst)
            elif os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
                else:
                    shutil.copytree(src, dst, symlinks=True)
            else:
                if os.path.exists(dst) or os.path.islink(dst):
                    try:
                        os.remove(dst)
                    except OSError:
                        pass
                shutil.copy2(src, dst)

        mapping_list = [f.strip() for f in files.split(';') if f.strip()]
        for m in mapping_list:
            parts = m.split(':', 1)
            src_part = parts[0]
            dst_part = parts[1] if len(parts) > 1 else ''

            target_dest_dir = os.path.join(dest_dir, dst_part)
            os.makedirs(target_dest_dir, exist_ok=True)

            pattern = os.path.join(src_dir, src_part)
            matched_files = glob.glob(pattern)
            if not matched_files:
                print(
                    f"Warning: pattern '{src_part}' matched no files in source directory '{src_dir}'",
                    file=sys.stderr,
                )
                continue

            for f in matched_files:
                copy_item(f, target_dest_dir)

            try:
                self.fix_symlink([target_dest_dir])
            except Exception:
                pass

        if need_cleanup:
            try:
                self._rmtree_try_chmod(tmp_dir)
            except Exception as e:
                print(
                    f"Warning: failed to remove temporary directory '{tmp_dir}': {e}",
                    file=sys.stderr,
                )

        return 0

    @classmethod
    def _rmtree_try_chmod(cls, path: str, *, ignore_errors=False):
        import shutil

        def onerror(func: Any, path: str, _exc_info: Any) -> None:
            import stat

            if not os.access(path, os.W_OK):
                os.chmod(path, stat.S_IWUSR)
                func(path)
            else:
                raise

        shutil.rmtree(path, ignore_errors=ignore_errors, onerror=onerror)  # pyright: ignore[reportDeprecated]

    @classmethod
    def main(cls, args: Optional[List[str]] = None) -> int:
        """Main CLI entrypoint for ShellCmd."""
        args = args or sys.argv[1:]
        try:
            from argparse import ArgumentParser, RawTextHelpFormatter

            parser = ArgumentParser(formatter_class=RawTextHelpFormatter)
            subparsers = parser.add_subparsers(dest='command')

            # 1. rm subparser
            rm_parser = subparsers.add_parser('rm', help='Simulate rm / rm -rf')
            rm_parser.add_argument(
                '-r', '-R', '--recursive', action='store_true', help='Recursive remove'
            )
            rm_parser.add_argument(
                '-f', '--force', action='store_true', help='Force remove'
            )
            rm_parser.add_argument(
                '--stdin',
                '--args-from-stdin',
                action='store_true',
                dest='args_from_stdin',
                help='Read from stdin',
            )
            rm_parser.add_argument(
                'paths', nargs='*', help='Files or directories to remove'
            )

            # 2. mkdir subparser
            mkdir_parser = subparsers.add_parser(
                'mkdir', help='Simulate mkdir / mkdir -p'
            )
            mkdir_parser.add_argument(
                '-f', '--force', action='store_true', help='Force create'
            )
            mkdir_parser.add_argument(
                '-p',
                '--parents',
                action='store_true',
                help='Make parent directories as needed',
            )
            mkdir_parser.add_argument(
                'paths', nargs='+', help='Directory paths to create'
            )

            # 3. rmdir subparser
            rmdir_parser = subparsers.add_parser('rmdir', help='Simulate rmdir')
            rmdir_parser.add_argument(
                '-p',
                '--parents',
                action='store_true',
                dest='remove_parents',
                help='Remove parent directories as needed',
            )
            rmdir_parser.add_argument(
                '-f', '--force', action='store_true', help='Ignore errors'
            )
            rmdir_parser.add_argument('paths', nargs='*', help='Directories to remove')

            # 4. mv subparser
            mv_parser = subparsers.add_parser('mv', help='Simulate mv')
            mv_parser.add_argument(
                '-f', '--force', action='store_true', help='Force move'
            )
            mv_parser.add_argument(
                'paths', nargs='+', help='Source files and destination directory'
            )

            # 5. cp subparser
            cp_parser = subparsers.add_parser('cp', help='Simulate cp')
            cp_parser.add_argument(
                '-r', '-R', '--recursive', action='store_true', help='Recursive copy'
            )
            cp_parser.add_argument(
                '-P',
                '--no-dereference',
                action='store_false',
                dest='follow_symlinks',
                default=True,
                help='No dereference symlinks',
            )
            cp_parser.add_argument(
                '-f', '--force', action='store_true', help='Force copy'
            )
            cp_parser.add_argument(
                'paths', nargs='+', help='Source files and destination directory'
            )

            # 6. mklink subparser
            mklink_parser = subparsers.add_parser(
                'mklink', help='Simulate symlink creation'
            )
            mklink_parser.add_argument(
                '-D', '--symlinkd', action='store_true', help='Force directory symlink'
            )
            mklink_parser.add_argument(
                '-f', '--force', action='store_true', help='Force link'
            )
            mklink_parser.add_argument('link', help='Link path')
            mklink_parser.add_argument('target', help='Target path')

            # 7. fix-symlink subparser
            fix_symlink_parser = subparsers.add_parser(
                'fix-symlink',
                help='Fix Windows/WSL broken symbolic links',
            )
            fix_symlink_parser.add_argument(
                'patterns', nargs='+', help='Glob patterns to search and fix'
            )

            # 8. cwd subparser
            subparsers.add_parser(
                'cwd', help='Print current working directory in Unix format'
            )

            # 9. mydir subparser
            subparsers.add_parser(
                'mydir', help='Print the directory of CMKABE utility in Unix format'
            )

            # 10. relpath subparser
            relpath_parser = subparsers.add_parser(
                'relpath', help='Print relative path'
            )
            relpath_parser.add_argument('path', help='Target path')
            relpath_parser.add_argument(
                'start', nargs='?', default=None, help='Start directory'
            )

            # 11. win2wsl-path subparser
            win2wsl_parser = subparsers.add_parser(
                'win2wsl-path', help='Convert Windows path to WSL'
            )
            win2wsl_parser.add_argument(
                'path', nargs='?', default=None, help='Windows path'
            )

            # 12. wsl2win-path subparser
            wsl2win_parser = subparsers.add_parser(
                'wsl2win-path',
                help='Convert WSL path to Windows',
            )
            wsl2win_parser.add_argument(
                'path', nargs='?', default=None, help='WSL path'
            )

            # 13. is-wsl-win-path subparser
            is_wsl_win_parser = subparsers.add_parser(
                'is-wsl-win-path',
                help='Check if path is a WSL mapped Windows drive path',
            )
            is_wsl_win_parser.add_argument(
                'path', nargs='?', default=None, help='Path to check'
            )

            # 14. touch subparser
            touch_parser = subparsers.add_parser('touch', help='Simulate touch')
            touch_parser.add_argument(
                '-f', '--force', action='store_true', help='Force touch'
            )
            touch_parser.add_argument('paths', nargs='+', help='File paths')

            # 15. timestamp subparser
            subparsers.add_parser('timestamp', help='Print current epoch timestamp')

            # 16. cmpver subparser
            cmpver_parser = subparsers.add_parser(
                'cmpver', help='Compare two version strings'
            )
            cmpver_parser.add_argument(
                '-f', '--force', action='store_true', help='Force exit code 0'
            )
            cmpver_parser.add_argument('v1', help='Version 1')
            cmpver_parser.add_argument('v2', help='Version 2')

            # 17. winreg subparser
            winreg_parser = subparsers.add_parser(
                'winreg', help='Query registry value on Windows'
            )
            winreg_parser.add_argument('keys', nargs='+', help='Registry key paths')

            # 18. ndk-root subparser
            subparsers.add_parser('ndk-root', help='Print Android NDK root path')

            # 19. cargo-exec subparser
            cargo_exec_parser = subparsers.add_parser(
                'cargo-exec',
                help='Simulate cargo build environment execution',
            )
            cargo_exec_parser.add_argument(
                'cargo_toml_path', help='Path to Cargo.toml or directory'
            )
            cargo_exec_parser.add_argument(
                'exec_cmd', nargs='+', help='Command to execute'
            )

            # 20. upload subparser
            upload_parser = subparsers.add_parser(
                'upload', help='Upload file via FTP or SFTP'
            )
            upload_parser.add_argument('ftp_path', help='Remote FTP server URL')
            upload_parser.add_argument(
                'files', nargs='+', help='File patterns to upload'
            )

            # 21. build-target-deps subparser
            build_deps_parser = subparsers.add_parser(
                'build-target-deps',
                help='Build target dependencies',
            )
            build_deps_parser.add_argument(
                'params', nargs='*', help='Key-value parameters'
            )

            # 22. dll2lib subparser
            dll2lib_parser = subparsers.add_parser(
                'dll2lib', help='Call dll2lib to generate MSVC import libraries'
            )
            dll2lib_parser.add_argument(
                '-f', '--force', action='store_true', help='Force overwrite'
            )
            dll2lib_parser.add_argument('dll_path', help='DLL path')
            dll2lib_parser.add_argument(
                'out_path', nargs='?', default=None, help='Output import library path'
            )

            # 23. zig-patch subparser
            zig_patch_parser = subparsers.add_parser(
                'zig-patch',
                help='Call zig_patch to patch Zig source libraries',
            )
            zig_patch_parser.add_argument(
                'zig_root', nargs='?', default=None, help='Zig installation root'
            )

            # 24. zig-clean-cache subparser
            zig_clean_parser = subparsers.add_parser(
                'zig-clean-cache', help='Clean Zig global cache'
            )
            zig_clean_parser.add_argument(
                '-v', '--verbose', action='store_true', help='Verbose output'
            )
            zig_clean_parser.add_argument(
                'zig_root', nargs='?', default=None, help='Zig installation root'
            )

            # 25. find-shell subparser
            find_shell_parser = subparsers.add_parser(
                'find-shell', help='Find the shell matching the terminal environment'
            )
            find_shell_parser.add_argument(
                '--exit-code',
                action='store_true',
                dest='exit_code',
                help='Exit code mode',
            )

            # 26. clone_libs subparser
            clone_libs_parser = subparsers.add_parser(
                'clone-libs', help='Download or rebuild external libraries'
            )
            clone_libs_parser.add_argument(
                '--dest-dir', required=True, help='Target destination directory'
            )
            clone_libs_parser.add_argument(
                '--url', default='', help='Remote URL or local path'
            )
            clone_libs_parser.add_argument(
                '--local-repo', default='', help='Local repository path'
            )
            clone_libs_parser.add_argument(
                '--files', default='', help='Semicolon-separated files list'
            )
            clone_libs_parser.add_argument(
                '--tmp-dir', default='.libs', help='Temporary directory path'
            )
            clone_libs_parser.add_argument(
                '--rebuild',
                nargs='?',
                default=None,
                const='',
                help='Target name (may be empty) to trigger rebuilding',
            )

            # 27. elf-path-fixer subparser
            elf_path_fixer_parser = subparsers.add_parser(
                'elf-path-fixer',
                help='Fix ELF dynamic library paths by removing directory paths',
            )
            elf_path_fixer_parser.add_argument(
                'elf_file', help='Path to the ELF executable file to process'
            )
            elf_path_fixer_parser.add_argument(
                '--target',
                '-t',
                required=True,
                dest='targets',
                action='append',
                help='Regular expression pattern to match in library paths',
            )
            elf_path_fixer_parser.add_argument(
                '--fix-rpath',
                action='store_true',
                dest='fix_rpath',
                default=False,
                help='fix both RPATH and RUNPATH',
            )
            elf_path_fixer_parser.add_argument(
                '--no-backup',
                action='store_false',
                dest='create_backup',
                default=True,
                help='Do not create a backup of the original file',
            )
            elf_path_fixer_parser.add_argument(
                '--verbose',
                '-v',
                action='store_true',
                default=False,
                help='Enable verbose output',
            )
            elf_path_fixer_parser.add_argument(
                '--quiet',
                '-q',
                action='store_true',
                default=False,
                help='Suppress all output except errors',
            )

            # 28. zig-build-wrapper subparser
            zig_build_wrapper_parser = subparsers.add_parser(
                'zig-build-wrapper',
                help='Build compiler wrapper using zig build-exe',
            )
            zig_build_wrapper_parser.add_argument(
                '--zig-root', default=None, help='Zig installation root'
            )
            zig_build_wrapper_parser.add_argument(
                '--out-dir', default=None, help='Destination directory for wrapper'
            )
            zig_build_wrapper_parser.add_argument(
                '--prefix', default='zig', help='Prefix for symlinks'
            )
            zig_build_wrapper_parser.add_argument(
                '-f', '--force', action='store_true', help='Force rebuild'
            )
            zig_build_wrapper_parser.add_argument(
                '--vcpkg', action='store_true', help='Vcpkg mode'
            )

            # 29. vcpkg-host-triplet subparser
            subparsers.add_parser(
                'vcpkg-host-triplet',
                help='Print vcpkg host triplet name',
            )

            # 30. vcpkg-create-triplet-cache subparser
            create_cache_parser = subparsers.add_parser(
                'vcpkg-create-triplet-cache',
                help='Create vcpkg triplet cmake files cache with custom settings',
            )
            create_cache_parser.add_argument(
                '--vcpkg-root', default=None, help='vcpkg root directory'
            )
            create_cache_parser.add_argument(
                '--triplet-cache-dir',
                default=None,
                help='Directory to store triplet cache',
            )
            create_cache_parser.add_argument(
                '--debug',
                action='store_true',
                help='Enable debug mode (unset VCPKG_BUILD_TYPE)',
            )
            create_cache_parser.add_argument(
                '--static-crt', action='store_true', help='Use static CRT linkage'
            )
            create_cache_parser.add_argument(
                '--static-lib', action='store_true', help='Use static library linkage'
            )
            create_cache_parser.add_argument(
                'triplets', nargs='*', help='Triplet names'
            )

            namespace = parser.parse_args(args)

            if not namespace.command:
                print('Missing command', file=sys.stderr)
                return cls.EINVAL

            inst = cls()
            cmd = namespace.command

            if cmd == 'rm':
                return inst.rm(
                    paths=namespace.paths,
                    recursive=namespace.recursive,
                    force=namespace.force,
                    args_from_stdin=namespace.args_from_stdin,
                )
            elif cmd == 'mkdir':
                return inst.mkdir(
                    paths=namespace.paths,
                    force=namespace.force,
                )
            elif cmd == 'rmdir':
                return inst.rmdir(
                    paths=namespace.paths,
                    remove_parents=namespace.remove_parents,
                    force=namespace.force,
                )
            elif cmd == 'mv':
                return inst.mv(
                    paths=namespace.paths,
                    force=namespace.force,
                )
            elif cmd == 'cp':
                return inst.cp(
                    paths=namespace.paths,
                    recursive=namespace.recursive,
                    follow_symlinks=namespace.follow_symlinks,
                    force=namespace.force,
                )
            elif cmd == 'mklink':
                return inst.mklink(
                    link=namespace.link,
                    target=namespace.target,
                    symlinkd=namespace.symlinkd,
                    force=namespace.force,
                )
            elif cmd == 'fix-symlink':
                return inst.fix_symlink(
                    patterns=namespace.patterns,
                )
            elif cmd == 'cwd':
                return inst.cwd()
            elif cmd == 'mydir':
                return inst.mydir()
            elif cmd == 'relpath':
                return inst.relpath(
                    path=namespace.path,
                    start=namespace.start,
                )
            elif cmd == 'win2wsl-path':
                return inst.win2wsl_path(
                    path=namespace.path,
                )
            elif cmd == 'wsl2win-path':
                return inst.wsl2win_path(
                    path=namespace.path,
                )
            elif cmd == 'is-wsl-win-path':
                return inst.is_wsl_win_path(
                    path=namespace.path,
                )
            elif cmd == 'touch':
                return inst.touch(
                    paths=namespace.paths,
                    force=namespace.force,
                )
            elif cmd == 'timestamp':
                return inst.timestamp()
            elif cmd == 'cmpver':
                return inst.cmpver(
                    v1=namespace.v1,
                    v2=namespace.v2,
                    force=namespace.force,
                )
            elif cmd == 'winreg':
                return inst.winreg(
                    keys=namespace.keys,
                )
            elif cmd == 'ndk-root':
                return inst.ndk_root()
            elif cmd == 'cargo-exec':
                return inst.cargo_exec(
                    cargo_toml_path=namespace.cargo_toml_path,
                    command=namespace.exec_cmd,
                )
            elif cmd == 'upload':
                return inst.upload(
                    ftp_path=namespace.ftp_path,
                    files=namespace.files,
                )
            elif cmd == 'build-target-deps':
                return inst.build_target_deps(
                    params=namespace.params,
                )
            elif cmd == 'dll2lib':
                return inst.dll2lib(
                    dll_path=namespace.dll_path,
                    out_path=namespace.out_path,
                    force=namespace.force,
                )
            elif cmd == 'zig-patch':
                return inst.zig_patch(
                    zig_root=namespace.zig_root,
                )
            elif cmd == 'zig-clean-cache':
                return inst.zig_clean_cache(
                    zig_root=namespace.zig_root,
                    verbose=namespace.verbose,
                )
            elif cmd == 'find-shell':
                return inst.find_shell(
                    exit_code=namespace.exit_code,
                )
            elif cmd == 'clone-libs':
                return inst.clone_libs(
                    dest_dir=namespace.dest_dir,
                    url=namespace.url,
                    local_repo=namespace.local_repo,
                    files=namespace.files,
                    tmp_dir=namespace.tmp_dir,
                    rebuild=namespace.rebuild,
                )
            elif cmd == 'elf-path-fixer':
                return inst.elf_path_fixer(
                    elf_file=namespace.elf_file,
                    targets=namespace.targets,
                    fix_rpath=namespace.fix_rpath,
                    create_backup=namespace.create_backup,
                    verbose=namespace.verbose,
                    quiet=namespace.quiet,
                )
            elif cmd == 'zig-build-wrapper':
                return inst.zig_build_wrapper(
                    zig_root=namespace.zig_root,
                    out_dir=namespace.out_dir,
                    prefix=namespace.prefix,
                    force=namespace.force,
                    vcpkg=namespace.vcpkg,
                )
            elif cmd == 'vcpkg-host-triplet':
                return inst.vcpkg_host_triplet()
            elif cmd == 'vcpkg-create-triplet-cache':
                return inst.vcpkg_create_triplet_cache(
                    vcpkg_root=namespace.vcpkg_root,
                    triplet_cache_dir=namespace.triplet_cache_dir,
                    triplets=namespace.triplets,
                    debug=namespace.debug,
                    static_crt=namespace.static_crt,
                    static_lib=namespace.static_lib,
                )

            print(f'Unrecognized command "{cmd}"', file=sys.stderr)
            return cls.EINVAL

        except PermissionError as e:
            print(e)
            return cls.EFAIL

        except KeyboardInterrupt:
            print('^C', file=sys.stderr)
            return cls.EINTERRUPT
