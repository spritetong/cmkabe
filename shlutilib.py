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
            pass
        print(path.replace('\\', '/'), end='')
        return 0

    def run__win2wsl_path(self):
        path = ShellCmd.win2wsl_path(
            self.args[0] if self.args else os.getcwd())
        print(path, end='')
        return 0

    def run__wsl2win_path(self):
        path = ShellCmd.wsl2win_path(
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

    @staticmethod
    def win2wsl_path(path):
        if os.path.isabs(path):
            path = os.path.abspath(path)
        path = path.replace('\\', '/')
        drive_path = path.split(':', 1)
        if len(drive_path) > 1 and len(drive_path[0]) == 1 and drive_path[0].isalpha():
            path = '/mnt/{}{}'.format(drive_path[0].lower(),
                                      drive_path[1]).rstrip('/')
        return path

    @staticmethod
    def wsl2win_path(path):
        if os.path.isabs(path):
            path = os.path.abspath(path)
        path = path.replace('\\', '/')
        if len(path) >= 6 and path.startswith('/mnt/') and path[5].isalpha():
            if len(path) == 6:
                path = path[5].upper() + ':/'
            elif path[6] == '/':
                path = '{}:{}'.format(path[5].upper(), path[6:])
        return path

    @staticmethod
    def main(args=None):
        try:
            from optparse import OptionParser
            parser = OptionParser(
                usage=('Usage: %prog [options] command <arguments>\n\n'))
            parser.get_option('-h').help = 'Show this help message and exit.'
            parser.add_option('-D', '--symlinkd',
                              action='store_true', default=False, dest='symlinkd',
                              help='creates a directory symbolic link')
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
            (options, args) = parser.parse_args(args)

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


################################################################################

class RmakeUserBase:
    """
    Initializes a new instance of the class.

    Parameters:
        rmake (RsyncMake): The rmake object to be assigned.

    Returns:
        None
    """

    def __init__(self, rmake):
        self.rmake = rmake

    """
    Add some arguemnents to the argument parser.

    Parameters:
        parser (argparse.ArgumentParser): The argument parser object.
        command_type (Callable): The type of command.

    Returns:
        None
    """

    def add_arguments(self, parser, command_type):
        pass

    """
    Synchronizes the source files from the source directory to the destination directory.

    Parameters:
        self (object): The instance of the class.
    
    Returns:
        None
    """

    def sync_forward(self):
        import subprocess
        rmake = self.rmake

        if not rmake.is_sources_synced:
            rmake.git_try_clone()

            rmake.is_sources_synced = True
            rsync_args = ['rsync']
            rsync_args.extend(rmake.rsync_args)
            rsync_args.append((rmake.src_dir + '/').replace('//', '/'))
            rsync_args.append((rmake.dst_dir + '/').replace('//', '/'))
            subprocess.check_call(rsync_args)

    """
    Syncs the generated files from the remote destination directory to
    the local source directory.

    Parameters:
        None

    Returns:
        None
    """
    # Synchronize generated files from <dst_dir> into <src_dir>.

    def sync_backward(self):
        pass

    """
    Execute a user command.

    Args:
        command (str): The command to execute.

    Returns:
        int: 0 if the command was executed successfully, -1 to ignore the command.
    """

    def exec_command(self, command):
        return -1


class RsyncMakeError(Exception):
    """
    Initializes an error intance.

    Args:
        message (str): The error message.
        code (int, optional): The error code. Defaults to 1.
    """

    def __init__(self, message, code=1):
        super().__init__(message)
        self.code = code


class RsyncMake:
    GIT_HOME_DIR = '~/.rmake/githome'
    RMAKE_USER = '.rmake-user.py'
    RMAKE_USER_CLASS = 'RmakeUser'
    RMAKE_INCLUDES = '.rmake-includes'
    RMAKE_EXCLUDES = '.rmake-excludes'
    RSYNC_ARGS = ['-av', '--delete', '--mkpath', '--exclude=.git']
    MAKE_TARGETS = ['cargo', 'cargo-*', 'clean', 'clean-*', 'cmake', 'cmake-*', 'update-libs']

    def __init__(self):
        self.args = None
        self.user = RmakeUserBase(self)
        self.git_home_dir = os.path.expanduser(self.GIT_HOME_DIR)
        self.src_dir = ''
        self.dst_dir = ''
        self.rsync_args = list(self.RSYNC_ARGS)
        self.commands = []
        self.make_targets = list(self.MAKE_TARGETS)
        self.make_vars = []
        self.exec_cmd_args = []
        self.is_sources_synced = False
        self.workspace_dir = RsyncMake.get_workspace_dir(__file__)

    def run(self, args):
        import subprocess
        import re

        self.args = args

        # <src_dir>
        self.src_dir = os.path.realpath(args.src_dir or self.workspace_dir)

        # <dst_dir>
        if args.dst_dir:
            self.dst_dir = args.dst_dir
        else:
            git_home_base = os.path.basename(self.git_home_dir)
            idx = self.src_dir.find('/' + git_home_base + '/')
            if idx < 0:
                self.error('\n'.join([
                    '"{}" does not have an ancestor directory named "{}"'.format(
                        self.src_dir, git_home_base),
                    'Please move the source repository into a directory named "{}"'.format(
                        git_home_base),
                    'or specify the destination directory with the option: --dst-dir <dst_dir>',
                ]))
            self.dst_dir = self.git_home_dir + \
                self.src_dir[idx + len(git_home_base) + 1:]
        self.dst_dir = os.path.realpath(self.dst_dir)

        # <rsync_args>
        self.rsync_args.extend(args.rsync_options or [])
        if not list(filter(lambda x: x.startswith('--include-from='), self.rsync_args)):
            include_from = os.path.join(self.src_dir, self.RMAKE_INCLUDES)
            if os.path.isfile(include_from):
                self.rsync_args.append('--include-from=' + include_from)
        if not list(filter(lambda x: x.startswith('--exclude-from='), self.rsync_args)):
            exclude_from = os.path.join(self.src_dir, self.RMAKE_EXCLUDES)
            if not os.path.isfile(exclude_from):
                exclude_from = os.path.join(self.src_dir, '.gitignore')
                if not os.path.isfile(exclude_from):
                    exclude_from = ''
            if exclude_from:
                self.rsync_args.append('--exclude-from=' + exclude_from)

        # <commands>
        self.commands.extend(x for x in args.commands if '=' not in x)
        if not self.commands:
            self.commands.append('build')
        self.make_vars.extend(x for x in args.commands if '=' in x)

        if not os.path.isdir(self.src_dir):
            self.error('"{}" is not a directory.'.format(self.src_dir))

        if self.src_dir.startswith(self.dst_dir) or self.dst_dir.startswith(self.src_dir):
            self.error('The source directory and the destination directory '
                       'can\'t be nested within each other.')

        print("rsync: [ {} ] -- [ {} ]".format(
            self.src_dir, self.dst_dir), flush=True)

        for command in self.commands:
            if command in ('clone', 'pull'):
                self.git_checkout(force=True)
            elif command == 'checkout':
                self.git_checkout(force=self.args.force)
            elif command == 'remove-git':
                subprocess.check_call(
                    'cd ~ && rm -rf "{}"'.format(self.dst_dir), shell=True)
            elif command == 'rsync':
                self.user.sync_forward()
            elif command == 'rsync-back':
                self.user.sync_backward()
            elif command == 'exec':
                os.chdir(self.dst_dir)
                subprocess.check_call(self.exec_cmd_args)
            elif self.user.exec_command(command) != -1:
                pass
            elif re.match('^(?:build|{})$'.format('|'.join(self.make_targets).replace('*', '.*')), command):
                self.user.sync_forward()
                # Run make
                self.run_make(command)
                # Sync generated files after build
                if 'clean' not in command:
                    self.user.sync_backward()
            else:
                self.error('Unknown command "{}"'.format(command))
        return 0

    """
    Show the error message and exit with the error code.

    Parameters:
        message (str): The error message.
        code (int, optional): The error code. Defaults to 1.
    """

    def error(self, message, code=1):
        raise RsyncMakeError(message, code)

    """
    Load a user script from the given file path.

    Parameters:
        script_path (str): The path to the user script file.

    Returns:
        None
    """

    def load_user_script(self, script_path):
        with open(script_path, 'r') as fp:
            code = fp.read()
        exec(code, globals(), globals())
        user_cls = globals().get(self.RMAKE_USER_CLASS)
        if not isinstance(user_cls, type) or not issubclass(user_cls, RmakeUserBase):
            self.error('Class {} is not defined in "{}".'.format(
                self.RMAKE_USER_CLASS, script_path))
        self.user = user_cls(self)

    """
    Try to clone a Git repository into a specified destination directory,
    then enter the destination directory on success.
    """

    def git_try_clone(self):
        import subprocess

        if not os.path.isdir(self.dst_dir):
            os.chdir(self.src_dir)
            # Get the current repository URL
            url = subprocess.check_output(
                'git config --get "remote.{}.url"'.format(
                    self.args.git_origin),
                text=True,
                shell=True,
            ).strip()
            # Get the current branch name
            branch = subprocess.check_output(
                'git rev-parse --abbrev-ref HEAD',
                text=True,
                shell=True,
            ).strip()

            branch_opt = ''
            # Check if the remote branch exists
            if subprocess.call(
                'git ls-remote --exit-code --heads "{}" "{}"'.format(
                    self.args.git_origin, branch),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=True,
            ) == 0:
                branch_opt = '-b "{}"'.format(branch)

            subprocess.check_call(' && '.join([
                'mkdir -p "{}"'.format(os.path.dirname(self.dst_dir)),
                'git clone {} "{}" "{}"'.format(branch_opt, url, self.dst_dir),
                'cd "{}"'.format(self.dst_dir),
                'git submodule update --init --recursive',
            ]), shell=True)

        # Enter the destination directory
        os.chdir(self.dst_dir)

    """
    Checks out a Git branch and updates the working directory to match the branch.

    Parameters:
        force (bool, optional): If True, forcefully clean unversioned files and
        revert dirty files. Defaults to False.

    Returns:
        None
    """

    def git_checkout(self, force=False):
        import subprocess

        self.git_try_clone()
        try:
            os.chdir(self.src_dir)
            # Get the current branch name
            branch = subprocess.check_output(
                'git rev-parse --abbrev-ref HEAD',
                text=True,
                shell=True,
            ).strip()
        finally:
            os.chdir(self.dst_dir)

        # Clean unversioned files and revert dirty files.
        if force:
            subprocess.call('git clean -f', shell=True)
            subprocess.call('git checkout -f', shell=True)
            subprocess.call(
                'git submodule foreach --recursive git clean -f', shell=True)
            subprocess.call(
                'git submodule update --init --recursive -f', shell=True)

        current_branch = subprocess.check_output(
            'git rev-parse --abbrev-ref HEAD',
            text=True,
            shell=True,
        ).strip()
        if current_branch != branch or force:
            subprocess.check_call('git remote update', shell=True)
            if subprocess.call(r'git branch | grep -e "^\\*\\?\\s*{}\$"'.format(branch),
                               stdout=subprocess.DEVNULL, shell=True) == 0:
                subprocess.check_call('git checkout {} "{}"'.format(
                    '-f' if force else '', branch),
                    shell=True,
                )
            elif subprocess.call('git ls-remote --exit-code --heads "{}" "{}"'.format(
                    self.args.git_origin, branch),
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=True) == 0:
                # The remote branch exists
                subprocess.check_call('git checkout {} -b "{}" "{}/{}"'.format(
                    '-f' if force else '', branch, self.args.git_origin, branch), shell=True)

        subprocess.check_call('git pull', shell=True)
        subprocess.check_call(
            'git submodule update --init --recursive', shell=True)

    """
    Runs the `make` command with the specified target in the remote destination directory.
    
    Parameters:
        target (str): The target to build with the `make` command.
    
    Returns:
        None
    """

    def run_make(self, target):
        import subprocess

        make_args = ['make', target]
        make_args.extend(self.make_vars)
        subprocess.check_call(make_args)

    @staticmethod
    def get_workspace_dir(script_path):
        workspace_dir = os.path.realpath(os.path.dirname(script_path))
        current = workspace_dir
        while True:
            for name in (RsyncMake.RMAKE_USER, RsyncMake.RMAKE_INCLUDES, RsyncMake.RMAKE_EXCLUDES,):
                if os.path.isfile(os.path.join(current, name)):
                    workspace_dir = current
                    break
            for name in ('.git',):
                if os.path.isdir(os.path.join(current, name)):
                    workspace_dir = current
                    break
            parent = os.path.dirname(current)
            if current == parent:
                break
            current = parent
        return workspace_dir

    @staticmethod
    def main(main_prog, args=None):
        args = args or sys.argv[1:]

        if sys.platform == "win32":
            return RsyncMake.wsl_main(main_prog, args)

        rmake = RsyncMake()
        # Load the user script.
        user_script = os.path.join(rmake.workspace_dir, rmake.RMAKE_USER)
        if os.path.isfile(user_script):
            rmake.load_user_script(user_script)

        try:
            from argparse import ArgumentParser, ArgumentError
            commands = []

            def command_type(s):
                commands.append(s)
                return s

            def parse_args(args):
                commands.clear()
                namespace = parser.parse_args(args)
                namespace.commands = commands
                return namespace
            parser = ArgumentParser(prog=main_prog,
                                    description='Use the `rsync` command to synchronize files between '
                                    'a Windows local repository and a WSL2 remote repository automatically, '
                                    'and execute compilation in the remote repository to improve '
                                    'compilation performance.')
            parser.add_argument('--src-dir',
                                action='store', type=str, default='', dest='src_dir',
                                help='the source directory of the local repository')
            parser.add_argument('--dst-dir',
                                action='store', type=str, default='', dest='dst_dir',
                                help='the destination directory of the remote repository')
            parser.add_argument('--git-origin',
                                action='store', type=str, default='origin', dest='git_origin',
                                help='git remote origin, defaults to `origin`')
            parser.add_argument('-f', '--force',
                                action='store_true', default=False, dest='force',
                                help='ignore errors, never prompt')
            parser.add_argument('--include', metavar='INCLUDE',
                                action='append', type=lambda x: '--include=' + x, dest='rsync_options',
                                help='rsync option --include')
            parser.add_argument('--include-from', metavar='INCLUDE-FROM',
                                action='append', type=lambda x: '--include-from=' + x, dest='rsync_options',
                                help='rsync option --include-from')
            parser.add_argument('--exclude', metavar='EXCLUDE',
                                action='append', type=lambda x: '--exclude=' + x, dest='rsync_options',
                                help='rsync option --exclude')
            parser.add_argument('--exclude-from', metavar='EXCLUDE-FROM',
                                action='append', type=lambda x: '--exclude-from=' + x, dest='rsync_options',
                                help='rsync option --exclude-from')
            parser.add_argument('--no-perms',
                                action='append_const', const='--no-perms', dest='rsync_options',
                                help='rsync option --no-perms')
            parser.add_argument('--progress',
                                action='append_const', const='--progress', dest='rsync_options',
                                help='rsync option --progress')
            parser.add_argument('clone', type=command_type, nargs='?',
                                help='clone a clean remote repository at the destination directory')
            parser.add_argument('pull', type=command_type, nargs='?',
                                help='clean and pull the remote repository at the destination directory')
            parser.add_argument('checkout', type=command_type, nargs='?',
                                help='checkout the remote repository at the destination directory, use -f option to ignore errors')
            parser.add_argument('remove-git', type=command_type, nargs='?',
                                help='remove the remote repository at the destination directory')
            parser.add_argument('rsync', type=command_type, nargs='?',
                                help='rsync all source files from the source directory to the destination directory')
            parser.add_argument('rsync-back', type=command_type, nargs='?',
                                help='rsync all generated files from the destination directory to the source directory')
            parser.add_argument('exec', type=command_type, nargs='?',
                                help='execute the following shell command at the destination directory')
            parser.add_argument('build', type=command_type, nargs='?',
                                help='(DEFAULT) execute build in the remote repository and sync backward')
            parser.add_argument(' | '.join(rmake.make_targets),
                                type=command_type, nargs='?',
                                help='execute `make` in the remote repository and sync backward if it is not a clean command.')
            rmake.user.add_arguments(parser, command_type)
            parser.add_argument('commands', metavar='COMMAND', type=command_type, nargs='*',
                                help='other user defined command')
            if 'exec' in args:
                start = 0
                while True:
                    try:
                        idx = args[start:].index('exec')
                    except ValueError:
                        break
                    namespace = parse_args(args[:idx + 1])
                    if 'exec' in namespace.commands:
                        rmake.exec_cmd_args = args[idx + 1:]
                        return rmake.run(namespace)
                    start = idx + 1
            return rmake.run(parse_args(args))

        except KeyboardInterrupt:
            print('^C')
            return ShellCmd.EINTERRUPT
        except RsyncMakeError as e:
            print('*** [Error {}]'.format(e.code), e, file=sys.stderr)
            return e.code
        except Exception as e:
            print('***', e, file=sys.stderr)
            return ShellCmd.EFAIL

    @staticmethod
    def wsl_main(main_prog, args=None):
        import subprocess

        # Enter the workspace directory.
        cmake_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
        os.chdir(RsyncMake.get_workspace_dir(cmake_dir))

        wsl_args = ['wsl.exe', '--shell-type', 'login']
        rmake_args = []

        # Split WSL options from rmake options.
        cmd_args = args or sys.argv[1:]
        while cmd_args:
            arg = cmd_args[0]
            for option in ('--distribution', '-d', '--user', '-u'):
                if arg == option:
                    wsl_args.append(arg)
                    if len(cmd_args) <= 1:
                        print('Error: {} requires an argument.'.format(
                            arg), file=sys.stderr)
                        return 1
                    wsl_args.append(cmd_args[1])
                    cmd_args = cmd_args[1:]
                    arg = None
                    break
                elif option.startswith('--') and arg.startswith(option + '='):
                    wsl_args.append(arg)
                    arg = None
                    break
            if arg:
                rmake_args.append(arg)
            cmd_args = cmd_args[1:]

        # The path of the rmake program must contains '/'.
        rmake_py = os.path.relpath(os.path.join(
            cmake_dir, main_prog)).replace('\\', '/')
        if '/' not in rmake_py:
            rmake_py = './' + rmake_py

        # Run wsl.exe on Windows.
        wsl_args.append(rmake_py)
        wsl_args.extend(rmake_args)
        return subprocess.call(wsl_args)
