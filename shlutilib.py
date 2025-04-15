#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Shell utility library

This file is the part of the `cmkabe` library (https://github.com/spritetong/cmkabe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2024 spritetong@gmail.com.
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

    def run__dll2lib(self):
        if len(self.args) < 1:
            print('Please input the DLL file path', file=sys.stderr)
            return self.EINVAL
        return TargetParser.zig_dll2lib(self.args[0],
                                        out_path=self.args[1] if len(
                                            self.args) >= 2 else None,
                                        force=self.options.force)

    def run__zig_patch(self):
        TargetParser.zig_patch()
        return 0

    def run__zig_clean_cache(self):
        TargetParser.zig_clean_cache()
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
    # Rust ARCH -> Visual Studio ARCH
    VSTOOLS_ARCH_MAP = {
        'aarch64': 'arm64',
        'i586': 'x86',
        'i686': 'x86',
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
                 make_clean='',
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
        self.host_cargo_target = host_target_info['cargo_triple']
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
            self.target_cmake_dir, self.host_system, '.cmake.lock'))
        self.cmake_target_prefix = self.normpath(os.path.abspath(
            cmake_target_prefix or (self.workspace_dir + '/installed')))
        self.cmake_prefix_dir = ''
        self.cmake_prefix_subdirs = []
        self.cargo_target = cargo_target
        self.zig_target = zig_target
        self.target_cc = target_cc
        self.make_clean = make_clean == 'ON'

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
        self.msvc_masm = ''
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
        return self.host_system_ext == 'mingw'

    @property
    def host_is_cygwin(self):
        return self.host_system_ext == 'cygwin'

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
    def target_is_runnable(self):
        if self.target_is_native or self.cargo_target == self.host_cargo_target:
            return True
        if (not self.android and not self.ios and
            (self.host_os == self.os) and
            (self.host_arch == self.arch or (self.host_arch == 'x86_64' and self.arch in ['i586', 'i686'])) and
            (self.vendor in ['pc', 'apple', 'unknown']) and
                (self.env in ['msvc', 'gnu', 'musl', ''])):
            return True
        return False

    @property
    def is_cross_compiling(self):
        return self.cargo_target != self.host_cargo_target

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

    @property
    def cmkabe_target(self):
        """
        The target triple for cmkabe.

        If the target is `native`, returns `native`, otherwise returns
        the target triple.

        :rtype: str
        """
        return 'native' if self.target_is_native else self.target

    def cargo_out_dir(self, make=False, cmake=False):
        if self.cargo_target == self.host_cargo_target:
            dir = self.cargo_target_dir
        else:
            dir = '{}/{}'.format(self.cargo_target_dir, self.cargo_target)
        build_type = 'debug'
        if make:
            build_type = '$(CARGO_BUILD_TYPE)'
        elif cmake:
            build_type = '${CARGO_BUILD_TYPE}'
        return '{}/{}'.format(dir, build_type)

    # Only for Make files.
    def cmake_build_dir(self):
        return '{}/$(CMAKE_BUILD_TYPE)'.format(self.cmake_target_dir)

    def enum_prefix_subdirs_of(self, subdir, quotes=False, make=False, cmake=False):
        if subdir in ['bin', 'lib']:
            if make:
                for dir in [self.cargo_out_dir(make=True), self.cmake_build_dir()]:
                    yield '"{}"'.format(dir) if quotes else dir
            elif cmake:
                for dir in [self.cargo_out_dir(cmake=True), '${CMAKE_BINARY_DIR}']:
                    yield '"{}"'.format(dir) if quotes else dir
        for dir in self.cmake_prefix_subdirs:
            if quotes:
                yield '"{}{}{}"'.format(dir, '/' if subdir else '', subdir)
            else:
                yield '{}{}{}'.format(dir, '/' if subdir else '', subdir)

    # Check if the host operating system is Windows.
    @classmethod
    def normpath(Self, path):
        return os.path.normpath(path).replace('\\', '/')

    @classmethod
    def need_update(Self, source_file, dest_file):
        return not os.path.isfile(dest_file) or (
            os.path.getmtime(dest_file) < os.path.getmtime(source_file))

    @classmethod
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
        cargo_target_vendor = ''
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
        elif target_os == 'linux':
            target_vendor = 'pc'
            cargo_target_vendor = 'unknown'
        else:
            target_vendor = 'unknown'
        if not cargo_target_vendor:
            cargo_target_vendor = target_vendor
        # target_env
        if target_os == 'windows':
            target_env = 'msvc'
        elif target_system in ('linux', 'cygwin', 'mingw'):
            target_env = 'gnu'
        # target_triple
        target_triple = Self.join_triple(
            target_arch, target_vendor, target_os, target_env)
        cargo_target_triple = Self.join_triple(
            target_arch, cargo_target_vendor, target_os, target_env)

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
            'cargo_triple': cargo_target_triple,
        }

    @classmethod
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

    @classmethod
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
        zig = shutil.which('zig' + self.EXE_EXT) if self.zig else None
        if (not self.target_is_native and not self.android and (zig is None) and
                (not self.target_cc or not shutil.which(self.target_cc)) and
                self.is_cross_compiling):
            # Try gcc cross-compiler.
            target_cc = shutil.which(
                self.target + '-gcc' + self.EXE_EXT) or shutil.which(self.target + '-cc' + self.EXE_EXT)
            if target_cc:
                self.target_cc = self.normpath(target_cc)
                # Disable Zig if gcc is found.
                self.zig = False
            elif (self.vendor != self.host_vendor or self.os != self.host_os or
                  self.env != self.host_env) or (self.host_is_linux and self.os == 'linux'):
                # Try Zig cross-compiler.
                if zig is None:
                    zig = shutil.which('zig' + self.EXE_EXT)
                if zig:
                    self.zig = True

        # Zig
        if self.zig and not self.zig_target:
            self.zig_target = zig_target

        # CMake generator
        if not self.cmake_generator and (self.host_is_unix or self.zig or self.target_cc):
            if self.host_is_windows or shutil.which('ninja' + self.EXE_EXT):
                self.cmake_generator = 'Ninja'
            elif self.host_is_unix:
                self.cmake_generator = 'Unix Makefiles'

        if ((self.target_is_native or self.cargo_target != self.host_cargo_target) and
                self.target == self.cargo_target):
            self.cargo_target_dir = self.target_dir
        else:
            self.cargo_target_dir = '{}/{}'.format(
                self.target_dir, self.target)

        self.cmake_prefix_dir = '{}/{}'.format(
            self.cmake_target_prefix, self.target)

        def _any_prefix_subdirs():
            # Add the CMake target as a subdirectory.
            yield self.target
            # If the Cargo target is not equal to the CMake target, add it as a subdirectory.
            if self.target != self.cargo_target:
                yield self.cargo_target
            yield self.join_triple(self.arch, self.vendor, self.os, 'any')
            if self.vendor != '':
                yield self.join_triple('any', self.vendor, self.os, 'any')
            yield self.join_triple('any', '', self.os, 'any')
            yield 'any'
        self.cmake_prefix_subdirs = ['{}/{}'.format(self.cmake_target_prefix, x)
                                     for x in _any_prefix_subdirs()]
        return self

    def _win32_init(self):
        import subprocess
        vswhere = 'vswhere.exe'
        for program_files in ['ProgramW6432', 'ProgramFiles(x86)', 'ProgramFiles']:
            path = r'{}\Microsoft Visual Studio\Installer\vswhere.exe'.format(
                os.environ.get(program_files, ''))
            if os.path.isfile(path):
                vswhere = path
        try:
            result = subprocess.run(
                [vswhere, '-latest', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.*',
                    "-find", r'VC\Tools\MSVC\**\bin\*{}\{}\ml*.exe'.format(
                        self.VSTOOLS_ARCH_MAP.get(
                            self.host_arch, self.host_arch),
                        self.VSTOOLS_ARCH_MAP.get(self.arch, self.arch),
                    )],
                stdin=subprocess.DEVNULL,
                capture_output=True, text=True)
            ml = result.stdout.strip()
            if ml:
                self.msvc_masm = self.normpath(ml)
        except OSError:
            pass

    def _cmake_init(self):
        self.cmake_target_dir = '{}/{}/{}'.format(
            self.target_cmake_dir,
            self.host_system,
            "native" if self.target_is_native else self.target)
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
            self.target_dir, '.zig', self.host_system))
        src = self.script_dir + '/zig-wrapper.zig'
        exe = self.zig_cc_dir + '/zig-wrapper' + self.EXE_EXT
        dir = self.zig_cc_dir

        self.makedirs(dir)
        if self.need_update(src, exe) and not self.make_clean:
            for file in glob.glob(os.path.join(dir, '*')):
                if not os.path.isdir(file):
                    os.unlink(file)
            # Compile wrapper
            subprocess.run(['zig' + self.EXE_EXT, 'cc', '-s', '-Os', '-o', exe, src],
                           env=self.copy_env_for_cc(), check=True)
            os.chmod(exe, 0o755)
            for file in glob.glob(os.path.join(dir, exe + '.*')):
                os.unlink(file)
            for name in ['ar', 'cc', 'c++', 'dlltool', 'lib', 'link', 'ranlib', 'objcopy', 'rc', 'windres']:
                dst = os.path.join(dir, 'zig-' + name + self.EXE_EXT)
                os.symlink(os.path.basename(exe), dst)
            for name in ['dlltool', 'windres']:
                dst = os.path.join(dir, name + self.EXE_EXT)
                os.symlink(os.path.basename(exe), dst)
            for name in ['elf_path_fixer.py']:
                dst = os.path.join(dir, name)
                os.symlink(os.path.relpath(
                    os.path.join(self.script_dir, name), dir).replace('/', os.sep), dst)

        # Override the target CC for Zig.
        self.target_cc = self.normpath(
            self.zig_cc_dir + '/zig-cc' + self.EXE_EXT)

        # Get include paths.
        def cc_cmd_args(cc):
            return [cc, '-target', self.zig_target]
        if not self.make_clean:
            self.c_includes = self._get_cc_includes(
                cc_cmd_args(self.target_cc), 'c')
            self.cxx_includes = self._get_cc_includes(
                cc_cmd_args(self.target_cxx), 'c++')

    @classmethod
    def zig_dll2lib(Self, dll_file, out_path=None, force=False):
        import subprocess
        try:
            import pefile
        except ImportError:
            print('`pefile` is not installed. Try: pip install pefile',
                  file=sys.stderr)
            return Self.EFAIL

        # Load the DLL file
        pe = pefile.PE(dll_file)

        # Mapping of PE machine types to `dlltool` machine types
        machine_types = {
            0x014c: 'i386',         # x86
            0x8664: 'i386:x86-64',  # x64 (AMD64)"
            0x01c4: 'arm',          # ARMv7
            0xaa64: 'arm64',        # ARM64
        }
        machine = machine_types.get(pe.FILE_HEADER.Machine, None)
        if machine is None:
            print('Unsupported machine type {} in {}'.format(
                pe.FILE_HEADER.Machine, dll_file), file=sys.stderr)
            return Self.EFAIL

        # Check if the DLL has an export directory
        if not hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
            print('No export symbols found in {}'.format(
                dll_file), file=sys.stderr)
            return Self.EFAIL

        dll_name = os.path.splitext(os.path.basename(dll_file))[0]
        out_dir = out_path
        out_file = dll_name + '.lib'
        if out_file.endswith('.lib') or out_file.endswith('.a'):
            out_dir = os.path.dirname(out_file) or '.'
            out_file = os.path.basename(out_file)
        def_file = os.path.splitext(out_file)[0] + '.def'
        if os.path.exists(os.path.join(out_dir, out_file)) and not force:
            print('"{}" already exists in "{}"'.format(
                out_file, out_dir), file=sys.stderr)
            return Self.EFAIL

        with open(os.path.join(out_dir, def_file), 'wb') as f:
            f.write('LIBRARY {}\r\n'.format(dll_name).encode())
            f.write(b'EXPORTS\r\n')
            for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
                name = symbol.name.decode() if symbol.name else None
                ordinal = symbol.ordinal if symbol.ordinal else None
                if name is not None:
                    if ordinal is not None:
                        f.write('    {} @{}\r\n'.format(name, ordinal).encode())
                    else:
                        f.write('    {}\r\n'.format(name).encode())

        subprocess.run(
            ['zig' + Self.EXE_EXT,
             'dlltool',
             '-m', machine,
             '-D', dll_file,
             '-d', os.path.join(out_dir, def_file),
             '-l', os.path.join(out_dir, out_file)],
            check=True)
        return 0

    @classmethod
    def zig_patch(Self):
        import shutil
        import glob
        import re

        def patch_file(filename, search, insert=b'', replace=None, count=1):
            with open(filename, 'rb') as file:
                content = file.read()
            slices = []
            changed = False
            while count > 0:
                # Find the index of the search string
                index = content.find(search)
                if index < 0:
                    break
                # Calculate the position to insert the new text
                insert_position = index + len(search)
                if content[insert_position:insert_position + len(insert)] != insert or replace is not None:
                    slices.append(content[:index])
                    if replace is not None:
                        slices.append(replace)
                    else:
                        slices.append(content[index:insert_position])
                    slices.append(insert)
                    changed = True
                else:
                    insert_position += len(insert)
                    slices.append(content[:insert_position])
                content = content[insert_position:]
                count -= 1
            slices.append(content)
            if changed:
                # Open the file for writing and save the modified content
                print('Patching {}'.format(filename))
                with open(filename, 'wb') as file:
                    for slice in slices:
                        file.write(slice)
            return changed

        def patch_visibility(filename):
            dll_import = b'__declspec(dllimport)'
            vis_default = b'__attribute__((visibility("default")))'

            insert = b'\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility push(hidden)\n\n'
            append = b'\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility pop\n'

            file_map = {
                'crtexewin.c': b'#include <mbctype.h>\n#endif\n',
                'wdirent.c': b'#include "dirent.c"\n',
                'ucrtexewin.c': b'#include "crtexewin.c"\n',
                'pseudo-reloc.c': b'# define NO_COPY\n#endif\n',
                'thread.c': b'#include "winpthread_internal.h"\n',
            }

            with open(filename, 'rb') as file:
                content = file.read()

            if dll_import in content and vis_default not in content:
                content = content.replace(
                    dll_import, dll_import + b' ' + vis_default)

            insert_position = 0
            search = file_map.get(os.path.basename(filename))
            if search:
                index = content.find(search)
                if index >= 0:
                    insert_position = index + len(search)
            if insert_position == 0 and (content.find(b'<windows.h>') >= 0 or
                                         content.find(b'<stdlib.h>') >= 0 or
                                         content.find(b'<wchar.h>') >= 0):
                index = content.rfind(b'#include <')
                if index >= 0:
                    insert_position = index + content[index:].find(b'\n') + 1

            if content[insert_position:insert_position + len(insert)] == insert:
                return False

            print('Patching {}'.format(filename))
            with open(filename, 'wb') as file:
                file.write(content[:insert_position])
                file.write(insert)
                file.write(content[insert_position:])
                file.write(append)
            return True

        def patch_visibility_mingw_S(filename):
            pattern = re.compile(rb'\b__MINGW_USYMBOL\((\w+)\)')
            symbols = set()

            with open(filename, 'rb') as file:
                content = file.read()
            for line in content.splitlines():
                matches = pattern.findall(line)
                for match in matches:
                    symbols.add(match.strip())
            symbols = list(sorted(symbols)) + \
                [b'_' + x for x in sorted(symbols)]
            if not symbols:
                return False
            code = b'\n/* XPATCH: do not export symbols. */\n.section .drectve,"yni"\n'
            code += b'\n'.join(map(lambda x: '.ascii " -exclude-symbols:{} "'.format(
                x.decode()).encode(), symbols))
            code += b'\n'

            if content.endswith(code):
                return False

            print('Patching {}'.format(filename))
            with open(filename, 'wb') as file:
                file.write(content)
                file.write(code)
            return True

        zig_path = shutil.which('zig' + Self.EXE_EXT)
        if not zig_path:
            return
        zig_root = os.path.realpath(os.path.dirname(zig_path))
        any_linux_any = os.path.join(
            zig_root, 'lib', 'libc', 'include', 'any-linux-any')
        lib_src_patched = False

        # 1. fix `lib/compiler_rt/stack_probe.zig` with Zig <= 0.13.
        if patch_file(os.path.join(zig_root, 'lib', 'compiler_rt', 'stack_probe.zig'),
                      b'.linkage = strong_linkage', b'', replace=b'.linkage = linkage', count=sys.maxsize):
            lib_src_patched = True

        # 2. Set symbol visibility to `hidden` in `libunwind`.
        libunwind_src = os.path.join(zig_root, 'lib', 'libunwind', 'src')
        for (file, tag) in [('assembly.h', 'UNWIND_ASSEMBLY_H'),
                            ('config.h', 'LIBUNWIND_CONFIG_H')]:
            if patch_file(
                os.path.join(libunwind_src, file),
                b'#define ' + tag.encode(),
                    b'\n\n/* XPATCH: do not export symbols. */\n#define _LIBUNWIND_HIDE_SYMBOLS'):
                lib_src_patched = True
        for (search, insert) in [
            (b'#define _LIBUNWIND_HIDE_SYMBOLS\n',
             b'''#if defined(__MINGW32__) && defined(_LIBUNWIND_HIDE_SYMBOLS)
#define XPATCH_HIDDEN_SYMBOL(name)                                             \\
  .section .drectve,"yni" SEPARATOR                                            \\
  .ascii " -exclude-symbols:", #name, " " SEPARATOR                            \\
  .text
#else
#define XPATCH_HIDDEN_SYMBOL(name)
#endif
'''),
            (b'''#if defined(__MINGW32__)
#define WEAK_ALIAS(name, aliasname)                                            \\
''',
             b'''  XPATCH_HIDDEN_SYMBOL(aliasname) SEPARATOR                                    \\
'''),
            (b'''#else
#define DEFINE_LIBUNWIND_FUNCTION(name)                                        \\
''',
             b'''  XPATCH_HIDDEN_SYMBOL(name) SEPARATOR                                         \\
'''),
        ]:
            if patch_file(os.path.join(libunwind_src, 'assembly.h'), search, insert):
                lib_src_patched = True

        # 3. Set symbol visibility to `hidden` in `mingw32`.
        for libc in ['mingw']:
            zig_libc = os.path.join(zig_root, 'lib', 'libc', libc)
            mingw_libsrc = '/mingw/libsrc/'
            for (ext, patch_func) in [('c', patch_visibility), ('S', patch_visibility_mingw_S)]:
                for file_path in glob.glob('{}/**/*.{}'.format(zig_libc, ext), recursive=True):
                    if mingw_libsrc not in file_path.replace('\\', '/'):
                        if patch_func(file_path):
                            lib_src_patched = True

        # 4. <sys/sysctl.h> is required by ffmpeg 6.0
        sys_ctl_h = os.path.join(any_linux_any, 'sys', 'sysctl.h')
        sys_ctl_h_src = os.path.join(any_linux_any, 'linux', 'sysctl.h')
        if not os.path.exists(sys_ctl_h) and os.path.isfile(sys_ctl_h_src):
            Self.makedirs(os.path.dirname(sys_ctl_h))
            os.symlink(os.path.relpath(
                sys_ctl_h_src, os.path.dirname(sys_ctl_h)), sys_ctl_h)

        if lib_src_patched:
            Self.zig_clean_cache()

    @classmethod
    def zig_clean_cache(Self):
        import shutil
        import subprocess
        import json
        zig_env = json.loads(subprocess.run(
            ['zig' + Self.EXE_EXT, 'env'],
            capture_output=True, check=True).stdout)
        shutil.rmtree(zig_env['global_cache_dir'], ignore_errors=True)

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
        self.c_includes = self._get_cc_includes(
            cc_cmd_args(self.target_cc), 'c')
        self.cxx_includes = self._get_cc_includes(
            cc_cmd_args(self.target_cxx), 'c++')

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
        if self.host_is_windows and self.win32:
            self._win32_init()
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

        with open(os.path.join(self.target_cmake_dir, self.host_system,
                               '.host.mk'), 'wb') as f:
            fwrite(f, 'override HOST_SYSTEM = {}\n'.format(self.host_system))
            fwrite(f, 'override HOST_TARGET = {}\n'.format(self.host_target))
            fwrite(f, 'override HOST_CARGO_TARGET = {}\n'.format(
                self.host_cargo_target))
            fwrite(f, 'override HOST_ARCH = {}\n'.format(self.host_arch))
            fwrite(f, 'override HOST_VENDOR = {}\n'.format(self.host_vendor))
            fwrite(f, 'override HOST_OS = {}\n'.format(self.host_os))
            fwrite(f, 'override HOST_ENV = {}\n'.format(self.host_env))
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            fwrite(f, 'override HOST_SEP := $(strip {})\n'.format(os.sep))
            fwrite(f, 'override HOST_PATHSEP = {}\n'.format(os.pathsep))
            fwrite(f, 'override HOST_EXE_EXT = {}\n'.format(self.EXE_EXT))
            fwrite(f, '\n')
            fwrite(
                f, '# Unexport environment variables that may affect the CC compiler.\n')
            for key in self.GCC_ENV_KEYS:
                fwrite(f, 'unexport {}\n'.format(key))

        with open(os.path.join(self.target_cmake_dir, self.host_system,
                               '.host.cmake'), 'wb') as f:
            fwrite(f, 'set(HOST_SYSTEM "{}")\n'.format(self.host_system))
            fwrite(f, 'set(HOST_TARGET "{}")\n'.format(self.host_target))
            fwrite(f, 'set(HOST_CARGO_TARGET "{}")\n'.format(
                self.host_cargo_target))
            fwrite(f, 'set(HOST_ARCH "{}")\n'.format(self.host_arch))
            fwrite(f, 'set(HOST_VENDOR "{}")\n'.format(self.host_vendor))
            fwrite(f, 'set(HOST_OS "{}")\n'.format(self.host_os))
            fwrite(f, 'set(HOST_ENV "{}")\n'.format(self.host_env))
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            fwrite(f, 'set(HOST_SEP "{}")\n'.format(
                os.sep.replace('\\', '\\\\')))
            fwrite(f, 'set(HOST_PATHSEP "{}")\n'.format(os.pathsep))
            fwrite(f, 'set(HOST_EXE_EXT "{}")\n'.format(self.EXE_EXT))

        with open(os.path.join(self.cmake_target_dir, '.settings.mk'), 'wb') as f:
            fwrite(f, '# Home directory\n')
            fwrite(f, 'override CMKABE_HOME = {}\n'.format(self.script_dir))
            fwrite(f, '\n')

            fwrite(f, '# Constants for the target platform\n')
            fwrite(f, 'override TARGET_SEP := $(strip {})\n'.format(
                '\\' if self.win32 else '/'))
            fwrite(f, 'override TARGET_PATHSEP = {}\n'.format(
                ';' if self.win32 else ':'))
            fwrite(f, 'override TARGET_EXE_EXT = {}\n'.format(
                '.exe' if self.win32 else ''))
            fwrite(f, '\n')

            fwrite(f, '# Build configuration\n')
            fwrite(f, 'ifeq ($(CMAKE_BUILD_TYPE),)\n')
            fwrite(f, '    $(error CMAKE_BUILD_TYPE is not set)\n')
            fwrite(f, 'endif\n')
            fwrite(f, 'ifeq ($(DEBUG),)\n')
            fwrite(f, '    $(error DEBUG is not set)\n')
            fwrite(f, 'endif\n')
            fwrite(
                f, 'override CARGO_BUILD_TYPE := $(call bsel,$(DEBUG),debug,release)\n')
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
            fwrite(f, 'override CMAKE_PREFIX_DIR = {}\n'.format(
                self.cmake_prefix_dir))
            fwrite(f, 'override CMAKE_PREFIX_SUBDIRS = {}\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('', make=True))))
            fwrite(f, 'override CMAKE_PREFIX_BINS := {}\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('bin', make=True))))
            fwrite(f, 'override CMAKE_PREFIX_LIBS := {}\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('lib', make=True))))
            fwrite(f, 'override CMAKE_PREFIX_INCLUDES = {}\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('include', make=True))))
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
            fwrite(f, 'override CARGO_OUT_DIR := {}\n'.format(
                self.cargo_out_dir(make=True)))
            fwrite(f, '\n')

            fwrite(f, '# CMake\n')
            fwrite(f, 'override CMAKE_GENERATOR = {}\n'.format(
                self.cmake_generator))
            fwrite(f, 'override CMAKE_TARGET_DIR = {}\n'.format(
                self.cmake_target_dir))
            fwrite(f, 'override CMAKE_BUILD_DIR = {}\n'.format(
                self.cmake_build_dir()))
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, 'override MSVC_ARCH = {}\n'.format(self.msvc_arch))
            fwrite(f, 'override MSVC_MASM = {}\n'.format(self.msvc_masm))
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            fwrite(f, 'override ANDROID_TARGET = {}{}\n'.format(
                self.android_target, '$(ANDROID_SDK_VERSION)' if self.android_target else ''))
            fwrite(f, 'override ANDROID_ARCH = {}\n'.format(
                self.android_arch))
            fwrite(f, 'override ANDROID_ABI = {}\n'.format(
                self.android_abi))
            if self.android_ndk_root:
                fwrite(f, 'override ANDROID_NDK_ROOT = {}\n'.format(
                    self.android_ndk_root))
            if self.android_ndk_bin:
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
            fwrite(f, 'override TARGET_IS_RUNNABLE = {}\n'.format(
                onoff(self.target_is_runnable)))
            fwrite(f, 'override TARGET_IS_WIN32 = {}\n'.format(onoff(self.win32)))
            fwrite(f, 'override TARGET_IS_MSVC = {}\n'.format(onoff(self.msvc)))
            fwrite(f, 'override TARGET_IS_ANDROID = {}\n'.format(
                onoff(self.android)))
            fwrite(f, 'override TARGET_IS_UNIX = {}\n'.format(onoff(self.unix)))
            fwrite(f, 'override TARGET_IS_APPLE = {}\n'.format(onoff(self.apple)))
            fwrite(f, 'override TARGET_IS_IOS = {}\n'.format(onoff(self.ios)))

        with open(os.path.join(self.cmake_target_dir, '.settings.cmake'), 'wb') as f:
            fwrite(f, '# Home directory\n')
            fwrite(f, 'set(CMKABE_HOME "{}")\n'.format(self.script_dir))
            fwrite(f, '\n')

            fwrite(f, '# Constants for the target platform\n')
            fwrite(f, 'set(TARGET_SEP "{}")\n'.format(
                '\\\\' if self.win32 else '/'))
            fwrite(f, 'set(TARGET_PATHSEP "{}")\n'.format(
                ';' if self.win32 else ':'))
            fwrite(f, 'set(TARGET_EXE_EXT "{}")\n'.format(
                '.exe' if self.win32 else ''))
            fwrite(f, '\n')

            fwrite(f, '# Build configuration\n')
            fwrite(f, 'if(NOT CMAKE_BUILD_TYPE)\n')
            fwrite(f, '    set(CMAKE_BUILD_TYPE "Release")\n')
            fwrite(f, 'endif()\n')
            fwrite(
                f, 'string(TOLOWER "${CMAKE_BUILD_TYPE}" CMAKE_BUILD_TYPE_LOWER)\n')
            fwrite(f, 'if(CMAKE_BUILD_TYPE_LOWER STREQUAL "debug")\n')
            fwrite(f, '    set(CARGO_BUILD_TYPE "debug")\n')
            fwrite(f, 'else()\n')
            fwrite(f, '    set(CARGO_BUILD_TYPE "release")\n')
            fwrite(f, 'endif()\n')
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
            fwrite(f, 'set(TARGET_PREFIX_DIR "{}")\n'.format(
                self.cmake_prefix_dir))
            fwrite(f, 'set(TARGET_PREFIX_SUBDIRS {})\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('', quotes=True, cmake=True))))
            fwrite(f, 'set(TARGET_PREFIX_BINS {})\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('bin', quotes=True, cmake=True))))
            fwrite(f, 'set(TARGET_PREFIX_LIBS {})\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('lib', quotes=True, cmake=True))))
            fwrite(f, 'set(TARGET_PREFIX_INCLUDES {})\n'.format(
                ' '.join(self.enum_prefix_subdirs_of('include', quotes=True, cmake=True))))
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
            fwrite(f, 'set(CARGO_OUT_DIR "{}")\n'.format(
                self.cargo_out_dir(cmake=True)))
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, 'set(MSVC_ARCH "{}")\n'.format(self.msvc_arch))
            fwrite(f, 'set(MSVC_MASM "{}")\n'.format(self.msvc_masm))
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            fwrite(f, 'set(ANDROID_TARGET "{}{}")\n'.format(
                self.android_target, '${ANDROID_SDK_VERSION}' if self.android_target else ''))
            fwrite(f, 'set(ANDROID_ARCH "{}")\n'.format(
                self.android_arch))
            fwrite(f, 'set(ANDROID_ABI "{}")\n'.format(
                self.android_abi))
            if self.android_ndk_root:
                fwrite(f, 'set(ANDROID_NDK_ROOT "{}")\n'.format(
                    self.android_ndk_root))
            if self.android_ndk_bin:
                fwrite(f, 'set(ANDROID_NDK_BIN "{}")\n'.format(
                    self.android_ndk_bin))
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
            fwrite(f, 'set(TARGET_IS_RUNNABLE {})\n'.format(
                onoff(self.target_is_runnable)))
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
            # Fix compilation issues of Rust native crates.
            cc_options.append("--disable-dllexport")
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

        with open(os.path.join(self.cmake_target_dir, '.environ.mk'), 'wb') as f:
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
            fwrite(f, '# RUSTFLAGS\n')
            fwrite(f, 'override {}_RUSTFLAGS := {} $(TARGET_RUSTFLAGS)\n'.format(
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
            fwrite(f, 'override ARFLAGS_{} := $(TARGET_ARFLAGS)\n'.format(
                cargo_target))
            fwrite(f, 'export ARFLAGS_{}\n'.format(cargo_target))
            fwrite(f, 'override CFLAGS_{} := {} $(TARGET_CFLAGS)\n'.format(
                cargo_target, ' '.join(cc_options)))
            fwrite(f, 'export CFLAGS_{}\n'.format(cargo_target))
            fwrite(f, 'override CXXFLAGS_{} := {} $(TARGET_CXXFLAGS)\n'.format(
                cargo_target, ' '.join(cc_options)))
            fwrite(f, 'export CXXFLAGS_{}\n'.format(cargo_target))
            fwrite(f, 'override RANLIBFLAGS_{} := $(TARGET_RANLIBFLAGS)\n'.format(
                cargo_target))
            fwrite(f, 'export RANLIBFLAGS_{}\n'.format(cargo_target))
            fwrite(f, '\n')

            fwrite(f, '# For Rust bingen + libclang\n')
            bindgen_includes = list(
                self.enum_prefix_subdirs_of('include', make=True)) + self.cxx_includes
            fwrite(f, 'override BINDGEN_EXTRA_CLANG_ARGS := $(TARGET_BINDGEN_CLANG_ARGS) {} {}\n'.format(
                '-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST' +
                ('' if self.apple else ' -D_LIBCPP_HAS_NO_VENDOR_AVAILABILITY_ANNOTATIONS=1'),
                ' '.join(map(lambda x: '-I"{}"'.format(x), bindgen_includes))))
            fwrite(f, 'export BINDGEN_EXTRA_CLANG_ARGS\n')
            fwrite(f, '\n')

            fwrite(f, '# For Rust cmake\n')
            fwrite(f, 'export CMAKE_TOOLCHAIN_FILE_{} = {}/.toolchain.cmake\n'.format(
                cargo_target, self.cmake_target_dir))
            if self.cmake_generator:
                fwrite(f, 'export CMAKE_GENERATOR_{} = {}\n'.format(
                    cargo_target, self.cmake_generator))
            else:
                fwrite(f, 'unexport CMAKE_GENERATOR_{}\n'.format(cargo_target))
            fwrite(f, '\n')

            fwrite(f, '# Configure the cross compile pkg-config.\n')
            fwrite(f, 'export PKG_CONFIG_ALLOW_CROSS = {}\n'.format(
                   1 if self.is_cross_compiling else 0))
            fwrite(f, make_export_paths('PKG_CONFIG_PATH_' + cargo_target,
                   list(self.enum_prefix_subdirs_of('lib/pkgconfig', make=True)), []))
            fwrite(f, '\n')

            fwrite(f, '# Set system paths.\n')
            if self.target_is_runnable:
                fwrite(f, make_export_paths('PATH',
                                            [self.zig_cc_dir] +
                                            list(self.enum_prefix_subdirs_of('bin', make=True)), []))
                if not self.host_is_windows:
                    fwrite(f, make_export_paths('LD_LIBRARY_PATH',
                                                list(self.enum_prefix_subdirs_of('lib', make=True)), []))
            fwrite(f, '\n')

            _make_build_vars = [
                'TARGET',
                'TARGET_DIR',
                'TARGET_CMAKE_DIR',
                'CMAKE_TARGET_PREFIX',
                'TARGET_CC',
                'CARGO_TARGET',
                'ZIG_TARGET',
                'DEBUG',
                'MINSIZE',
                'DBGINFO',
            ]
            fwrite(f, '# Export variables for Cargo build.rs and CMake\n')
            fwrite(f, 'export CARGO_WORKSPACE_DIR = {}\n'.format(
                self.workspace_dir))
            fwrite(f, 'export CMKABE_HOST_TARGET = {}\n'.format(
                self.host_target))
            fwrite(f, 'export CMKABE_TARGET = {}\n'.format(
                self.cmkabe_target))
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
            fwrite(f, 'export CMKABE_CMAKE_BUILD_TYPE := $(CMAKE_BUILD_TYPE)\n')
            fwrite(f, 'export CMKABE_CMAKE_BUILD_DIR := $(CMAKE_BUILD_DIR)\n')
            fwrite(f, 'export CMKABE_CARGO_OUT_DIR := {}\n'.format(
                self.cargo_out_dir(make=True)))
            fwrite(f, 'export CMKABE_MAKE_BUILD_VARS = {}\n'.format(
                ';'.join(_make_build_vars)))
            fwrite(f, 'export CMKABE_LINK_DIRS := {}\n'.format(
                os.path.pathsep.join(self.enum_prefix_subdirs_of('lib', make=True))))
            fwrite(f, 'export CMKABE_INCLUDE_DIRS = {}\n'.format(
                os.path.pathsep.join(self.enum_prefix_subdirs_of('include', make=True))))

        with open(os.path.join(self.cmake_target_dir, '.environ.cmake'), 'wb') as f:
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
                   1 if self.is_cross_compiling else 0))
            fwrite(f, cmake_export_paths('PKG_CONFIG_PATH',
                                         self.enum_prefix_subdirs_of('lib/pkgconfig', cmake=True), []))
            fwrite(f, '\n')

            fwrite(f, '# Export variables for Cargo build.rs and CMake\n')
            fwrite(f, 'set(ENV{{CARGO_WORKSPACE_DIR}} "{}")\n'.format(
                self.workspace_dir))
            fwrite(f, 'set(ENV{{CMKABE_HOST_TARGET}} "{}")\n'.format(
                self.host_target))
            fwrite(f, 'set(ENV{{CMKABE_TARGET}} "{}")\n'.format(
                self.cmkabe_target))
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
            fwrite(f, 'if(CMAKE_BUILD_TYPE_LOWER STREQUAL "debug")\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} ON)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} ON)\n')
            fwrite(f, 'elseif(CMAKE_BUILD_TYPE_LOWER STREQUAL "minsizerel")\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} ON)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} OFF)\n')
            fwrite(f, 'elseif(CMAKE_BUILD_TYPE_LOWER STREQUAL "relwithdebinfo")\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} ON)\n')
            fwrite(f, 'else()\n')
            fwrite(f, '    set(ENV{CMKABE_DEBUG} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_MINSIZE} OFF)\n')
            fwrite(f, '    set(ENV{CMKABE_DBGINFO} OFF)\n')
            fwrite(f, 'endif()\n')
            fwrite(
                f, 'set(ENV{{CMKABE_CMAKE_BUILD_TYPE}} "${CMAKE_BUILD_TYPE}")\n')
            fwrite(
                f, 'set(ENV{{CMKABE_CMAKE_BUILD_DIR}} "${CMAKE_BINARY_DIR}")\n')
            fwrite(f, 'set(ENV{{CMKABE_CARGO_OUT_DIR}} "{}")\n'.format(
                self.cargo_out_dir(cmake=True)))
            fwrite(f, 'set(ENV{{CMKABE_MAKE_BUILD_VARS}} "{}")\n'.format(
                ';'.join(_make_build_vars)))
            fwrite(f, 'set(ENV{{CMKABE_LINK_DIRS}} "{}")\n'.format(
                os.path.pathsep.join(self.enum_prefix_subdirs_of('lib', cmake=True))))
            fwrite(f, 'set(ENV{{CMKABE_INCLUDE_DIRS}} "{}")\n'.format(
                os.path.pathsep.join(self.enum_prefix_subdirs_of('include', cmake=True))))

        with open(os.path.join(self.cmake_target_dir, '.toolchain.cmake'), 'wb') as f:
            fwrite(f, 'cmake_minimum_required(VERSION 3.16)\n')
            fwrite(f, '\n')
            fwrite(f, 'include("{}/.settings.cmake")\n'.format(
                self.cmake_target_dir))
            fwrite(f, 'set(TARGET "{}")\n'.format(self.cmkabe_target))
            fwrite(f, 'set(ZIG_CC_DISABLE_DLLEXPORT ON)\n')
            fwrite(f, '\n')
            fwrite(f, 'set(TARGET "${TARGET}" CACHE STRING "" FORCE)\n')
            fwrite(
                f, 'set(TARGET_DIR "${TARGET_DIR}" CACHE STRING "" FORCE)\n')
            fwrite(
                f, 'set(TARGET_CMAKE_DIR "${TARGET_CMAKE_DIR}" CACHE STRING "" FORCE)\n')
            fwrite(f, '\n')
            fwrite(f, 'include("${CMKABE_HOME}/toolchain.cmake")\n')
            fwrite(f, '_cmkabe_apply_extra_flags()\n')

        return self
