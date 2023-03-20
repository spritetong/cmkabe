#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os


class ShellCmd:
    EFAIL = 1
    ENOENT = 7
    EINVAL = 8
    EINTERRUPT = 9

    def __init__(self, options, args):
        self.options = options
        self.args = args

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
                    if not os.path.isdir(path):
                        os.makedirs(path)
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
                        # On Windows, a link is like a bad <JUNCTION> which can't be accessed.
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
            pass
        print(path.replace('\\', '/'), end='')
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
            ftp.set_pasv()
        elif scheme == 'sftp':
            try:
                import paramiko
            except ImportError:
                print(
                    'paramiko is not installed. Please execute: pip install paramiko', file=sys.stderr)
                return self.EFAIL
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(hostname, port or 23, username, password)
            sftp = ssh.open_sftp()
        else:
            print('Unsupported protocol: {}'.format(scheme), file=sys.stderr)
            return self.EINVAL

        for item in files:
            pair = item.split('=')
            (local_path, remote_path) = (pair[0], os.path.basename(
                pair[0])) if len(pair) == 1 else (pair[1], pair[0])
            remote_path = '/'.join([remote_dir,
                                    remote_path]).replace('\\', '/')
            while '//' in remote_path:
                remote_path = remote_path.replace('//', '/')

            print('Upload "{}"'.format(local_path))
            print('    to "{}{}" ...'.format(url, remote_path), flush=True)
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

    @classmethod
    def main(cls):
        try:
            from optparse import OptionParser
            parser = OptionParser(
                usage=('Usage: %prog [options] command <arguments>\n\n'))
            parser.get_option('-h').help = 'Show this help message and exit.'
            parser.add_option('-e', '--empty-dirs',
                              action='store_true', default=False, dest='remove_empty_dirs',
                              help='remove all empty directories')
            parser.add_option('-f', '--force',
                              action='store_true', default=False, dest='force',
                              help='ignore errors, never prompt')
            parser.add_option('--list',
                              action='store_true', default=False, dest='list_cmds',
                              help='list all commands')
            parser.add_option('-P', '--no-dereference',
                              action='store_false', default=True, dest='follow_symlinks',
                              help='always follow symbolic links in SOURCE')
            parser.add_option('-p', '--parents',
                              action='store_true', default=True, dest='parents',
                              help='if existing, make parent directories as needed')
            parser.add_option('-r', '-R', '--recursive',
                              action='store_true', default=False, dest='recursive',
                              help='copy/remove directories and their contents recursively')
            parser.add_option('--args-from-stdin', '--stdin',
                              action='store_true', default=False, dest='args_from_stdin',
                              help='read arguments from stdin')
            (options, args) = parser.parse_args()

            if options.list_cmds:
                for name in dir(ShellCmd(options, args[1:])):
                    if name.startswith('run__'):
                        print(name[5:])
                return 0

            try:
                return getattr(ShellCmd(options, args[1:]), 'run__' + args[0].replace('-', '_'))()
            except IndexError:
                print('Missing command', file=sys.stderr)
            except AttributeError:
                print('Unrecognized command "{}"'.format(
                    args[0]), file=sys.stderr)
            return ShellCmd.EINVAL

        except KeyboardInterrupt:
            print('^C')
            return ShellCmd.EINTERRUPT
