#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shell utility library

This file is the part of the cmake-abe library (https://github.com/spritetong/cmake-abe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2022 spritetong@gmail.com.
"""

import sys
import os

__all__ = ('ShellCmd', 'TargetParser',)


class ShellCmd:
    EFAIL = 1
    ENOENT = 7
    EINVAL = 8
    EINTERRUPT = 254

    EXE_EXT = '.exe' if os.name == 'nt' else ''

    def __init__(self, namespace):
        self.options = namespace
        self.args = namespace.args

    def run__rm(self):
        def read_arg():
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

        def onerror(func, path, _exc_info):
            import stat
            # Is the error an access error?
            if not os.access(path, os.W_OK):
                os.chmod(path, stat.S_IWUSR)
                func(path)
            else:
                raise

        status = 0
        if not self.options.recursive:
            import glob
            for pattern in read_arg():
                files = glob.glob(pattern)
                if not files and not self.options.force:
                    print('Can not find file {}'.format(
                        pattern), file=sys.stderr)
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
                        print('Can not remove file {}'.format(
                            file), file=sys.stderr)
                        return status
        else:
            import shutil
            import glob
            for pattern in read_arg():
                files = glob.glob(pattern)
                if not files and not self.options.force:
                    print('Can not find file {}'.format(
                        pattern), file=sys.stderr)
                    return self.EFAIL
                for file in files:
                    try:
                        if os.path.isfile(file) or os.path.islink(file):
                            os.remove(file)
                        elif os.path.isdir(file):
                            shutil.rmtree(
                                file, ignore_errors=False, onerror=onerror)
                        else:
                            # On Windows, a link like a bad <JUNCTION> can't be accessed.
                            os.remove(file)
                    except OSError:
                        status = self.EFAIL
                        if self.options.force:
                            continue
                        print('Can not remove tree {}'.format(
                            file), file=sys.stderr)
                        return status
        return status

    def run__mkdir(self):
        import time
        status = 0
        for path in self.args:
            ok = False
            for _ in range(100):
                try:
                    self.makedirs(path)
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
                print('Can not make directory {}'.format(path), file=sys.stderr)
                return status
        return status

    def run__rmdir(self):
        status = 0
        for path in self.args:
            if not self.options.remove_empty_dirs:
                try:
                    os.rmdir(path)
                except OSError:
                    status = self.EFAIL
                    if self.options.force:
                        continue
                    print('Can not remove directory {}'.format(
                        path), file=sys.stderr)
                    return status
            else:
                def remove_empty_dirs(path):
                    # Remove empty sub-directories recursively
                    for item in os.listdir(path):
                        dir = os.path.join(path, item)
                        if os.path.isdir(dir):
                            remove_empty_dirs(dir)
                            if not os.listdir(dir):
                                os.rmdir(dir)
                if os.path.isdir(path):
                    try:
                        remove_empty_dirs(path)
                        # Try to remove empty ancestor directories.
                        while path:
                            os.rmdir(path)
                            path = os.path.dirname(path)
                    except OSError:
                        pass
        return status

    def run__mv(self):
        import shutil
        import glob

        status = 0
        if len(self.args) < 2:
            print('Invalid parameter {} for mv'.format(
                self.args), file=sys.stderr)
            return self.EFAIL
        dst = self.args[-1]
        files = []
        for pattern in self.args[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            print('{} is not a direcotry'.format(dst), file=sys.stderr)
            return self.EFAIL
        if not files and not self.options.force:
            print('Can not find file {}'.format(pattern), file=sys.stderr)
            return self.EFAIL
        for file in files:
            try:
                shutil.move(file, dst)
            except OSError:
                status = self.EFAIL
                if not self.options.force:
                    print('Can not move {} to {}'.format(
                        file, dst), file=sys.stderr)
                return status
        return status

    def run__cp(self):
        import shutil
        import glob

        def copy_file(src, dst):
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
            print('Invalid parameter {} for cp'.format(
                self.args), file=sys.stderr)
            return self.EFAIL
        if len(self.args) == 1:
            self.args.append('.')
        dst = self.args[-1]
        files = []
        for pattern in self.args[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            print('{} is not a direcotry'.format(dst), file=sys.stderr)
            return self.EFAIL
        if not files and not self.options.force:
            print('Can not find file {}'.format(pattern), file=sys.stderr)
            return self.EFAIL
        for file in files:
            try:
                if os.path.isfile(file):
                    copy_file(file, dst)
                elif self.options.recursive:
                    shutil.copytree(file, os.path.join(
                        dst, os.path.basename(file)),
                        copy_function=copy_file, dirs_exist_ok=True)
            except OSError:
                status = self.EFAIL
                if not self.options.force:
                    print('Can not copy {} to {}'.format(
                        file, dst), file=sys.stderr)
                return status
        return status

    def run__mklink(self):
        status = 0
        if len(self.args) < 2:
            print('Invalid parameter', file=sys.stderr)
            return self.EINVAL
        link = self.args[0]
        target = self.args[1]
        try:
            target = target.replace('/', os.sep).replace('\\', os.sep)
            os.symlink(
                target, link, self.options.symlinkd or os.path.isdir(target))
        except OSError:
            status = self.EFAIL
            if not self.options.force:
                print('Can not create symbolic link: {} -> {}'.format(link, target),
                      file=sys.stderr)
        return status

    def run__fix_symlink(self):
        import glob
        is_wsl = 'WSL_DISTRO_NAME' in os.environ

        def walk(pattern):
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
                    print('Can not fix the bad symbolic link {}'.format(file),
                          file=sys.stderr)
                    raise

        try:
            for pattern in self.args:
                walk(pattern)
            return 0
        except OSError:
            return self.EFAIL

    def run__cwd(self):
        print(os.getcwd().replace('\\', '/'), end='')
        return 0

    def run__mydir(self):
        path = os.path.dirname(__file__)
        if os.path.isdir(path):
            path = os.path.realpath(path)
        else:
            path = os.getcwd()
        print(path.replace('\\', '/'), end='')
        return 0

    def run__relpath(self):
        start = None if len(self.args) <= 1 else self.args[1]
        try:
            path = self.args[0]
            path = os.path.relpath(path, start)
        except (IndexError, ValueError, OSError):
            path = ''
        print(path.replace('\\', '/'), end='')
        return 0

    def run__win2wsl_path(self):
        path = self.win2wsl_path(
            self.args[0] if self.args else os.getcwd())
        print(path, end='')
        return 0

    def run__wsl2win_path(self):
        path = self.wsl2win_path(
            self.args[0] if self.args else os.getcwd())
        print(path, end='')
        return 0

    def run__is_wsl_win_path(self):
        path = os.path.abspath(self.args[0]) if self.args else os.getcwd()
        path = path.replace('\\', '/')
        if len(path) >= 6 and path.startswith('/mnt/') and path[5].isalpha():
            if len(path) == 6 or path[6] == '/':
                print('true', end='')
                return 0
        print('false', end='')
        return 0

    def run__touch(self):
        import glob
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
                    print('Can not create file {}'.format(
                        pattern), file=sys.stderr)
                    return status
            for file in files:
                try:
                    os.utime(file, None)
                except OSError:
                    status = self.EFAIL
                    if self.options.force:
                        continue
                    print('Can not touch file {}'.format(file), file=sys.stderr)
                    return status
        return status

    def run__timestamp(self):
        import time
        print(time.time(), end='')
        return 0

    def run__cmpver(self):
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

    def run__winreg(self):
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
                    # Read registry.
                    key = root_keys[keys[0]]
                    sub_key = '\\'.join(keys[1:-1])
                    value_name = keys[-1]
                    try:
                        with winreg.OpenKey(key, sub_key, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as rkey:
                            value = winreg.QueryValueEx(rkey, value_name)[0]
                            if value:
                                break
                    except WindowsError:
                        pass
            except ImportError:
                pass
            print(value or '', end='')
            return 0
        except (NameError, AttributeError):
            return self.EFAIL

    def run__ndk_root(self):
        ndk_root = self.ndk_root()
        if ndk_root:
            print(ndk_root, end='')
            return 0
        return self.ENOENT

    def run__cargo_exec(self):
        import time
        import subprocess
        if len(self.args) < 1:
            print('Invalid parameter {} for cargo-exec'.format(
                self.args), file=sys.stderr)
            return self.EFAIL
        ws_dir = os.environ.get('CARGO_WORKSPACE_DIR', '.')
        cfg_file = self.args[0] if self.args[0].endswith(
            '.toml') else os.path.join(self.args[0], 'Cargo.toml')
        cargo_toml = os.path.join(ws_dir, cfg_file) if os.path.isfile(
            os.path.join(ws_dir, cfg_file)) else cfg_file
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
                    'toml is not installed. Please execute: pip install toml', file=sys.stderr)
                return self.EFAIL
        package = cargo['package']
        os.environ['CARGO_CRATE_NAME'] = package['name']
        os.environ['CARGO_PKG_NAME'] = package['name']
        os.environ['CARGO_PKG_VERSION'] = package['version']
        os.environ['CARGO_MAKE_TIMESTAMP'] = '{}'.format(time.time())
        return subprocess.call(' '.join(self.args[1:]), shell=True)

    def run__upload(self):
        import urllib.parse
        import glob

        if len(self.args) < 2:
            print(
                'Invalid parameter {} for upload'.format(self.args), file=sys.stderr)
            return self.EFAIL

        ftp_path = self.args[0]
        files = self.args[1:]

        parsed = urllib.parse.urlparse(ftp_path)
        if not parsed.hostname:
            print('No hostname'.format(self.args), file=sys.stderr)
            return self.EINVAL
        scheme = parsed.scheme
        hostname = parsed.hostname
        port = int(parsed.port) if parsed.port else 0
        url = scheme + '://' + \
            ('{}:{}'.format(hostname, port) if port else hostname)
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
                ftp.prot_p()
            ftp.set_pasv(True)
        elif scheme == 'sftp':
            try:
                import paramiko
            except ImportError:
                print(
                    'paramiko is not installed. Please execute: pip install paramiko', file=sys.stderr)
                return self.EFAIL
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname, port or 22, username, password)
            sftp = ssh.open_sftp()
        else:
            print('Unsupported protocol: {}'.format(scheme), file=sys.stderr)
            return self.EINVAL

        for item in files:
            pair = item.split('=')
            for local_path in glob.glob(pair[-1]):
                if not os.path.isdir(local_path):
                    remote_path = os.path.basename(
                        local_path) if len(pair) == 1 else pair[0]
                    if not remote_path.startswith('/'):
                        remote_path = '/'.join([remote_dir, remote_path])
                    if remote_path.endswith('/'):
                        remote_path = '/'.join([remote_path,
                                               os.path.basename(local_path)])
                    while '//' in remote_path:
                        remote_path = remote_path.replace('//', '/')

                    print('Upload "{}"'.format(local_path))
                    print('    to "{}{}" ...'.format(
                        url, remote_path), end="", flush=True)
                    if ftp is not None:
                        with open(local_path, 'rb') as fp:
                            ftp.storbinary('STOR {}'.format(remote_path), fp,
                                           32 * 1024, callback=lambda _sent: print('.', end='', flush=True))
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

    def run__build_target_deps(self):
        import traceback
        try:
            args = {k.strip().lower(): v for (
                k, v) in map(lambda x: x.split('=', 1), self.args)}
            TargetParser(**args).parse().build()
        except Exception:
            traceback.print_exc(file=sys.stderr)
            return 1
        return 0

    def run__zig_patch(self):
        TargetParser.zig_patch()
        return 0

    @classmethod
    def makedirs(Self, dir):
        if not os.path.isdir(dir):
            os.makedirs(dir)

    @classmethod
    def lock_file(Self, path=None, unlock=None):
        if unlock is None:
            if not os.path.exists(os.path.dirname(path)):
                Self.makedirs(os.path.dirname(path))
            f = open(path, 'a+')
        else:
            f = unlock
        try:
            # Posix based file locking (Linux, Ubuntu, MacOS, etc.)
            #   Only allows locking on writable files, might cause
            #   strange results for reading.
            import fcntl
            if unlock is None:
                fcntl.lockf(f, fcntl.LOCK_EX)
                return f
            else:
                fcntl.lockf(f, fcntl.LOCK_UN)
                unlock.close()
        except ModuleNotFoundError:
            # Windows file locking
            import msvcrt

            def file_size(f):
                return os.path.getsize(os.path.realpath(f.name))
            if unlock is None:
                msvcrt.locking(f.fileno(), msvcrt.LK_RLCK, file_size(f))
                return f
            else:
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, file_size(f))
                unlock.close()

    @classmethod
    def win2wsl_path(Self, path):
        if os.path.isabs(path):
            path = os.path.abspath(path)
        path = path.replace('\\', '/')
        drive_path = path.split(':', 1)
        if len(drive_path) > 1 and len(drive_path[0]) == 1 and drive_path[0].isalpha():
            path = '/mnt/{}{}'.format(drive_path[0].lower(),
                                      drive_path[1]).rstrip('/')
        return path

    @classmethod
    def wsl2win_path(Self, path):
        if os.path.isabs(path):
            path = os.path.abspath(path)
        path = path.replace('\\', '/')
        if len(path) >= 6 and path.startswith('/mnt/') and path[5].isalpha():
            if len(path) == 6:
                path = path[5].upper() + ':/'
            elif path[6] == '/':
                path = '{}:{}'.format(path[5].upper(), path[6:])
        return path

    @classmethod
    def ndk_root(Self, check_env=False):
        if check_env:
            ndk_root = os.environ.get('ANDROID_NDK_ROOT', '')
            if ndk_root and os.path.isdir(ndk_root):
                os.environ['ANDROID_NDK_HOME'] = ndk_root
                return ndk_root

        sdk_dir = ''
        if 'ANDROID_HOME' in os.environ:
            sdk_dir = os.path.join(os.environ['ANDROID_HOME'], 'ndk')
        elif sys.platform != 'win32':
            for dir in ('/opt/ndk', '/opt/android/ndk', '/opt/android/sdk/ndk',):
                if os.path.isdir(dir):
                    sdk_dir = dir
                    break
        if not sdk_dir:
            print('The environment variable `ANDROID_HOME` is not set.',
                  file=sys.stderr)
            return ''

        try:
            import re
            pattern1 = re.compile(r'^(\d+)\.(\d+)\.(\d+)(?:\.\w+)?$')
            pattern2 = re.compile(r'^android-ndk-r(\d+)([a-z]+)$')
            ndk_dirs = []
            for name in os.listdir(sdk_dir):
                if not os.path.isfile(os.path.join(sdk_dir, name, 'build', 'cmake', 'android.toolchain.cmake')):
                    continue
                group = pattern1.match(name)
                if group:
                    ndk_dirs.append(
                        (name, [int(group[1]), int(group[2]), int(group[3])]))
                    continue
                group = pattern2.match(name)
                if group:
                    ndk_dirs.append((
                        name, [int(group[1]),
                               int(''.join(chr(ord(x) + ord('0') - ord('a'))
                                           for x in group[2])),
                               0]
                    ))
                    continue
            if ndk_dirs:
                (dir, _) = sorted(
                    ndk_dirs, key=lambda x: x[1], reverse=True)[0]
                ndk_root = os.path.join(sdk_dir, dir).replace('\\', '/')
                if check_env:
                    os.environ['ANDROID_NDK_ROOT'] = ndk_root
                    os.environ['ANDROID_NDK_HOME'] = ndk_root
                return ndk_root
        except OSError:
            pass
        return ''

    @classmethod
    def main(Self, args=None):
        args = args or sys.argv[1:]
        try:
            from argparse import ArgumentParser, RawTextHelpFormatter
            parser = ArgumentParser(formatter_class=RawTextHelpFormatter)
            parser.add_argument('-D', '--symlinkd',
                                action='store_true', default=False, dest='symlinkd',
                                help='creates a directory symbolic link')
            parser.add_argument('-e', '--empty-dirs',
                                action='store_true', default=False, dest='remove_empty_dirs',
                                help='remove all empty directories')
            parser.add_argument('-f', '--force',
                                action='store_true', default=False, dest='force',
                                help='ignore errors, never prompt')
            parser.add_argument('--list',
                                action='store_true', default=False, dest='list_cmds',
                                help='list all commands')
            parser.add_argument('-P', '--no-dereference',
                                action='store_false', default=True, dest='follow_symlinks',
                                help='always follow symbolic links in SOURCE')
            parser.add_argument('-p', '--parents',
                                action='store_true', default=True, dest='parents',
                                help='if existing, make parent directories as needed')
            parser.add_argument('-r', '-R', '--recursive',
                                action='store_true', default=False, dest='recursive',
                                help='copy/remove directories and their contents recursively')
            parser.add_argument('--args-from-stdin', '--stdin',
                                action='store_true', default=False, dest='args_from_stdin',
                                help='read arguments from stdin')
            parser.add_argument('command', nargs='?', default='')
            parser.add_argument('args', nargs='*', default=[])
            namespace = parser.parse_intermixed_args(args)

            if namespace.list_cmds:
                for name in dir(Self(namespace)):
                    if name.startswith('run__'):
                        print(name[5:])
                return 0

            try:
                return getattr(Self(namespace),
                               'run__' + namespace.command.replace('-', '_'))()
            except AttributeError:
                if not namespace.command:
                    print('Missing command', file=sys.stderr)
                else:
                    print('Unrecognized command "{}"'.format(
                        namespace.command), file=sys.stderr)
            return Self.EINVAL

        except PermissionError as e:
            print(e)
            return Self.EFAIL

        except KeyboardInterrupt:
            print('^C', file=sys.stderr)
            return Self.EINTERRUPT


class TargetParser(ShellCmd):
    HOST_SYSTEM_MAP = (
        ('cygwin_nt', 'cygwin'),
        ('msys_nt', 'mingw'),
        ('mingw32_nt', 'mingw'),
        ('mingw64_nt', 'mingw'),
        ('darwin', 'macos'),
    )
    # Host ARCH -> Rust ARCH
    HOST_ARCH_MAP = {
        'x86': 'i686',
        'i686': 'i686',
        'amd64': 'x86_64',
        'x64': 'x86_64',
        'x86_64': 'x86_64',
        'aarch64': 'aarch64',
    }

    VENDOR_LIST = ('pc', 'apple', 'sun', 'nvidia', 'unknown',)
    OS_LIST = ('windows', 'linux', 'macos', 'darwin', 'ios', 'freebsd',
               'netbsd', 'solaris', 'redox', 'fuchsia', 'cuda', 'uefi', 'none',)
    OS_PREFIXES = ('wasi',)
    ENV_LIST = ('msvc', 'android', 'gnu', 'musl', 'sgx', 'elf', 'ohos',)
    ENV_PREFIXES = ('msvc', 'android', 'gnu', 'musl',)
    ENV_SUFFIXES = ('eabi', 'eabihf', 'llvm',)

    RUST_ARCH_MAP = {
        'arm': 'armv7',  # Upgrade arm to armv7
        'armv7': 'armv7',
        'armv7a': 'armv7',
        'thumb': 'thumbv7neon',
        'thumbv7neon': 'thumbv7neon',
        'arm64': 'aarch64',
        'aarch64': 'aarch64',
        'x86': 'i686',
        'i586': 'i686',  # Upgrade i586 to i686
        'i686': 'i686',
        'win32': 'i686',
        'x64': 'x86_64',
        'x86_64': 'x86_64',
    }
    # Rust ARCH -> MSVC ARCH
    MSVC_ARCH_MAP = {
        'aarch64': 'ARM64',
        'i586': 'Win32',
        'i686': 'Win32',
        'x86_64': 'x64',
    }
    # Rust ARCH -> Android ARCH
    ANDROID_ARCH_MAP = {
        'i686': 'i686',
        'x86_64': 'x86_64',
        'armv7': 'armv7a',
        'thumbv7neon': 'armv7a',
        'aarch64': 'aarch64',
    }
    # Rust ARCH -> Android ABI (JNI Directory Name)
    ANRDOID_ABI_MAP = {
        'i686': 'x86',
        'x86_64': 'x86_64',
        'armv7': 'armeabi-v7a',
        'thumbv7neon': 'armeabi-v7a',
        'aarch64': 'arm64-v8a',
    }
    # Rust ARCH -> Android ARCH
    APPLE_ARCH_MAP = {
        'x86_64': 'x86_64',
        'aarch64': 'aarch64',
    }
    ZIG_ARCH_MAP = {
        'i686': 'x86',
        'x86_64': 'x86_64',
        'armv7': 'arm',
        'thumbv7neon': 'thumb',
        'aarch64': 'aarch64',
    }
    ZIG_OS_MAP = {
        'darwin': 'macos',
        'ios-sim': 'ios',
    }

    GCC_ENV_KEYS = (
        'BINDGEN_EXTRA_CLANG_ARGS',
        'CPATH',
        'C_INCLUDE_PATH',
        'CPLUS_INCLUDE_PATH',
        'OBJC_INCLUDE_PATH',
        'COMPILER_PATH',
        'LIBRARY_PATH',
    )

    def __init__(self,
                 workspace_dir='',
                 target='',
                 target_dir='',
                 target_cmake_dir='',
                 cmake_target_prefix='',
                 cargo_target='',
                 zig_target='',
                 target_cc='',
                 **_args):
        host_target_info = self.host_target_info()

        # Const variables
        self.host_system = host_target_info['host_system']
        self.host_system_ext = host_target_info['system']
        self.host_arch = host_target_info['arch']
        self.host_os = host_target_info['os']
        self.host_vendor = host_target_info['vendor']
        self.host_env = host_target_info['env']
        self.host_target = host_target_info['triple']
        self.script_dir = self.normpath(
            os.path.abspath(os.path.dirname(__file__)))

        # Input parameters
        self.workspace_dir = self.normpath(os.path.abspath(
            workspace_dir or os.path.join(self.script_dir, '..')))
        self.target = target
        self.target_is_native = False
        self.target_dir = self.normpath(os.path.abspath(
            target_dir or os.path.join(self.workspace_dir, 'target')))
        self.target_cmake_dir = self.normpath(os.path.abspath(
            target_cmake_dir or (self.target_dir + '/.cmake')))
        self.cmake_lock_file = self.normpath(os.path.join(
            self.target_cmake_dir, '{}.cmake.lock'.format(self.host_system)))
        self.cmake_target_prefix = self.normpath(os.path.abspath(
            cmake_target_prefix or (self.target_cmake_dir + '/output')))
        self.cmake_prefix_triple = ''
        self.cmake_prefix_subdirs = []
        self.cargo_target = cargo_target
        self.zig_target = zig_target
        self.target_cc = target_cc

        # Parsed triple
        self.arch = ''
        self.vendor = ''
        self.os = ''
        self.env = ''

        # Built-in variables in CMake
        self.win32 = False
        self.msvc = False
        self.android = False
        self.unix = False
        self.apple = False
        self.ios = False

        # Cargo
        self.cargo_target_dir = ''
        # CMake
        self.cmake_generator = ''
        self.cmake_target_dir = ''

        # Windows
        self.msvc_arch = ''
        # Android
        self.android_ndk_root = ''
        self.android_ndk_bin = ''
        self.android_target = ''
        self.android_arch = ''
        self.android_abi = ''
        # Zig
        self.zig = False
        self.zig_root = ''
        self.zig_cc_dir = ''
        # Include paths
        self.c_includes = []
        self.cxx_includes = []

    @property
    def host_is_windows(self):
        return self.host_system == 'Windows'

    # Check if the host is a POSIX system (mingw, cygwin) on Windows.
    @property
    def host_is_win_posix(self):
        return self.host_system_ext in ['mingw', 'cygwin']

    @property
    def host_is_mingw(self):
        return self.host_system_ext  == 'mingw'

    @property
    def host_is_cygwin(self):
        return self.host_system_ext  == 'cygwin'

    @property
    def host_is_unix(self):
        return self.host_system != 'Windows'

    @property
    def host_is_linux(self):
        return self.host_system == 'Linux'

    @property
    def host_is_macos(self):
        return self.host_system == 'Darwin'

    @property
    def target_cxx(self):
        stem, ext = os.path.splitext(os.path.basename(self.target_cc))
        if stem.endswith('clang'):
            cxx = stem[:-5] + 'clang++'
        elif stem.endswith('gcc'):
            cxx = stem[:-3] + 'g++'
        elif stem.endswith('cc'):
            cxx = stem[:-2] + 'c++'
        else:
            cxx = stem
        return self.target_cc[:-(len(stem) + len(ext))] + cxx + ext

    # Check if the host operating system is Windows.
    @ classmethod
    def normpath(Self, path):
        return os.path.normpath(path).replace('\\', '/')

    @ classmethod
    def need_update(Self, source_file, dest_file):
        return not os.path.isfile(dest_file) or (
            os.path.getmtime(dest_file) < os.path.getmtime(source_file))

    @ classmethod
    def host_target_info(Self):
        import platform
        # (compatible with Make & CMake) Windows, Linux, Darwin
        host_system = 'Windows' if os.name == 'nt' else platform.uname()[0]
        # (not for Cargo) windows, linux, macos, mingw, cygwin
        target_system = ''
        # windows, unix, wasm
        target_family = ''
        # windows, linux, macos, android, ios ..., none
        target_os = ''
        # i686(i586, ???x86), x86_64, arm, aarch64, ...
        target_arch = ''
        # pc, apple, fortanix, unknown
        target_vendor = ''
        # msvc, gnu, musl, sgx, ...
        target_env = ''
        # 16, 32, 64
        target_pointer_width = 64
        # little, big
        target_endian = sys.byteorder
        # (separate by comma) mmx, sse, sse2, sse4.1, avx, avx2, rdrand, crt-static, ...
        target_feature = ''
        # arch-vendor-os-env
        target_triple = ''

        # target_system <- platform.system()
        if os.environ.get("MSYSTEM") in ("MSYS", "MINGW32", "MINGW64"):
            target_system = 'mingw'
        else:
            target_system = platform.system().lower()
            for k, v in Self.HOST_SYSTEM_MAP:
                if target_system.startswith(k):
                    target_system = v
                    break
        # target_family, target_os
        if target_system in ('windows', 'cygwin', 'mingw'):
            target_family = 'windows'
            target_os = 'windows'
        else:
            target_family = 'unix'
            target_os = target_system
        # target_pointer_width, target_arch
        machine = platform.machine()
        if '64' not in machine:
            target_pointer_width = 32
        target_arch = Self.HOST_ARCH_MAP.get(machine.lower())
        if target_arch is None:
            raise RuntimeError(
                'Not supported machine architecture: {}'.format(machine))
        # target_vendor
        if target_os == 'windows':
            target_vendor = 'pc'
        elif target_system in 'macos':
            target_vendor = 'apple'
        else:
            target_vendor = 'unknown'
        # target_env
        if target_os == 'windows':
            target_env = 'msvc'
        elif target_system in ('linux', 'cygwin', 'mingw'):
            target_env = 'gnu'
        # target_triple
        target_triple = Self.join_triple(
            target_arch, target_vendor, target_os, target_env
        )

        return {
            'host_system': host_system,
            'system': target_system,
            'family': target_family,
            'os': target_os,
            'arch': target_arch,
            'vendor': target_vendor,
            'env': target_env,
            'pointer_width': target_pointer_width,
            'endian': target_endian,
            'feature': target_feature,
            'triple': target_triple,
        }

    @ classmethod
    def join_triple(Self, arch, vendor, os, env):
        return '{}{}{}{}{}{}{}'.format(
            arch,
            '-' if vendor else '',
            vendor or '',
            '-' if os else '',
            os or '',
            '-' if env else '',
            env or '',
        )

    @ classmethod
    def parse_triple(Self, target_triple):
        triple = target_triple.lower().split('-')

        # Fix up '-ios-sim'
        if len(triple) > 2 and triple[-1] == 'sim':
            triple[-2] += '-' + triple[-1]
            triple = triple[:-1]

        (arch, vendor, os_str, env_str) = (triple[0], '', '', '')

        def is_vendor_str(s):
            return s in Self.VENDOR_LIST

        def is_os_str(s):
            return (s in Self.OS_LIST or
                    any(map(lambda x: s.startswith(x), Self.OS_PREFIXES)))

        def is_env_str(s):
            return (s in Self.ENV_LIST or
                    any(map(lambda x: s.startswith(x), Self.ENV_PREFIXES)) or
                    any(map(lambda x: s.endswith(x), Self.ENV_SUFFIXES)))

        if len(triple) == 1:
            pass
        elif len(triple) == 2:
            os_str = triple[1]
        elif len(triple) == 3:
            if is_os_str(triple[1]):
                os_str = triple[1]
                env_str = triple[2]
            elif is_os_str(triple[2]):
                vendor = triple[1]
                os_str = triple[2]
            if is_vendor_str(triple[1]):
                vendor = triple[1]
                if is_env_str(triple[2]):
                    env_str = triple[2]
                elif not os_str:
                    os_str = triple[2]
            if is_env_str(triple[2]):
                env_str = triple[2]
                if not vendor and not os_str:
                    os_str = triple[1]
        else:
            vendor = triple[1]
            os_str = triple[2]
            env_str = triple[3]

        rust_arch = Self.RUST_ARCH_MAP.get(arch) or arch
        if 'windows' in target_triple and (
                os_str != 'windows' or rust_arch not in Self.MSVC_ARCH_MAP):
            raise ValueError(
                'Invalid ARCH for Windows: {}'.format(target_triple))
        if 'android' in target_triple and (
            not env_str.startswith('android') or
                os_str != 'linux' or rust_arch not in Self.ANDROID_ARCH_MAP):
            raise ValueError(
                'Invalid ARCH for Android: {}'.format(target_triple))
        if 'apple' in target_triple and (
                vendor != 'apple' and rust_arch not in Self.APPLE_ARCH_MAP):
            raise ValueError(
                'Invalid ARCH for Apple: {}'.format(target_triple))

        parsed_triple = Self.join_triple(arch, vendor, os_str, env_str)
        if not arch or not os_str or parsed_triple != target_triple:
            raise ValueError('Invalid target triple: {}'.format(target_triple))

        return (arch, vendor, os_str, env_str)

    def parse(self):
        import shutil

        self.target_is_native = self.target in ('', 'native')
        if self.target_is_native:
            self.target = self.host_target

        (self.arch, self.vendor, self.os, self.env) = (
            self.parse_triple(self.target))
        self.arch = self.RUST_ARCH_MAP.get(self.arch) or self.arch

        if self.os == 'windows':
            self.win32 = True
            if self.env == 'msvc':
                self.msvc = True
                self.msvc_arch = self.MSVC_ARCH_MAP[self.arch]
            # Cargo
            self.cargo_target = (self.cargo_target or self.join_triple(
                self.arch, 'pc', 'windows', self.env))
            # Zig
            zig_target = self.join_triple(
                self.ZIG_ARCH_MAP.get(self.arch) or self.arch, '', 'windows', self.env)
        elif self.env.startswith('android'):
            self.android = True
            self.unix = True
            # NDK
            self.android_target = self.join_triple(
                self.ANDROID_ARCH_MAP[self.arch], '', 'linux', self.env)
            self.android_arch = self.ANDROID_ARCH_MAP[self.arch]
            self.android_abi = self.ANRDOID_ABI_MAP[self.arch]
            # Cargo
            self.cargo_target = (self.cargo_target or self.join_triple(
                self.arch, '', 'linux', self.env))
            # Zig
            zig_target = self.join_triple(
                self.ZIG_ARCH_MAP.get(self.arch) or self.arch, '', 'linux', self.env)
            # CMake
            self.cmake_generator = 'Ninja'
        elif self.os == 'linux':
            self.unix = True
            # Cargo
            self.cargo_target = (self.cargo_target or self.join_triple(
                self.arch, 'unknown', 'linux', self.env))
            # Zig
            zig_target = self.join_triple(
                self.ZIG_ARCH_MAP.get(self.arch) or self.arch, '', 'linux', self.env)
        elif self.vendor == 'apple':
            self.apple = True
            self.unix = True
            self.ios = 'ios' in self.os
            # Cargo
            self.cargo_target = (self.cargo_target or self.join_triple(
                self.arch, 'apple', self.os, ''))
            # Zig
            zig_target = self.join_triple(
                self.ZIG_ARCH_MAP.get(self.arch) or self.arch, '',
                self.ZIG_OS_MAP.get(self.os) or self.os, 'none')
        else:
            self.unix = True
            # Cargo
            self.cargo_target = (self.cargo_target or self.join_triple(
                self.arch, self.vendor, self.os, self.env))
            # Zig
            zig_target = self.join_triple(
                self.ZIG_ARCH_MAP.get(self.arch) or self.arch, '', self.os, self.env)

        # Find the cross compiler.
        self.zig = (os.path.splitext(
            os.path.basename(self.target_cc))[0] in ('zig', 'zig-cc',))
        if (not self.target_is_native and not self.android and not self.zig and
                (not self.target_cc or not shutil.which(self.target_cc)) and
                self.cargo_target != self.host_target):
            # Try gcc cross-compiler.
            target_cc = shutil.which(
                self.target + '-gcc' + self.EXE_EXT) or shutil.which(self.target + '-cc' + self.EXE_EXT)
            if target_cc:
                self.target_cc = self.normpath(target_cc)
            elif (self.vendor != self.host_vendor or self.os != self.host_os or 
                  self.env != self.host_env) or (self.host_is_linux and self.os == 'linux'):
                # Try Zig cross-compiler.
                zig = shutil.which('zig' + self.EXE_EXT)
                if zig:
                    self.zig = True

        # Zig
        if self.zig:
            if not self.zig_target:
                self.zig_target = zig_target
            self.cmake_generator = 'Ninja' if self.host_is_windows else 'Unix Makefiles'

        if self.target == self.cargo_target:
            self.cargo_target_dir = self.target_dir
        else:
            self.cargo_target_dir = '{}/{}'.format(
                self.target_dir, self.target)

        self.cmake_prefix_triple = '{}/{}'.format(
            self.cmake_target_prefix, self.target)
        # Add the CMake target as a subdirectory.
        self.cmake_prefix_subdirs.clear()
        self.cmake_prefix_subdirs.append(self.cmake_prefix_triple)
        # If the Cargo target is not equal to the CMake target, add it as a subdirectory.
        if self.target != self.cargo_target:
            self.cmake_prefix_subdirs.append(
                '{}/{}'.format(self.cmake_target_prefix, self.cargo_target))
        self.cmake_prefix_subdirs.append(
            '{}/any'.format(self.cmake_target_prefix))
        return self

    def _cmake_init(self):
        self.cmake_target_dir = '{}/{}{}'.format(
            self.target_cmake_dir, self.target, '.native' if self.target_is_native else '')
        self.makedirs(self.cmake_target_dir)

    def _zig_init(self):
        import subprocess
        import shutil
        import glob

        # Zig root path and include directories.
        zig_path = shutil.which('zig' + self.EXE_EXT)
        if not zig_path:
            raise FileNotFoundError('`zig` is not found')
        self.zig_root = self.normpath(
            os.path.realpath(os.path.dirname(zig_path)))

        self.zig_cc_dir = self.normpath(os.path.join(
            self.target_dir, '.zig', self.host_target))
        src = self.script_dir + '/zig-wrapper.zig'
        exe = self.zig_cc_dir + '/zig-wrapper' + self.EXE_EXT
        dir = self.zig_cc_dir

        self.makedirs(dir)
        if self.need_update(src, exe):
            for file in glob.glob(os.path.join(dir, '*')):
                if not os.path.isdir(file):
                    os.unlink(file)
            # Compile wrapper
            subprocess.run(['zig' + self.EXE_EXT, 'cc', '-s', '-Os', '-o', exe, src],
                           env=self.copy_env_for_cc(), check=True)
            os.chmod(exe, 0o755)
            for file in glob.glob(os.path.join(dir, exe + '.*')):
                os.unlink(file)
            for name in ['ar', 'cc', 'c++', 'dlltool', 'lib', 'ranlib', 'objcopy', 'rc']:
                dst = os.path.join(dir, 'zig-' + name + self.EXE_EXT)
                os.symlink(os.path.basename(exe), dst)

        # Override the target CC for Zig.
        self.target_cc = self.normpath(
            self.zig_cc_dir + '/zig-cc' + self.EXE_EXT)

        # Get include paths.
        def cc_cmd_args(cc):
            return [cc, '-target', self.zig_target]
        self.c_includes = self._get_cc_includes(cc_cmd_args(self.target_cc), 'c')
        self.cxx_includes = self._get_cc_includes(cc_cmd_args(self.target_cxx), 'c++')

    @classmethod
    def zig_patch(Self):
        import shutil

        zig_path = shutil.which('zig' + Self.EXE_EXT)
        if not zig_path:
            return
        zig_root = os.path.realpath(os.path.dirname(zig_path))
        any_linux_any = os.path.join(
            zig_root, 'lib', 'libc', 'include', 'any-linux-any')

        # 1. <sys/sysctl.h> is required by ffmpeg 6.0
        sys_ctl_h = os.path.join(any_linux_any, 'sys', 'sysctl.h')
        sys_ctl_h_src = os.path.join(any_linux_any, 'linux', 'sysctl.h')
        if not os.path.exists(sys_ctl_h) and os.path.isfile(sys_ctl_h_src):
            Self.makedirs(os.path.dirname(sys_ctl_h))
            os.symlink(os.path.relpath(
                sys_ctl_h_src, os.path.dirname(sys_ctl_h)), sys_ctl_h)

    def _cc_init(self):
        if not os.path.isfile(self.target_cc):
            import shutil
            target_cc = shutil.which(self.target_cc)
            if not target_cc:
                raise FileNotFoundError(
                    "Target CC is not found: {}".format(self.target_cc))
            self.target_cc = self.normpath(target_cc)

        # Get include paths.
        self.c_includes = self._get_cc_includes([self.target_cc], 'c')
        self.cxx_includes = self._get_cc_includes([self.target_cxx], 'c++')

    def _android_init(self):
        self.android_ndk_root = self.normpath(
            self.ndk_root(check_env=True))
        self.android_ndk_bin = self.android_ndk_root + \
            '/toolchains/llvm/prebuilt/{}-{}/bin'.format(
                self.host_system.lower(), self.host_arch.lower())
        if not self.android_ndk_root or not os.path.isdir(self.android_ndk_root):
            raise FileNotFoundError(
                'Android NDK is not found: ', self.android_ndk_root)
        if not self.android_ndk_bin or not os.path.isdir(self.android_ndk_bin):
            raise FileNotFoundError(
                'Android NDK Clang compiler is not found:', self.android_ndk_bin)

        # Override the target CC for NDK.
        self.target_cc = '{}/clang{}'.format(
            self.android_ndk_bin, self.EXE_EXT)

        # Get include paths.
        def cc_cmd_args(cc):
            return [cc, '--target={}'.format(self.android_target)]
        self.c_includes = self._get_cc_includes(cc_cmd_args(self.target_cc), 'c')
        self.cxx_includes = self._get_cc_includes(cc_cmd_args(self.target_cxx), 'c++')

    @classmethod
    def _get_cc_includes(Self, cmd_args, lang='c'):
        import subprocess
        result = subprocess.run(cmd_args + ['-E', '-x', lang, '-', '-v'],
                                stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                text=True,
                                env=Self.copy_env_for_cc())
        start_marker = '#include <...> search starts here:'
        end_marker = 'End of search list.'
        output = result.stderr
        # Find the start and end indices
        start = output.find(start_marker)
        end = output.find(end_marker, start)
        # Extract the lines between the markers if both markers are found
        if start >= 0 and end >= 0:
            text = output[start + len(start_marker):end]
            return [line for line in map(lambda x: x.strip().replace(os.sep, '/'),
                                         text.splitlines()) if line]
        return []

    @classmethod
    def copy_env_for_cc(Self):
        # Remove GCC environment variables.
        return {k: v for (k, v) in os.environ.items() if k not in Self.GCC_ENV_KEYS}

    def build(self):
        file = self.lock_file(path=self.cmake_lock_file)
        try:
            self._build()
        finally:
            self.lock_file(unlock=file)

    def _build(self):
        if self.android:
            self._android_init()
        elif self.zig:
            self._zig_init()
        elif self.target_cc:
            self._cc_init()
        self._cmake_init()

        def fwrite(f, s):
            f.write(s.encode('utf-8'))

        def onoff(b):
            return 'ON' if b else 'OFF'

        def join_paths(paths, subdirs=None):
            return ['/'.join([p, s]) for p in paths for s in subdirs] if subdirs else paths

        def make_export_paths(name, paths, subdirs=None):
            value = os.pathsep + \
                os.pathsep.join(join_paths(paths, subdirs)) + os.pathsep
            export_only = False
            if name == 'PATH':
                value = '$(subst /,$(SEP),{})'.format(value)
                export_only = True
            return ''.join([
                '# Environment variable `{}`\n'.format(name),
                '_s := {}\n'.format(value),
                'ifeq ($(findstring $(_s),$({})),)\n'.format(name),
                '    {} {} := $(_s)$({})\n'.format(
                    'export' if export_only else 'override', name, name),
                '    export {}\n'.format(name) if not export_only else '',
                'endif\n',
            ])

        def cmake_export_paths(name, paths, subdirs=None):
            env_name = 'ENV{{{}}}'.format(name)
            value = os.pathsep + \
                os.pathsep.join(join_paths(paths, subdirs)) + os.pathsep
            return ''.join([
                '# Environment variable `{}`\n'.format(name),
                'set(_s "{}")\n'.format(value),
                'string(FIND "${}" "${{_s}}" _n)\n'.format(env_name),
                'if(_n EQUAL -1)\n',
                '    set({} "${{_s}}${}")\n'.format(env_name, env_name),
                'endif()\n',
            ])

        with open(os.path.join(self.target_cmake_dir, '{}.host.mk'.format(self.host_system)), 'wb') as f:
            fwrite(f, 'override HOST_SYSTEM = {}\n'.format(self.host_system))
            fwrite(f, 'override HOST_TARGET = {}\n'.format(self.host_target))
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            fwrite(f, 'override HOST_SEP := $(strip {})\n'.format(os.sep))
            fwrite(f, 'override HOST_PATHSEP = {}\n'.format(os.pathsep))
            fwrite(f, 'override HOST_EXE_EXT = {}\n'.format(self.EXE_EXT))
            fwrite(f, '\n')
            fwrite(f, '# Unexport environment variables that may affect the CC compiler.\n')
            for key in self.GCC_ENV_KEYS:
                fwrite(f, 'unexport {}\n'.format(key))

        with open(os.path.join(self.target_cmake_dir, '{}.host.cmake'.format(self.host_system)), 'wb') as f:
            fwrite(f, 'set(HOST_SYSTEM "{}")\n'.format(self.host_system))
            fwrite(f, 'set(HOST_TARGET "{}")\n'.format(self.host_target))
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            fwrite(f, 'set(HOST_SEP "{}")\n'.format(
                os.sep.replace('\\', '\\\\')))
            fwrite(f, 'set(HOST_PATHSEP "{}")\n'.format(os.pathsep))
            fwrite(f, 'set(HOST_EXE_EXT "{}")\n'.format(self.EXE_EXT))

        with open(os.path.join(self.cmake_target_dir, '{}.vars.mk'.format(self.host_system)), 'wb') as f:
            fwrite(f, '# Constants for the target platform\n')
            fwrite(f, 'override TARGET_SEP := $(strip {})\n'.format(
                '\\' if self.win32 else '/'))
            fwrite(f, 'override TARGET_PATHSEP = {}\n'.format(
                ';' if self.win32 else ':'))
            fwrite(f, 'override TARGET_EXE_EXT = {}\n'.format(
                '.exe' if self.win32 else ''))
            fwrite(f, '\n')

            fwrite(f, '# Constant directories\n')
            fwrite(f, 'override WORKSPACE_DIR = {}\n'.format(self.workspace_dir))
            fwrite(f, 'override TARGET_DIR = {}\n'.format(self.target_dir))
            fwrite(f, 'override TARGET_CMAKE_DIR = {}\n'.format(
                self.target_cmake_dir))
            fwrite(f, 'override CMAKE_LOCK_FILE = {}\n'.format(
                self.cmake_lock_file))
            fwrite(f, 'override CMAKE_TARGET_PREFIX = {}\n'.format(
                self.cmake_target_prefix))
            fwrite(f, 'override CMAKE_PREFIX_TRIPLE = {}\n'.format(
                self.cmake_prefix_triple))
            fwrite(f, 'override CMAKE_PREFIX_SUBDIRS = {}\n'.format(
                ' '.join(self.cmake_prefix_subdirs)))
            fwrite(f, 'override CMAKE_PREFIX_BINS = {}\n'.format(
                ' '.join(map(lambda x: x + '/bin', self.cmake_prefix_subdirs))))
            fwrite(f, 'override CMAKE_PREFIX_LIBS = {}\n'.format(
                ' '.join(map(lambda x: x + '/lib', self.cmake_prefix_subdirs))))
            fwrite(f, 'override CMAKE_PREFIX_INCLUDES = {}\n'.format(
                ' '.join(map(lambda x: x + '/include', self.cmake_prefix_subdirs))))
            fwrite(f, '\n')

            fwrite(f, '# Cargo\n')
            fwrite(f, 'override TARGET = {}\n'.format(self.target))
            fwrite(f, 'override TARGET_ARCH = {}\n'.format(self.arch))
            fwrite(f, 'override TARGET_VENDOR = {}\n'.format(self.vendor))
            fwrite(f, 'override TARGET_OS = {}\n'.format(self.os))
            fwrite(f, 'override TARGET_ENV = {}\n'.format(self.env))
            fwrite(f, 'override TARGET_CC = {}\n'.format(self.target_cc))
            fwrite(f, 'override CARGO_TARGET = {}\n'.format(self.cargo_target))
            fwrite(f, 'override CARGO_TARGET_UNDERSCORE = {}\n'.format(
                self.cargo_target.replace('-', '_')))
            fwrite(f, 'override CARGO_TARGET_UNDERSCORE_UPPER = {}\n'.format(
                self.cargo_target.replace('-', '_').upper()))
            fwrite(f, 'override CARGO_TARGET_DIR = {}\n'.format(
                self.cargo_target_dir))
            _cargo_target_out_dir = '{}/{}'.format(
                self.cargo_target_dir, '' if self.target_is_native else (self.cargo_target + '/'))
            fwrite(f, 'override CARGO_TARGET_OUT_DIR = {}$(call bsel,$(DEBUG),debug,release)\n'.format(
                _cargo_target_out_dir))
            fwrite(f, '\n')

            fwrite(f, '# CMake\n')
            fwrite(f, 'override CMAKE_GENERATOR = {}\n'.format(
                self.cmake_generator))
            fwrite(f, 'override CMAKE_TARGET_DIR = {}\n'.format(
                self.cmake_target_dir))
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, 'override MSVC_ARCH = {}\n'.format(self.msvc_arch))
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            fwrite(f, 'override ANDROID_TARGET = {}{}\n'.format(
                self.android_target, '$(ANDROID_SDK_VERSION)' if self.android_target else ''))
            fwrite(f, 'override ANDROID_ARCH = {}\n'.format(
                self.android_arch))
            fwrite(f, 'override ANDROID_ABI = {}\n'.format(
                self.android_abi))
            fwrite(f, 'override ANDROID_NDK_ROOT = {}\n'.format(
                self.android_ndk_root))
            fwrite(f, 'override ANDROID_NDK_BIN = {}\n'.format(
                self.android_ndk_bin))
            if self.android:
                fwrite(f, 'override CMAKE_SYSTEM_VERSION = $(ANDROID_SDK_VERSION)\n')
            fwrite(f, '\n')

            fwrite(f, '# Zig\n')
            fwrite(f, 'override ZIG = {}\n'.format(onoff(self.zig)))
            fwrite(f, 'override ZIG_TARGET = {}\n'.format(self.zig_target))
            fwrite(f, 'override ZIG_CC_DIR = {}\n'.format(self.zig_cc_dir))
            fwrite(f, 'override ZIG_ROOT = {}\n'.format(self.zig_root))
            fwrite(f, '\n')

            fwrite(f, '# Target related conditions\n')
            fwrite(f, 'override TARGET_IS_NATIVE = {}\n'.format(
                onoff(self.target_is_native)))
            fwrite(f, 'override TARGET_IS_WIN32 = {}\n'.format(onoff(self.win32)))
            fwrite(f, 'override TARGET_IS_MSVC = {}\n'.format(onoff(self.msvc)))
            fwrite(f, 'override TARGET_IS_ANDROID = {}\n'.format(
                onoff(self.android)))
            fwrite(f, 'override TARGET_IS_UNIX = {}\n'.format(onoff(self.unix)))
            fwrite(f, 'override TARGET_IS_APPLE = {}\n'.format(onoff(self.apple)))
            fwrite(f, 'override TARGET_IS_IOS = {}\n'.format(onoff(self.ios)))

        with open(os.path.join(self.cmake_target_dir, '{}.vars.cmake'.format(self.host_system)), 'wb') as f:
            fwrite(f, '# Constants for the target platform\n')
            fwrite(f, 'set(TARGET_SEP "{}")\n'.format(
                '\\\\' if self.win32 else '/'))
            fwrite(f, 'set(TARGET_PATHSEP "{}")\n'.format(
                ';' if self.win32 else ':'))
            fwrite(f, 'set(TARGET_EXE_EXT "{}")\n'.format(
                '.exe' if self.win32 else ''))
            fwrite(f, '\n')

            fwrite(f, '# Constant directories\n')
            fwrite(f, 'set(WORKSPACE_DIR "{}")\n'.format(self.workspace_dir))
            fwrite(f, 'set(TARGET_DIR "{}")\n'.format(self.target_dir))
            fwrite(f, 'set(TARGET_CMAKE_DIR "{}")\n'.format(
                self.target_cmake_dir))
            fwrite(f, 'set(TARGET_LOCK_FILE "{}")\n'.format(
                self.cmake_lock_file))
            fwrite(f, 'set(TARGET_PREFIX "{}")\n'.format(
                self.cmake_target_prefix))
            fwrite(f, 'set(TARGET_PREFIX_TRIPLE "{}")\n'.format(
                self.cmake_prefix_triple))
            fwrite(f, 'set(TARGET_PREFIX_SUBDIRS {})\n'.format(
                ' '.join(map(lambda x: '"{}"'.format(x), self.cmake_prefix_subdirs))))
            fwrite(f, 'set(TARGET_PREFIX_BINS {})\n'.format(
                ' '.join(map(lambda x: '"{}/bin"'.format(x), self.cmake_prefix_subdirs))))
            fwrite(f, 'set(TARGET_PREFIX_LIBS {})\n'.format(
                ' '.join(map(lambda x: '"{}/lib"'.format(x), self.cmake_prefix_subdirs))))
            fwrite(f, 'set(TARGET_PREFIX_INCLUDES {})\n'.format(
                ' '.join(map(lambda x: '"{}/include"'.format(x), self.cmake_prefix_subdirs))))
            fwrite(f, '\n')

            fwrite(f, '# Cargo\n')
            fwrite(f, 'set(TARGET "{}")\n'.format(self.target))
            fwrite(f, 'set(TARGET_ARCH "{}")\n'.format(self.arch))
            fwrite(f, 'set(TARGET_VENDOR "{}")\n'.format(self.vendor))
            fwrite(f, 'set(TARGET_OS "{}")\n'.format(self.os))
            fwrite(f, 'set(TARGET_ENV "{}")\n'.format(self.env))
            fwrite(f, 'set(TARGET_CC "{}")\n'.format(self.target_cc))
            fwrite(f, 'set(CARGO_TARGET "{}")\n'.format(self.cargo_target))
            fwrite(f, 'set(CARGO_TARGET_UNDERSCORE "{}")\n'.format(
                self.cargo_target.replace('-', '_')))
            fwrite(f, 'set(CARGO_TARGET_UNDERSCORE_UPPER "{}")\n'.format(
                self.cargo_target.replace('-', '_').upper()))
            fwrite(f, 'set(CARGO_TARGET_DIR "{}")\n'.format(
                self.cargo_target_dir))
            fwrite(f, 'if(CMAKE_BUILD_TYPE MATCHES "^(Debug|debug)$")\n')
            fwrite(f, '    set(CARGO_TARGET_OUT_DIR "{}debug")\n'.format(
                _cargo_target_out_dir))
            fwrite(f, 'else()\n')
            fwrite(f, '    set(CARGO_TARGET_OUT_DIR "{}release")\n'.format(
                _cargo_target_out_dir))
            fwrite(f, 'endif()\n')
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, 'set(MSVC_ARCH "{}")\n'.format(self.msvc_arch))
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            fwrite(f, 'set(ANDROID_TARGET "{}{}")\n'.format(
                self.android_target, '${ANDROID_SDK_VERSION}' if self.android_target else ''))
            fwrite(f, 'set(ANDROID_ARCH "{}")\n'.format(
                self.android_arch))
            fwrite(f, 'set(ANDROID_ABI "{}")\n'.format(
                self.android_abi))
            fwrite(f, 'set(ANDROID_NDK_ROOT "{}")\n'.format(
                self.android_ndk_root))
            fwrite(f, 'set(ANDROID_NDK_BIN "{}")\n'.format(self.android_ndk_bin))
            if self.android:
                fwrite(
                    f, 'set(CMAKE_SYSTEM_VERSION "${ANDROID_SDK_VERSION}")\n')
            fwrite(f, '\n')

            fwrite(f, '# Zig\n')
            fwrite(f, 'set(ZIG {})\n'.format(onoff(self.zig)))
            fwrite(f, 'set(ZIG_TARGET "{}")\n'.format(self.zig_target))
            fwrite(f, 'set(ZIG_CC_DIR "{}")\n'.format(self.zig_cc_dir))
            fwrite(f, 'set(ZIG_ROOT "{}")\n'.format(self.zig_root))
            fwrite(f, '\n')

            fwrite(f, '# Target related conditions\n')
            fwrite(f, 'set(TARGET_IS_NATIVE {})\n'.format(
                onoff(self.target_is_native)))
            fwrite(f, 'set(TARGET_IS_WIN32 {})\n'.format(onoff(self.win32)))
            fwrite(f, 'set(TARGET_IS_MSVC {})\n'.format(onoff(self.msvc)))
            fwrite(f, 'set(TARGET_IS_ANDROID {})\n'.format(onoff(self.android)))
            fwrite(f, 'set(TARGET_IS_UNIX {})\n'.format(onoff(self.unix)))
            fwrite(f, 'set(TARGET_IS_APPLE {})\n'.format(onoff(self.apple)))
            fwrite(f, 'set(TARGET_IS_IOS {})\n'.format(onoff(self.ios)))
            fwrite(f, '\n')
            fwrite(f, '# Suppress warnings\n')
            fwrite(f, 'set(ignoreMe "${CMAKE_VERBOSE_MAKEFILE}")\n')

        cc_exports = []
        cc_options = []
        linker_options = []
        (linker, ar, cc, cxx, ranlib, strip, rc) = ('', '', '', '', '', '', '')
        if self.android:
            cc_exports.append(
                'ANDROID_NDK_ROOT = {}'.format(self.android_ndk_root))
            cc_options.append(
                '--target={}$(ANDROID_SDK_VERSION)'.format(self.android_target))
            linker_options.extend(
                map(lambda x: '-C link-arg=' + x, cc_options))
            linker = '{}/clang++{}'.format(self.android_ndk_bin, self.EXE_EXT)
            ar = '{}/llvm-ar{}'.format(self.android_ndk_bin, self.EXE_EXT)
            cc = '{}/clang{}'.format(self.android_ndk_bin, self.EXE_EXT)
            cxx = '{}/clang++{}'.format(self.android_ndk_bin, self.EXE_EXT)
            ranlib = '{}/llvm-ranlib{}'.format(
                self.android_ndk_bin, self.EXE_EXT)
            strip = '{}/llvm-strip{}'.format(
                self.android_ndk_bin, self.EXE_EXT)
        elif self.zig:
            cc_exports.append(
                'ZIG_WRAPPER_TARGET = {}'.format(self.zig_target))
            cc_exports.append(
                'ZIG_WRAPPER_CLANG_TARGET = {}'.format(self.cargo_target))
            # On windows-gnu, linux-musl, and wasi targets:
            #     https://doc.rust-lang.org/rustc/codegen-options/index.html
            if ((self.os == 'windows' and self.env == 'gnu') or
                    (self.os == 'linux' and self.env == 'musl') or self.os.startswith('wasi')):
                linker_options.append('-C linker-flavor=gcc')
                linker_options.append('-C link-self-contained=no')
            linker = '{}/zig-c++{}'.format(self.zig_cc_dir, self.EXE_EXT)
            ar = '{}/zig-ar{}'.format(self.zig_cc_dir, self.EXE_EXT)
            cc = '{}/zig-cc{}'.format(self.zig_cc_dir, self.EXE_EXT)
            cxx = '{}/zig-c++{}'.format(self.zig_cc_dir, self.EXE_EXT)
            ranlib = '{}/zig-ranlib{}'.format(self.zig_cc_dir, self.EXE_EXT)
            strip = '{}/zig-strip{}'.format(self.zig_cc_dir, self.EXE_EXT)
            rc = '{}/zig-rc{}'.format(self.zig_cc_dir, self.EXE_EXT)
        elif self.target_cc:
            (target_cc, cc_ext) = os.path.splitext(self.target_cc)
            target_cc = self.normpath(os.path.abspath(target_cc))
            if self.host_is_windows:
                cc_ext = cc_ext.lower()
            if target_cc.endswith('-gcc'):
                cc_prefix = target_cc[:-4]
                cxx = cc_prefix + '-g++' + cc_ext
            elif target_cc.endswith('-cc'):
                cc_prefix = target_cc[:-3]
                cxx = cc_prefix + '-c++' + cc_ext
            else:
                raise ValueError(
                    "Unrecognized target CC: {}".format(target_cc))
            linker = target_cc + cc_ext
            cc = target_cc + cc_ext
            ar = cc_prefix + '-ar' + cc_ext
            ranlib = cc_prefix + '-ranlib' + cc_ext
            strip = cc_prefix + '-strip' + cc_ext

        with open(os.path.join(self.cmake_target_dir, '{}.toolchain.mk'.format(self.host_system)), 'wb') as f:
            if cc_exports:
                for line in cc_exports:
                    [k, v] = list(map(lambda x: x.strip(), line.split('=', 1)))
                    if k.endswith('+'):
                        k = k[:-1].strip()
                        fwrite(f, make_export_paths(k, [v]))
                    else:
                        fwrite(f, 'export {} = {}\n'.format(k, v))
                fwrite(f, '\n')

            cargo_target = 'CARGO_TARGET_' + self.cargo_target.upper().replace('-', '_')
            if cc:
                fwrite(f, '# LINKER\n')
                fwrite(f, 'export {}_LINKER = {}\n'.format(cargo_target, linker))
                fwrite(f, 'override {}_RUSTFLAGS += {}\n'.format(
                    cargo_target, ' '.join(linker_options)))
                fwrite(f, 'export {}_RUSTFLAGS\n'.format(cargo_target))
                fwrite(f, '\n')

            cargo_target = self.cargo_target.replace('-', '_')
            if cc:
                fwrite(f, '# AR, CC, CXX, RANLIB, STRIP\n')
                fwrite(f, 'export AR_{} = {}\n'.format(cargo_target, ar))
                fwrite(f, 'export CC_{} = {}\n'.format(cargo_target, cc))
                fwrite(f, 'export CXX_{} = {}\n'.format(cargo_target, cxx))
                fwrite(f, 'export RANLIB_{} = {}\n'.format(cargo_target, ranlib))
                fwrite(f, 'export STRIP_{} = {}\n'.format(cargo_target, strip))
                fwrite(f, '\n')

                fwrite(f, '# ARFLAGS, CFLAGS, CXXFLAGS, RANLIBFLAGS\n')
                fwrite(f, 'override ARFLAGS_{} := $(TARGET_ARFLAGS)\n'.format(cargo_target))
                fwrite(f, 'export ARFLAGS_{}\n'.format(cargo_target))
                fwrite(f, 'override CFLAGS_{} := {} $(TARGET_CFLAGS)\n'.format(cargo_target,
                                                              ' '.join(cc_options)))
                fwrite(f, 'export CFLAGS_{}\n'.format(cargo_target))
                fwrite(f, 'override CXXFLAGS_{} := {} $(TARGET_CXXFLAGS)\n'.format(
                    cargo_target, ' '.join(cc_options)))
                fwrite(f, 'export CXXFLAGS_{}\n'.format(cargo_target))
                fwrite(f, 'override RANLIBFLAGS_{} := $(TARGET_RANLIBFLAGS)\n'.format(cargo_target))
                fwrite(f, 'export RANLIBFLAGS_{}\n'.format(cargo_target))
                fwrite(f, '\n')

            fwrite(f, '# For Rust bingen + libclang\n')
            bindgen_includes = [
                '{}/include'.format(x) for x in self.cmake_prefix_subdirs] + self.cxx_includes
            fwrite(f, 'override BINDGEN_EXTRA_CLANG_ARGS := $(TARGET_BINDGEN_CLANG_ARGS) {} {}\n'.format(
                '-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST',
                ' '.join(map(lambda x: '-I' + x, bindgen_includes))))
            fwrite(f, 'export BINDGEN_EXTRA_CLANG_ARGS\n')
            fwrite(f, '\n')

            fwrite(f, '# Configure the cross compile pkg-config.\n')
            fwrite(f, 'export PKG_CONFIG_ALLOW_CROSS = {}\n'.format(
                   1 if self.host_target != self.cargo_target else 0))
            fwrite(f, make_export_paths('PKG_CONFIG_PATH_' + cargo_target,
                   self.cmake_prefix_subdirs, ['lib/pkgconfig']))
            fwrite(f, '\n')

            fwrite(f, '# Set system paths.\n')
            if self.host_is_windows and self.win32:
                fwrite(f, make_export_paths('PATH', [
                    '$(CARGO_TARGET_OUT_DIR)'] + join_paths(self.cmake_prefix_subdirs, ['bin', 'lib'])))
            elif self.host_target == self.cargo_target:
                fwrite(f, make_export_paths('PATH',
                       ['$(CARGO_TARGET_OUT_DIR)'] + join_paths(self.cmake_prefix_subdirs, ['bin'])))
                fwrite(f, make_export_paths('LD_LIBRARY_PATH',
                       ['$(CARGO_TARGET_OUT_DIR)'] + join_paths(self.cmake_prefix_subdirs, ['lib'])))
            fwrite(f, '\n')

            fwrite(f, '# Export variables for Cargo build.rs and CMake\n')
            fwrite(f, 'export CARGO_WORKSPACE_DIR = {}\n'.format(
                self.workspace_dir))
            fwrite(f, 'export CMKABE_TARGET = {}\n'.format(
                'native' if self.target_is_native else self.target))
            fwrite(f, 'export CMKABE_TARGET_DIR = {}\n'.format(
                self.target_dir))
            fwrite(f, 'export CMKABE_TARGET_CMAKE_DIR = {}\n'.format(
                self.target_cmake_dir))
            fwrite(f, 'export CMKABE_TARGET_PREFIX = {}\n'.format(
                self.cmake_target_prefix))
            fwrite(f, 'export CMKABE_TARGET_CC = {}\n'.format(
                self.target_cc))
            fwrite(f, 'export CMKABE_CARGO_TARGET = {}\n'.format(
                self.cargo_target))
            fwrite(f, 'export CMKABE_ZIG_TARGET = {}\n'.format(
                self.zig_target))
            fwrite(f, 'export CMKABE_DEBUG := $(DEBUG)\n')
            fwrite(f, 'export CMKABE_MINSIZE := $(MINSIZE)\n')
            fwrite(f, 'export CMKABE_DBGINFO := $(DBGINFO)\n')

        with open(os.path.join(self.cmake_target_dir, '{}.toolchain.cmake'.format(self.host_system)), 'wb') as f:
            if cc_exports:
                for line in cc_exports:
                    [k, v] = list(map(lambda x: x.strip(), line.split('=', 1)))
                    if k.endswith('+'):
                        k = k[:-1].strip()
                        fwrite(f, cmake_export_paths(k, [v]))
                    else:
                        fwrite(f, 'set(ENV{{{}}} "{}")\n'.format(k, v))
                fwrite(f, '\n')

            fwrite(f, '# AR, CC, CXX, RANLIB, STRIP, RC\n')
            fwrite(f, 'set(TARGET_AR "{}")\n'.format(ar))
            fwrite(f, 'set(TARGET_CC "{}")\n'.format(cc))
            fwrite(f, 'set(TARGET_CXX "{}")\n'.format(cxx))
            fwrite(f, 'set(TARGET_RANLIB "{}")\n'.format(ranlib))
            fwrite(f, 'set(TARGET_STRIP "{}")\n'.format(strip))
            fwrite(f, 'set(TARGET_RC "{}")\n'.format(rc))
            fwrite(f, '\n')

            fwrite(f, '# Configure the cross compile pkg-config.\n')
            fwrite(f, 'set(ENV{{PKG_CONFIG_ALLOW_CROSS}} "{}")\n'.format(
                   1 if self.host_target != self.cargo_target else 0))
            fwrite(f, cmake_export_paths(
                'PKG_CONFIG_PATH', self.cmake_prefix_subdirs, ['lib/pkgconfig']))
            fwrite(f, '\n')

            fwrite(f, '# Export variables for Cargo build.rs and CMake\n')
            fwrite(f, 'set(ENV{{CARGO_WORKSPACE_DIR}} "{}")\n'.format(
                self.workspace_dir))
            fwrite(f, 'set(ENV{{CMKABE_TARGET}} "{}")\n'.format(
                'native' if self.target_is_native else self.target))
            fwrite(f, 'set(ENV{{CMKABE_TARGET_DIR}} "{}")\n'.format(
                self.target_dir))
            fwrite(f, 'set(ENV{{CMKABE_TARGET_CMAKE_DIR}} "{}")\n'.format(
                self.target_cmake_dir))
            fwrite(f, 'set(ENV{{CMKABE_TARGET_PREFIX}} "{}")\n'.format(
                self.cmake_target_prefix))
            fwrite(f, 'set(ENV{{CMKABE_TARGET_CC}} "{}")\n'.format(
                self.target_cc))
            fwrite(f, 'set(ENV{{CMKABE_CARGO_TARGET}} "{}")\n'.format(
                self.cargo_target))
            fwrite(f, 'set(ENV{{CMKABE_ZIG_TARGET}} "{}")\n'.format(
                self.zig_target))
            fwrite(f, 'if(CMAKE_BUILD_TYPE STREQUAL "Release")\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} OFF)\n')
            fwrite(f, 'elseif(CMAKE_BUILD_TYPE STREQUAL "MinSizeRel")\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} ON)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} OFF)\n')
            fwrite(f, 'elseif(CMAKE_BUILD_TYPE STREQUAL "RelWithDebInfo")\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} ON)\n')
            fwrite(f, 'else()\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} ON)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} ON)\n')
            fwrite(f, 'endif()\n')

        return self
