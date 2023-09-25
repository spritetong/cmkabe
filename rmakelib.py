import os
import sys
import subprocess

"""
The base class of the user defined interface
"""


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
    Synchronizes the source files from the local source directory to
    the remote destination directory.

    Parameters:
        None
    
    Returns:
        None
    """

    def sync_forward(self):
        rmake = self.rmake

        rmake.git_try_clone()

        rsync_args = ['rsync']
        rsync_args.extend(rmake.rsync_args)
        rsync_args.append((rmake.src_dir + '/').replace('//', '/'))
        rsync_args.append((rmake.dst_dir + '/').replace('//', '/'))
        subprocess.check_call(rsync_args)

    """
    Synchronizes the generated files from the remote destination directory to
    the local source directory.

    Parameters:
        None

    Returns:
        None
    """

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


class RsyncMake:
    RMAKE_REMOTE_ROOT = '~/.rmake/githome'
    RMAKE_USER = '.rmake-user.py'
    RMAKE_USER_CLASS = 'RmakeUser'
    RMAKE_INCLUDES = '.rmake-includes'
    RMAKE_EXCLUDES = '.rmake-excludes'
    RSYNC_ARGS = ['-av', '--delete', '--mkpath', '--exclude=.git']
    MAKE_TARGETS = ['cargo', 'cargo-*', 'clean',
                    'clean-*', 'cmake', 'cmake-*', 'update-libs']

    def __init__(self):
        # the command line arguments
        self.args = None
        # the user defined interface
        self.user = RmakeUserBase(self)

        # the `git` home directory
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

    def run(self, args):
        import re

        self.args = args

        # <src_dir>
        self.src_dir = os.path.realpath(args.src_dir or self.workspace_dir)

        # <dst_dir>
        if args.dst_dir:
            self.dst_dir = args.dst_dir
        else:
            git_home_base = os.path.basename(self.remote_root)
            idx = self.src_dir.find('/' + git_home_base + '/')
            if idx < 0:
                self.error('\n'.join([
                    '"{}" does not have an ancestor directory named "{}"'.format(
                        self.src_dir, git_home_base),
                    'Please move the source repository into a directory named "{}"'.format(
                        git_home_base),
                    'or specify the destination directory with the option: --dst-dir <dst_dir>',
                ]))
            self.dst_dir = self.remote_root + \
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
                self.sync_forward()
            elif command == 'rsync-back':
                # Do sync immediately
                self.user.sync_backward()
            elif command == 'exec':
                os.chdir(self.dst_dir)
                subprocess.check_call(self.exec_cmd_args)
            elif self.user.exec_command(command) != -1:
                pass
            elif re.match('^(?:build|{})$'.format('|'.join(self.make_targets).replace('*', '.*')), command):
                self.sync_forward()
                # Run make
                self.run_make(command)
                # Sync generated files after build
                if 'clean' not in command:
                    self.sync_backward()
            else:
                self.error('Unknown command "{}"'.format(command))

        if self.need_sync_backward:
            # Do sync at the end
            self.user.sync_backward()
        return 0

    """
    Show the error message and exit with the error code.

    Parameters:
        message (str): The error message.
        code (int, optional): The error code. Defaults to 1.
    """

    def error(self, message, code=1):
        print('*** [Error {}]'.format(code), message, file=sys.stderr)
        sys.exit(code)

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

            os.makedirs(os.path.dirname(self.dst_dir), exist_ok=True)
            subprocess.check_call(' && '.join([
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
            # Check if the local branch exists
            branch_exists = False
            try:
                output = subprocess.check_output(["git", "branch"], text=True)
                branch_exists = branch in [branch.strip(
                    '* \t\r\n') for branch in output.splitlines()]
            except subprocess.CalledProcessError:
                pass
            if branch_exists:
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
    Synchronizes the source files from the local source directory to
    the remote destination directory.

    This method checks if the synchronization operation has already been executed.
    If not, it calls the `sync_forward()` method of the `user` object.

    Parameters:
        None
    
    Returns:
        None
    """

    def sync_forward(self):
        if not self.has_synced_forward:
            self.user.sync_forward()
            self.has_synced_forward = True

    """
    Set the `need_sync_backward` flag to `True` to synchronize the generated files from 
    the remote destination directory to the local source directory in future.

    This function does not do the real synchronization operation, but only sets the flag.

    Parameters:
        None

    Returns:
        None
    """

    def sync_backward(self):
        self.need_sync_backward = True

    """
    Runs the `make` command with the specified target in the remote destination directory.
    
    Parameters:
        target (str): The target to build with the `make` command.
    
    Returns:
        None
    """

    def run_make(self, target):
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
            parser.add_argument('--wsl-distribution', '--wsl-d', metavar='WSL_DISTRO',
                                action='store', type=str, default='', dest='wsl_distro',
                                help='run the specified WSL2 distribution')
            parser.add_argument('--wsl-user', '--wsl-u', metavar='WSL_USER',
                                action='store', type=str, default='', dest='wsl_user',
                                help='run as the specified WSL2 user')
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
                                help='(DEFAULT) execute build in the remote repository, then sync backward')
            if rmake.make_targets:
                parser.add_argument(' | '.join(rmake.make_targets),
                                    type=command_type, nargs='?',
                                    help='execute `make` in the remote repository, then sync backward if it is not a clean command.')
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
            return 254
        except Exception as e:
            print('***', e, file=sys.stderr)
            return e.returncode if (
                isinstance(e, subprocess.CalledProcessError) and e.returncode > 0) else 1

    @staticmethod
    def wsl_main(main_prog, args=None):
        # Enter the workspace directory.
        cmake_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
        os.chdir(RsyncMake.get_workspace_dir(cmake_dir))

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
            cmake_dir, main_prog)).replace('\\', '/')
        if '/' not in rmake_py:
            rmake_py = './' + rmake_py

        # Run wsl.exe on Windows.
        wsl_args.append(rmake_py)
        wsl_args.extend(rmake_args)
        return subprocess.call(wsl_args)
