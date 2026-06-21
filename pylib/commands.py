# -*- coding: utf-8 -*-
"""Simulated shell utilities for Makefile compatibility on Windows."""

import glob
import os
import sys
import time
from typing import Any, Generator, List, Optional

from cmk.pylib.sys_utils import (
    ndk_root,
    win2wsl_path,
    wsl2win_path,
)
from cmk.pylib.zig import zig_clean_cache, zig_dll2lib, zig_patch


class ShellCmd:
    """Implement platform-independent shell commands."""

    EFAIL: int = 1
    ENOENT: int = 7
    EINVAL: int = 8
    EINTERRUPT: int = 254

    def __init__(self, namespace: Any) -> None:
        self.options = namespace
        self.args: List[str] = namespace.args

    def run__rm(self) -> int:
        """Simulate rm / rm -rf.

        Removes files, directories, or glob patterns. Automatically handles Windows read-only file system permissions.
        Options:
            -r / -R / --recursive: Recursively remove directories.
            -f / --force: Ignore nonexistent files and execution errors.
            --stdin / --args-from-stdin: Read arguments from stdin.
        """

        def read_arg() -> Generator[str, None, None]:
            if self.options.args_from_stdin:
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
                for arg in self.args:
                    yield arg

        status = 0
        if not self.options.recursive:
            for pattern in read_arg():
                files = glob.glob(pattern)
                if not files and not self.options.force:
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
                        if self.options.force:
                            continue
                        print(f'Can not remove file {file}', file=sys.stderr)
                        return status
        else:
            for pattern in read_arg():
                files = glob.glob(pattern)
                if not files and not self.options.force:
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
                        if self.options.force:
                            continue
                        print(f'Can not remove tree {file}', file=sys.stderr)
                        return status
        return status

    def run__mkdir(self) -> int:
        """Simulate mkdir / mkdir -p.

        Creates directory paths. Always acts like Unix `mkdir -p` (creates parent directories, ignores existing paths).
        Options:
            -f / --force: Ignore execution errors.
        """
        status = 0
        for path in self.args:
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
                if self.options.force:
                    continue
                print(f'Can not make directory {path}', file=sys.stderr)
                return status
        return status

    def run__rmdir(self) -> int:
        """Simulate rmdir.

        Removes directory paths.
        Options:
            -e / --empty-dirs: Recursively prune empty subdirectories and parent directories.
            -f / --force: Ignore execution errors.
        """
        status = 0
        for path in self.args:
            if not self.options.remove_empty_dirs:
                try:
                    os.rmdir(path)
                except OSError:
                    status = self.EFAIL
                    if self.options.force:
                        continue
                    print(f'Can not remove directory {path}', file=sys.stderr)
                    return status
            else:

                def remove_empty_dirs(p: str) -> None:
                    # Remove empty sub-directories recursively
                    for item in os.listdir(p):
                        directory = os.path.join(p, item)
                        if os.path.isdir(directory):
                            remove_empty_dirs(directory)
                            if not os.listdir(directory):
                                os.rmdir(directory)

                if os.path.isdir(path):
                    try:
                        remove_empty_dirs(path)
                        # Try to remove empty ancestor directories.
                        curr: str = path
                        while curr:
                            os.rmdir(curr)
                            curr = os.path.dirname(curr)
                    except OSError:
                        pass
        return status

    def run__mv(self) -> int:
        """Simulate mv.

        Moves files, directories, or glob patterns to a destination path.
        Arguments:
            args[:-1]: Source file/directory paths or glob patterns.
            args[-1]: Destination path.
        Options:
            -f / --force: Ignore execution errors.
        """
        import shutil

        status = 0
        if len(self.args) < 2:
            print(f'Invalid parameter {self.args} for mv', file=sys.stderr)
            return self.EFAIL
        dst = self.args[-1]
        files: List[str] = []
        for pattern in self.args[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            print(f'{dst} is not a directory', file=sys.stderr)
            return self.EFAIL
        if not files and not self.options.force:
            print(f'Can not find file {self.args[:-1]}', file=sys.stderr)
            return self.EFAIL
        for file in files:
            try:
                shutil.move(file, dst)
            except OSError:
                status = self.EFAIL
                if not self.options.force:
                    print(f'Can not move {file} to {dst}', file=sys.stderr)
                return status
        return status

    def run__cp(self) -> int:
        """Simulate cp.

        Copies files, directories, or glob patterns to a destination path.
        Arguments:
            args[:-1]: Source file/directory paths or glob patterns.
            args[-1]: Destination path (defaults to '.' if only one argument is provided).
        Options:
            -r / -R / --recursive: Recursively copy directories.
            -P / --no-dereference: Preserve symbolic links without following them.
            -f / --force: Ignore execution errors.
        """
        import shutil

        def copy_file(src: str, dst: str) -> None:
            if os.path.islink(src) and not self.options.follow_symlinks:
                if os.path.isdir(dst):
                    dst = os.path.join(dst, os.path.basename(src))
                if os.path.lexists(dst):
                    os.unlink(dst)
                linkto = os.readlink(src)
                os.symlink(linkto, dst)
            else:
                shutil.copy2(src, dst)

        status = 0
        if len(self.args) < 1:
            print(f'Invalid parameter {self.args} for cp', file=sys.stderr)
            return self.EFAIL
        if len(self.args) == 1:
            self.args.append('.')
        dst = self.args[-1]
        files: List[str] = []
        for pattern in self.args[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            print(f'{dst} is not a directory', file=sys.stderr)
            return self.EFAIL
        if not files and not self.options.force:
            print(f'Can not find file {self.args[:-1]}', file=sys.stderr)
            return self.EFAIL
        for file in files:
            try:
                if os.path.isfile(file):
                    copy_file(file, dst)
                elif self.options.recursive:
                    shutil.copytree(
                        file,
                        os.path.join(dst, os.path.basename(file)),
                        copy_function=copy_file,
                        dirs_exist_ok=True,
                    )
            except OSError:
                status = self.EFAIL
                if not self.options.force:
                    print(f'Can not copy {file} to {dst}', file=sys.stderr)
                return status
        return status

    def run__mklink(self) -> int:
        """Simulate symlink creation.

        Creates file or directory symbolic links.
        Arguments:
            args[0]: Link path.
            args[1]: Target path.
        Options:
            -D / --symlinkd: Force directory symlink.
            -f / --force: Ignore execution errors.
        """
        status = 0
        if len(self.args) < 2:
            print('Invalid parameter', file=sys.stderr)
            return self.EINVAL
        link = self.args[0]
        target = self.args[1]
        try:
            target = target.replace('/', os.sep).replace('\\', os.sep)
            os.symlink(
                target,
                link,
                target_is_directory=self.options.symlinkd or os.path.isdir(target),
            )
        except OSError:
            status = self.EFAIL
            if not self.options.force:
                print(
                    f'Can not create symbolic link: {link} -> {target}',
                    file=sys.stderr,
                )
        return status

    def run__fix_symlink(self) -> int:
        """Fix Windows/WSL broken symbolic links.

        Fixes directory junctions on Windows and absolute symlinks on WSL recursively.
        Arguments:
            args: Glob patterns to search and fix.
        """
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
                        # Try to find it's target and rebuild it.
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
            for pattern in self.args:
                walk(pattern)
            return 0
        except OSError:
            return self.EFAIL

    def run__cwd(self) -> int:
        """Print current working directory in Unix format (forward slashes)."""
        print(os.getcwd().replace('\\', '/'), end='')
        return 0

    def run__mydir(self) -> int:
        """Print the directory of CMK utility in Unix format (forward slashes)."""
        path = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        if os.path.isdir(path):
            path = os.path.realpath(path)
        else:
            path = os.getcwd()
        print(path.replace('\\', '/'), end='')
        return 0

    def run__relpath(self) -> int:
        """Print relative path.

        Arguments:
            args[0]: Target path.
            args[1] (optional): Start directory.
        """
        start = None if len(self.args) <= 1 else self.args[1]
        try:
            path = self.args[0]
            path = os.path.relpath(path, start)
        except (IndexError, ValueError, OSError):
            path = ''
        print(path.replace('\\', '/'), end='')
        return 0

    def run__win2wsl_path(self) -> int:
        """Convert Windows path to WSL.

        Arguments:
            args[0] (optional): Windows path to convert (defaults to current directory).
        """
        path = win2wsl_path(self.args[0] if self.args else os.getcwd())
        print(path, end='')
        return 0

    def run__wsl2win_path(self) -> int:
        """Convert WSL path to Windows.

        Arguments:
            args[0] (optional): WSL path to convert (defaults to current directory).
        """
        path = wsl2win_path(self.args[0] if self.args else os.getcwd())
        print(path, end='')
        return 0

    def run__is_wsl_win_path(self) -> int:
        """Check if path is a WSL mapped Windows drive path (/mnt/*).

        Prints 'true' or 'false'.
        Arguments:
            args[0] (optional): Path to check (defaults to current directory).
        """
        path = os.path.abspath(self.args[0]) if self.args else os.getcwd()
        path = path.replace('\\', '/')
        if len(path) >= 6 and path.startswith('/mnt/') and path[5].isalpha():
            if len(path) == 6 or path[6] == '/':
                print('true', end='')
                return 0
        print('false', end='')
        return 0

    def run__touch(self) -> int:
        """Simulate touch.

        Creates empty files or updates access and modification times of files.
        Arguments:
            args: File paths or glob patterns.
        Options:
            -f / --force: Ignore execution errors.
        """
        status = 0
        for pattern in self.args:
            files = glob.glob(pattern)
            if not files:
                try:
                    open(pattern, 'ab').close()
                except OSError:
                    status = self.EFAIL
                    if self.options.force:
                        continue
                    print(f'Can not create file {pattern}', file=sys.stderr)
                    return status
            for file in files:
                try:
                    os.utime(file, None)
                except OSError:
                    status = self.EFAIL
                    if self.options.force:
                        continue
                    print(f'Can not touch file {file}', file=sys.stderr)
                    return status
        return status

    def run__timestamp(self) -> int:
        """Print current epoch timestamp."""
        print(time.time(), end='')
        return 0

    def run__cmpver(self) -> int:
        """Compare two version strings.

        Prints '+' if v1 > v2, '0' if equal, '-' if v1 < v2.
        Arguments:
            args[0]: First version string (v1).
            args[1]: Second version string (v2).
        Options:
            -f / --force: Force return exit code 0.
        """
        try:
            v1 = [int(x) for x in (self.args[0] + '.0.0.0').split('.')[:4]]
            v2 = [int(x) for x in (self.args[1] + '.0.0.0').split('.')[:4]]
            if v1 > v2:
                result = (1, '+')
            elif v1 == v2:
                result = (0, '0')
            else:
                result = (2, '-')
        except (IndexError, ValueError):
            result = (self.EINVAL, '')
            print('Invalid arguments', file=sys.stderr)
        print(result[1], end='')
        return 0 if self.options.force else result[0]

    def run__winreg(self) -> int:
        """Query registry value on Windows.

        Arguments:
            args: Registry key path (e.g. HKEY_LOCAL_MACHINE\\SOFTWARE\\...).
        """
        try:
            value = None
            try:
                import winreg

                root_keys = {
                    'HKEY_CLASSES_ROOT': winreg.HKEY_CLASSES_ROOT,
                    'HKEY_CURRENT_USER': winreg.HKEY_CURRENT_USER,
                    'HKEY_LOCAL_MACHINE': winreg.HKEY_LOCAL_MACHINE,
                    'HKEY_USERS': winreg.HKEY_USERS,
                    'HKEY_PERFORMANCE_DATA': winreg.HKEY_PERFORMANCE_DATA,
                    'HKEY_CURRENT_CONFIG': winreg.HKEY_CURRENT_CONFIG,
                }
                for arg in self.args:
                    keys = arg.split('\\')
                    key = root_keys[keys[0]]
                    sub_key = '\\'.join(keys[1:-1])
                    value_name = keys[-1]
                    try:
                        with winreg.OpenKey(
                            key, sub_key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY
                        ) as rkey:
                            value = winreg.QueryValueEx(rkey, value_name)[0]
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

    def run__ndk_root(self) -> int:
        """Print Android NDK root directory path."""
        root_dir = ndk_root()
        if root_dir:
            print(root_dir, end='')
            return 0
        return self.ENOENT

    def run__cargo_exec(self) -> int:
        """Simulate cargo build environment execution.

        Sets up Cargo environment variables from a Cargo.toml file and executes a command.
        Arguments:
            args[0]: Path to Cargo.toml or directory.
            args[1:]: Shell command to execute.
        """
        import subprocess

        if len(self.args) < 1:
            print(f'Invalid parameter {self.args} for cargo-exec', file=sys.stderr)
            return self.EFAIL
        ws_dir = os.environ.get('CARGO_WORKSPACE_DIR', '.')
        cfg_file = (
            self.args[0]
            if self.args[0].endswith('.toml')
            else os.path.join(self.args[0], 'Cargo.toml')
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
        return subprocess.call(' '.join(self.args[1:]), shell=True)

    def run__upload(self) -> int:
        """Upload file via FTP or SFTP.

        Arguments:
            args[0]: Remote server URL (e.g. sftp://user:pass@host/path).
            args[1:]: File patterns to upload (format: [remote_file=]local_glob).
        """
        import urllib.parse

        if len(self.args) < 2:
            print(f'Invalid parameter {self.args} for upload', file=sys.stderr)
            return self.EFAIL

        ftp_path = self.args[0]
        files = self.args[1:]

        parsed = urllib.parse.urlparse(ftp_path)
        if not parsed.hostname:
            print(f'No hostname in {self.args}', file=sys.stderr)
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

    def run__build_target_deps(self) -> int:
        """Call TargetParser to build target dependencies.

        Arguments:
            args: Key-value parameters passed to TargetParser (e.g. TARGET=native).
        """
        from cmk.pylib.target import TargetParser

        try:
            args = {
                k.strip().lower(): v
                for (k, v) in map(lambda x: x.split('=', 1), self.args)
            }
            TargetParser(**args).parse().build()
        except Exception as e:
            # Check for debug environment
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

    def run__dll2lib(self) -> int:
        """Call dll2lib to generate MSVC import libraries from DLLs.

        Arguments:
            args[0]: Path to source DLL file.
            args[1] (optional): Path to output import library (.lib).
        Options:
            -f / --force: Overwrite existing .lib files.
        """
        if len(self.args) < 1:
            print('Please input the DLL file path', file=sys.stderr)
            return self.EINVAL
        return zig_dll2lib(
            self.args[0],
            out_path=self.args[1] if len(self.args) >= 2 else None,
            force=self.options.force,
        )

    def run__zig_patch(self) -> int:
        """Call zig_patch to patch Zig source libraries to hide runtime exports.

        Arguments:
            args[0] (optional): Path to Zig installation root.
        """
        zig_root = self.args[0] if self.args and self.args[0] else None
        zig_patch(zig_root)
        return 0

    def run__zig_clean_cache(self) -> int:
        """Call zig_clean_cache to clean Zig global cache.

        Arguments:
            args[0] (optional): Path to Zig installation root.
        """
        zig_root = self.args[0] if self.args and self.args[0] else None
        zig_clean_cache(zig_root)
        return 0

    def run__update_libs(self) -> int:
        """Download or rebuild external libraries and copy files.

        Options are parsed from self.options (added in main parser):
            --url: remote URL or local path
            --local-repo: local repository path
            --dest-dir: target destination directory
            --files: semicolon-separated list of file patterns/mappings
            --tmp-dir: temporary directory path
            --rebuild: flag to trigger rebuilding
        """
        import shutil
        import subprocess

        url = self.options.url or ''
        local_repo = self.options.local_repo or ''
        dest_dir = self.options.dest_dir or ''
        files = self.options.files or ''
        tmp_dir = self.options.tmp_dir or '.libs'
        rebuild = bool(self.options.rebuild)

        if not dest_dir:
            print('Error: --dest-dir is required', file=sys.stderr)
            return self.EINVAL

        if not local_repo and url:
            base = os.path.basename(url)
            if base.endswith('.git'):
                base = base[:-4]
            local_repo = os.path.join('..', base)

        # Clean up tmp_dir at the beginning
        if os.path.exists(tmp_dir):
            try:
                self._rmtree_try_chmod(tmp_dir)
            except Exception:
                pass

        src_dir = None
        need_cleanup = False

        if rebuild:
            print(f"Rebuilding in local repository '{local_repo}'...")
            ret = subprocess.call('make DEBUG=0', shell=True, cwd=local_repo)
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

        # Process file mappings
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

            # Fix symlinks on the destination folder
            saved_args = self.args
            self.args = [target_dest_dir]
            try:
                self.run__fix_symlink()
            finally:
                self.args = saved_args

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

            # Is the error an access error?
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
            parser.add_argument(
                '-D',
                '--symlinkd',
                action='store_true',
                default=False,
                dest='symlinkd',
                help='creates a directory symbolic link',
            )
            parser.add_argument(
                '-e',
                '--empty-dirs',
                action='store_true',
                default=False,
                dest='remove_empty_dirs',
                help='remove all empty directories',
            )
            parser.add_argument(
                '-f',
                '--force',
                action='store_true',
                default=False,
                dest='force',
                help='ignore errors, never prompt',
            )
            parser.add_argument(
                '--list',
                action='store_true',
                default=False,
                dest='list_cmds',
                help='list all commands',
            )
            parser.add_argument(
                '-P',
                '--no-dereference',
                action='store_false',
                default=True,
                dest='follow_symlinks',
                help='always follow symbolic links in SOURCE',
            )
            parser.add_argument(
                '-p',
                '--parents',
                action='store_true',
                default=True,
                dest='parents',
                help='if existing, make parent directories as needed',
            )
            parser.add_argument(
                '-r',
                '-R',
                '--recursive',
                action='store_true',
                default=False,
                dest='recursive',
                help='copy/remove directories and their contents recursively',
            )
            parser.add_argument(
                '--args-from-stdin',
                '--stdin',
                action='store_true',
                default=False,
                dest='args_from_stdin',
                help='read arguments from stdin',
            )
            parser.add_argument(
                '--url',
                default='',
                help='remote git repository URL or local path for update-libs',
            )
            parser.add_argument(
                '--local-repo',
                default='',
                help='local source repository path for update-libs',
            )
            parser.add_argument(
                '--dest-dir',
                default='',
                help='local destination directory for update-libs',
            )
            parser.add_argument(
                '--files',
                default='',
                help='semicolon-separated list of file mappings for update-libs',
            )
            parser.add_argument(
                '--tmp-dir',
                default='',
                help='temporary directory for update-libs',
            )
            parser.add_argument(
                '--rebuild',
                action='store_true',
                default=False,
                help='rebuild libraries in local repo for update-libs',
            )
            parser.add_argument('command', nargs='?', default='')
            parser.add_argument('args', nargs='*', default=[])
            namespace = parser.parse_intermixed_args(args)

            inst = cls(namespace)
            if namespace.list_cmds:
                for name in dir(inst):
                    if name.startswith('run__'):
                        print(name[5:].replace('_', '-'))
                return 0

            if not namespace.command:
                print('Missing command', file=sys.stderr)
                return cls.EINVAL

            cmd_func_name = 'run__' + namespace.command.replace('-', '_')
            try:
                func = getattr(inst, cmd_func_name)
                return int(func())
            except AttributeError:
                print(
                    f'Unrecognized command "{namespace.command}"',
                    file=sys.stderr,
                )
                return cls.EINVAL

        except PermissionError as e:
            print(e)
            return cls.EFAIL

        except KeyboardInterrupt:
            print('^C', file=sys.stderr)
            return cls.EINTERRUPT
