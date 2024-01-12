"""The `rsync-make` library

This file is the part of the cmake-abe library (https://github.com/spritetong/cmake-abe),
which is licensed under the MIT license (https://opensource.org/licenses/MIT).

Copyright (C) 2023 spritetong@gmail.com.
"""

import os
import re
import sys
import subprocess


class RmakeUserBase:
    """The base class of the user defined interface
    """

    def __init__(self, rmake):
        """Constructor

        Parameters:
            rmake (RsyncMake): The rmake object to be assigned.

        Returns:
            None
        """
        self.rmake = rmake

    def add_arguments(self, parser, command_type):
        """Add some arguemnents to the argument parser.

        Parameters:
            parser (argparse.ArgumentParser): The argument parser object.
            command_type (Callable): The type of command.

        Returns:
            None
        """
        pass

    def prepare(self):
        """Initialize and prepare to execute commands.

        This method is called before any command is executed.
        """
        pass

    def sync_forward(self):
        """
        Synchronizes the source files from the local source directory to
        the remote destination directory.

        Parameters:
            None

        Returns:
            None
        """
        rmake = self.rmake
        rmake.git_clone()

        rsync = ['rsync']
        rsync.extend(rmake.rsync_args)
        rsync.append((rmake.src_dir + '/').replace('//', '/'))
        rsync.append((rmake.dst_dir + '/').replace('//', '/'))
        subprocess.check_call(rsync)

    def sync_backward(self):
        """
        Synchronizes the generated files from the remote destination directory to
        the local source directory.

        Parameters:
            None

        Returns:
            None
        """
        pass

    def exec_command(self, command):
        """Execute a user command.

        Parameters:
            command (str): The command to execute.

        Returns:
            int: 0 if the command was executed successfully, -1 to ignore the command.
        """
        return -1


class RsyncMake:
    RMAKE_REMOTE_ROOT = '~/.rmake/githome'
    RMAKE_USER = '.rmake-user.py'
    RMAKE_USER_CLASS = 'RmakeUser'
    RMAKE_INCLUDES = '.rmake-includes'
    RMAKE_EXCLUDES = '.rmake-excludes'
    # --recursive --links --perms --times
    RSYNC_ARGS = ['-v', '-rlpt', '--mkpath', '--delete', '--exclude=.git']
    MAKE_TARGETS = ['cargo', 'cargo-*', 'clean',
                    'clean-*', 'cmake', 'cmake-*', 'update-libs']

    def __init__(self):
        """Constructor
        """
        # the command line arguments
        self.args = None
        # the user defined interface
        self.user = RmakeUserBase(self)

        # the remote `githome` directory
        self.remote_root = os.path.expanduser(self.RMAKE_REMOTE_ROOT)
        # the `rsync` source directory to the local repository
        self.src_dir = ''
        # the `rsync` remote directory to the remote repository
        self.dst_dir = ''
        # the default value of rsync options
        self.rsync_args = list(self.RSYNC_ARGS)
        # the default value of supported make targets
        self.make_targets = list(self.MAKE_TARGETS)
        # all commands parsed from the command line
        self.commands = []
        # all make variables like `<variable>=<value>` parsed from the command line
        self.make_vars = []
        # all arguments follows the `exec` command
        self.exec_cmd_args = []
        # the local workspace directory
        self.workspace_dir = RsyncMake.get_workspace_dir(__file__)

        # internal attributes
        self.has_synced_forward = False
        self.need_sync_backward = False

    def _run(self, args):
        """Process the command line arguments and run.

        Parameters:
            args (argparse.Namespace): The command line arguments

        Returns:
            None
        """
        self.args = args

        # <src_dir>
        self.src_dir = os.path.realpath(
            self.args.src_dir or self.workspace_dir)

        # <dst_dir>
        if self.args.dst_dir:
            self.dst_dir = self.args.dst_dir
        else:
            git_home_base = os.path.basename(self.remote_root)
            idx = self.src_dir.find(os.sep + git_home_base + os.sep)
            if idx >= 0:
                self.dst_dir = self.remote_root + \
                    self.src_dir[idx + len(git_home_base) + 1:]
            else:
                # Use the current repository URL to build the destination directory
                from urllib.parse import urlparse, quote
                git_url = urlparse(self.git_config_get(
                    'remote.{}.url'.format(self.args.git_origin)))
                git_hostname = git_url.hostname or git_url.netloc
                git_path = git_url.path.strip('/\\')
                # Remove the tailing '.git'
                if git_path.endswith('.git'):
                    git_path = os.path.splitext(git_path)[0]
                if not git_hostname or not git_path:
                    self.error('\n'.join([
                        '"{}" does not have an ancestor directory named "{}"'.format(
                            self.src_dir, git_home_base),
                        'Please move the source repository into a directory named "{}"'.format(
                            git_home_base),
                        'or specify the destination directory with the option: --dst-dir <dst_dir>',
                    ]))
                self.dst_dir = os.path.join(os.path.dirname(self.remote_root),
                                            quote(git_hostname), git_path)
        self.dst_dir = os.path.realpath(self.dst_dir)

        # <rsync_args>
        self.rsync_args.extend(self.args.rsync_args or [])
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
        self.commands.extend(x for x in self.args.commands if '=' not in x)
        if not self.commands:
            self.commands.append('build')
        self.make_vars.extend(x for x in self.args.commands if '=' in x)

        if not os.path.isdir(self.src_dir):
            self.error('"{}" is not a directory.'.format(self.src_dir))

        if self.src_dir.startswith(self.dst_dir) or self.dst_dir.startswith(self.src_dir):
            self.error('The source directory and the destination directory '
                       'can\'t be nested within each other.')

        print("rsync: [ {} ] -- [ {} ]".format(
            self.src_dir, self.dst_dir), flush=True)

        # Enter the destination directory
        if os.path.isdir(self.dst_dir):
            os.chdir(self.dst_dir)

        # Set environment variables
        for item in self.args.env_vars or []:
            kv = item.split('=', 1)
            if len(kv) == 2:
                if kv[1]:
                    os.environ[kv[0]] = kv[1]
                elif kv[0] in os.environ:
                    del os.environ[kv[0]]

        # Prepare to run commands.
        self.user.prepare()

        for command in self.commands:
            if command in ('clone', 'pull'):
                self.git_checkout(force=True)
            elif command == 'checkout':
                self.git_checkout(force=self.args.force)
            elif command == 'remove-git':
                if os.path.isdir(self.dst_dir):
                    import shutil
                    os.chdir(os.path.expanduser('~'))
                    print('Removing {} ...'.format(self.dst_dir))
                    shutil.rmtree(self.dst_dir)
                    print('Done.')
            elif command == 'rsync':
                # Force to run sync
                self.sync_forward(force=True)
            elif command == 'rsync-back':
                # Do sync immediately
                self.sync_backward()
                self.finish_sync_backward()
            elif command == 'exec':
                if self.exec_cmd_args:
                    os.chdir(self.dst_dir)
                    subprocess.check_call(self.exec_cmd_args)
            elif self.user.exec_command(command) != -1:
                pass
            elif re.match('^(?:build|{})$'.format('|'.join(self.make_targets).replace('*', '.*')), command):
                self.sync_forward()
                # Run make
                self.run_make(command)
                # Sync generated files after build
                self.sync_backward()
            else:
                self.error('Unknown command "{}"'.format(command))

        if not self.args.skip_rsync_back and not self.args.skip_rsync_all:
            # Do sync at the end
            self.finish_sync_backward()
        return 0

    def error(self, message, code=1):
        """Show the error message and exit with the error code.

        Parameters:
            message (str): The error message.
            code (int, optional): The error code. Defaults to 1.
        """
        print('*** [Error {}]'.format(code), message, file=sys.stderr)
        sys.exit(code)

    def load_user_script(self, script_path):
        """Load a user script from the given file path.

        Parameters:
            script_path (str): The path to the user script file.

        Returns:
            None
        """
        with open(script_path, 'r') as fp:
            code = fp.read()
        exec(code, globals(), globals())
        user_cls = globals().get(self.RMAKE_USER_CLASS)
        if not isinstance(user_cls, type) or not issubclass(user_cls, RmakeUserBase):
            self.error('Class {} is not defined in "{}".'.format(
                self.RMAKE_USER_CLASS, script_path))
        self.user = user_cls(self)

    def git_config_get(self, key):
        """Get the value of a Git configuration option.

        Parameters:
            key (str): The configuration option key.

        Returns:
            str : The value
        """
        return subprocess.check_output(['git', 'config', '--get', key], text=True).strip()

    def git_remote_branch_exists(self, branch):
        """Check if a Git remote branch exists.

        Parameters:
            branch (str): The branch name.

        Returns:
            boolean : True if the branch exists, False otherwise
        """
        return subprocess.call(['git', 'ls-remote', '--exit-code', '--heads',
                                self.args.git_origin, branch],
                               stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL) == 0

    def git_clone(self):
        """Try to clone a Git repository into the specified destination directory, and enter it on success.

        Parameters:
            None

        Returns:
            None
        """
        if os.path.isdir(self.dst_dir):
            # Enter the destination directory
            os.chdir(self.dst_dir)
            return

        os.chdir(self.src_dir)
        # Get the current repository URL
        url = self.git_config_get('remote.{}.url'.format(self.args.git_origin))
        # Get the current branch name
        branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            text=True,
        ).strip()

        git_clone = ['git', 'clone']
        if self.git_remote_branch_exists(branch):
            # The remote branch exists
            git_clone.extend(['--branch', branch])
        git_clone.extend([url, self.dst_dir])
        try:
            os.makedirs(os.path.dirname(self.dst_dir), exist_ok=True)
            subprocess.check_call(git_clone)
            os.chdir(self.dst_dir)
        except (OSError, subprocess.CalledProcessError):
            import shutil
            if os.path.isdir(self.dst_dir):
                os.chdir(os.path.expanduser('~'))
                shutil.rmtree(self.dst_dir)
            raise
        subprocess.check_call(
            ['git', 'submodule', 'update', '--init', '--recursive'])

    def git_checkout(self, force=False):
        '''Checks out a Git branch and updates the working directory to match the branch.

        Parameters:
            force (bool, optional): If True, forcefully clean unversioned files and
            revert dirty files. Defaults to False.

        Returns:
            None
        '''
        self.git_clone()
        cwd = os.getcwd()
        try:
            os.chdir(self.src_dir)
            # Get the current branch name
            branch = subprocess.check_output(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                text=True,
            ).strip()
        finally:
            os.chdir(cwd)

        # Clean unversioned files and revert dirty files.
        if force:
            subprocess.call(['git', 'clean', '--force', '-d'])
            subprocess.call(['git', 'checkout', '--force'])
            subprocess.call(['git', 'submodule', 'foreach',
                            '--recursive', 'git', 'clean', '--force', '-d'])
            subprocess.call(['git', 'submodule', 'update',
                            '--init', '--recursive', '--force'])

        current_branch = subprocess.check_output(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            text=True,
        ).strip()
        if current_branch != branch or force:
            subprocess.check_call(['git', 'remote', 'update'])
            # Check if the local branch exists
            branch_exists = False
            try:
                output = subprocess.check_output(["git", "branch"], text=True)
                branch_exists = branch in [branch.strip(
                    '* \t\r\n') for branch in output.splitlines()]
            except subprocess.CalledProcessError:
                pass

            git_checkout = ['git', 'checkout']
            if force:
                git_checkout.append('--force')
            if branch_exists:
                git_checkout.append(branch)
                subprocess.check_call(git_checkout)
            elif self.git_remote_branch_exists(branch):
                # The remote branch exists
                git_checkout.extend(
                    ['-b', branch, '{}/{}'.format(self.args.git_origin, branch)])
                subprocess.check_call(git_checkout)

        subprocess.check_call(['git', 'pull'])
        subprocess.check_call(
            ['git', 'submodule', 'update', '--init', '--recursive'])

    def sync_forward(self, force=False):
        """
        Synchronizes the source files from the local source directory to
        the remote destination directory.

        This method checks if the synchronization operation has already been executed.
        If not, it calls the `sync_forward()` method of the `user` object.

        Parameters:
            force (bool): If True, forcefully execute the synchronization operation without checking the
                `--skip-rsync` and `--skip-rsync-all` options.
                Defaults to False.

        Returns:
            None
        """
        if not self.has_synced_forward:
            if (force or (not self.args.skip_rsync and not self.args.skip_rsync_all)):
                self.user.sync_forward()
                self.has_synced_forward = True

    def sync_backward(self):
        """
        Set the `need_sync_backward` flag to `True` to synchronize the generated files from 
        the remote destination directory to the local source directory in future.

        This function does not do the real synchronization operation, but only sets the flag.

        Parameters:
            None

        Returns:
            None
        """
        self.need_sync_backward = True

    def finish_sync_backward(self):
        """
        Try to synchronize the generated files from the remote destination directory to
        the local source directory immediately if `need_sync_backward` is True;
        do nothing if `need_sync_backward` is False.

        Parameters:
            None

        Returns:
            None
        """
        if self.need_sync_backward:
            self.user.sync_backward()
            self.need_sync_backward = False

    def run_make(self, target):
        """Runs the `make` command with the specified target in the remote destination directory.

        Parameters:
            target (str): The target to build with the `make` command.

        Returns:
            None
        """
        make = ['make']
        make.extend(self.args.make_options or [])
        make.append(target)
        make.extend(self.make_vars)
        subprocess.check_call(make)

    @staticmethod
    def is_wsl2():
        """Checks if the current operating system is WSL2

        Parameters:
            None

        Returns:
            boolean : True if WSL2, False otherwise
        """
        import platform
        return platform.system() == 'Linux' and 'WSL2' in platform.release()

    @staticmethod
    def is_valid_file_name(file_name):
        """
        Checks if the file name is valid

        Parameters:
            name (str): The file name to check

        Returns:
            boolean : True if the file name is valid, False otherwise
        """
        return re.match(r"^[^\\\/:*?\"<>|]{1,255}$", file_name) is not None

    @staticmethod
    def get_workspace_dir(script_path):
        """Gets the workspace directory from the given script path
        """
        workspace_dir = os.path.realpath(os.path.dirname(script_path))
        current = workspace_dir
        while True:
            for name in (RsyncMake.RMAKE_USER, RsyncMake.RMAKE_INCLUDES, RsyncMake.RMAKE_EXCLUDES,):
                if os.path.isfile(os.path.join(current, name)):
                    return current
            for name in ('.git',):
                if os.path.isdir(os.path.join(current, name)):
                    return current
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
            from argparse import ArgumentParser, RawTextHelpFormatter
            commands = []

            def command_type(s):
                commands.append(s)
                return s

            def parse_args(args):
                commands.clear()
                namespace = parser.parse_intermixed_args(args)
                namespace.commands = commands
                return namespace
            parser = ArgumentParser(prog=main_prog,
                                    formatter_class=RawTextHelpFormatter,
                                    description='Use the `rsync` command to synchronize files between '
                                    'a Windows local repository and a WSL2 remote repository automatically, '
                                    'and execute compilation in the remote repository to improve '
                                    'compilation performance.',
                                    epilog='examples:\n'
                                    '  # Build the project (each command is OK)\n'
                                    '  rmake\n'
                                    '  rmake build\n\n'
                                    '  # Build the project in the WSL2 distro named "ubuntu"\n'
                                    '  rmake --wsl-d ubuntu\n\n'
                                    '  # Build two targets with variable(s) in a single command line\n'
                                    '  rmake cmake-build cargo-build TARGET=native\n\n'
                                    '  # Clean and pull the remote repository\n'
                                    '  rmake checkout -f\n\n'
                                    '  # Remove the whole remote repository\n'
                                    '  rmake remove-git\n\n'
                                    '  # Execute a bash shell in the remote repository\n'
                                    '  rmake exec bash\n\n'
                                    )
            parser.add_argument('--wsl-distribution', '--wsl-d', metavar='DISTRO',
                                action='store', type=str, default='', dest='wsl_distro',
                                help='run the specified WSL2 distribution')
            parser.add_argument('--wsl-user', '--wsl-u', metavar='USER',
                                action='store', type=str, default='', dest='wsl_user',
                                help='run as the specified WSL2 user')
            parser.add_argument('-e', '--environment', metavar='NAME=VALUE',
                                action='append', type=str, dest='env_vars',
                                help='environment variables')
            parser.add_argument('--src-dir', metavar='DIRECTORY',
                                action='store', type=str, default='', dest='src_dir',
                                help='the source directory of the local repository')
            parser.add_argument('--dst-dir', metavar='DIRECTORY',
                                action='store', type=str, default='', dest='dst_dir',
                                help='the destination directory of the remote repository')
            parser.add_argument('--git-origin', metavar='ORIGIN',
                                action='store', type=str, default='origin', dest='git_origin',
                                help='git remote origin, defaults to `origin`')
            parser.add_argument('-f', '--force',
                                action='store_true', default=False, dest='force',
                                help='see the `checkout` command')
            parser.add_argument('--include', metavar='PATTERN',
                                action='append', type=lambda x: '--include=' + x, dest='rsync_args',
                                help='rsync option --include')
            parser.add_argument('--include-from', metavar='FILE',
                                action='append', type=lambda x: '--include-from=' + x, dest='rsync_args',
                                help='rsync option --include-from')
            parser.add_argument('--exclude', metavar='PATTERN',
                                action='append', type=lambda x: '--exclude=' + x, dest='rsync_args',
                                help='rsync option --exclude')
            parser.add_argument('--exclude-from', metavar='FILE',
                                action='append', type=lambda x: '--exclude-from=' + x, dest='rsync_args',
                                help='rsync option --exclude-from')
            parser.add_argument('--no-perms',
                                action='append_const', const='--no-perms', dest='rsync_args',
                                help='rsync option --no-perms')
            parser.add_argument('--progress',
                                action='append_const', const='--progress', dest='rsync_args',
                                help='rsync option --progress')
            parser.add_argument('--skip-rsync',
                                action='store_true', default=False, dest='skip_rsync',
                                help='skip `rsync` forward before executing commands')
            parser.add_argument('--skip-rsync-back',
                                action='store_true', default=False, dest='skip_rsync_back',
                                help='skip `rsync` backward after executing commands')
            parser.add_argument('--skip-rsync-all',
                                action='store_true', default=False, dest='skip_rsync_all',
                                help='skip `rsync` both forward and backward')
            if rmake.make_targets:
                parser.add_argument('--file', '--makefile', metavar='FILE',
                                    action='append', type=lambda x: '--file=' + x, dest='make_options',
                                    help='read FILE as a makefile, passed to `make`')
                parser.add_argument('--make-opt', metavar='OPTION',
                                    action='append', type=str, dest='make_options',
                                    help='an option passed to `make`')
            parser.add_argument('clone', type=command_type, nargs='?',
                                help='clone a clean remote repository at the destination directory')
            parser.add_argument('pull', type=command_type, nargs='?',
                                help='clean and pull the remote repository at the destination directory')
            parser.add_argument('checkout', type=command_type, nargs='?',
                                help='checkout the remote repository at the destination directory, use -f option to ignore errors')
            parser.add_argument('remove-git', type=command_type, nargs='?',
                                help='remove the remote repository at the destination directory')
            parser.add_argument('rsync', type=command_type, nargs='?',
                                help='rsync (forward) all source files from the source directory to the destination directory')
            parser.add_argument('rsync-back', type=command_type, nargs='?',
                                help='rsync (backward) all generated files from the destination directory to the source directory')
            parser.add_argument('exec', type=command_type, nargs='?',
                                help='execute the following shell command at the destination directory')
            parser.add_argument('build', type=command_type, nargs='?',
                                help='(DEFAULT) execute build in the remote repository, then sync backward')
            if rmake.make_targets:
                parser.add_argument(' | '.join(rmake.make_targets),
                                    type=command_type, nargs='?',
                                    help='execute `make` in the remote repository, then sync backward.')
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
                        return rmake._run(namespace)
                    start = idx + 1
            return rmake._run(parse_args(args))

        except KeyboardInterrupt:
            print('^C', file=sys.stderr)
            return 254
        except Exception as e:
            print('***', e, file=sys.stderr)
            return e.returncode if (
                isinstance(e, subprocess.CalledProcessError) and e.returncode > 0) else 1

    @staticmethod
    def wsl_main(main_prog, args=None):
        # Enter the workspace directory.
        rmake_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
        os.chdir(RsyncMake.get_workspace_dir(rmake_dir))

        wsl_args = ['wsl.exe', '--shell-type', 'login']
        rmake_args = []

        # Retrieve WSL options apart from command line arguments.
        cmd_args = args or sys.argv[1:]
        while cmd_args:
            arg = cmd_args[0]
            for option in ('--wsl-distribution', '--wsl-d', '--wsl-user', '--wsl-u'):
                if arg == option:
                    wsl_args.append(arg.replace(
                        '-wsl' if len(option) > 7 else '--wsl', ''))
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
            rmake_dir, main_prog)).replace('\\', '/')
        if '/' not in rmake_py:
            rmake_py = './' + rmake_py

        # Run wsl.exe on Windows.
        wsl_args.append(rmake_py)
        wsl_args.extend(rmake_args)
        return subprocess.call(wsl_args)
