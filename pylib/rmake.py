# -*- coding: utf-8 -*-
"""Windows to WSL2 file synchronization and remote build executor."""

import os
import re
import subprocess
import sys
from typing import Any, List, Optional, Tuple, Callable

from cmk.pylib.sys_utils import host_target_info


class RmakeUserBase:
    """Base class for user-defined build scripting logic in rmake."""

    def __init__(self, rmake: "RsyncMake") -> None:
        self.rmake = rmake

    def add_arguments(self, parser: Any, command_type: Callable[[str], str]) -> None:
        """Add custom arguments to the argparse parser."""
        pass

    def prepare(self) -> None:
        """Run preparation steps before execution."""
        pass

    def sync_forward(self) -> None:
        """Synchronize repository forward to remote."""
        rmake = self.rmake
        rmake.git_clone()

        rsync = ["rsync"]
        rsync.extend(rmake.rsync_args)
        rsync.append((rmake.src_dir + "/").replace("//", "/"))
        rsync.append((rmake.dst_dir + "/").replace("//", "/"))
        subprocess.check_call(rsync)

    def sync_backward(self) -> None:
        """Synchronize build outputs backward to local."""
        pass

    def exec_command(self, command: str) -> int:
        """Execute a custom target command."""
        return -1


def _rsync_times_ok() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


class RsyncMake:
    """Implement sync-and-make logic for WSL2 cross-compilation."""

    RMAKE_REMOTE_ROOT: str = "~/.rmake/githome"
    RMAKE_USER: str = ".rmake-user.py"
    RMAKE_USER_CLASS: str = "RmakeUser"
    RMAKE_INCLUDES: str = ".rmake-includes"
    RMAKE_EXCLUDES: str = ".rmake-excludes"
    RSYNC_ARGS: List[str] = ["-v", "-rlpt", "--mkpath", "--delete", "--exclude=.git"]
    RSYNC_BACKWARD_ARGS: List[str] = [
        "-v",
        "-rl{}".format("t" if _rsync_times_ok() else "c"),
        "--mkpath",
    ]
    MAKE_TARGETS: List[str] = [
        "cargo",
        "cargo-*",
        "clean",
        "clean-*",
        "cmake",
        "cmake-*",
        "update-libs",
    ]

    def __init__(self) -> None:
        self.args: Any = None
        self.user: RmakeUserBase = RmakeUserBase(self)

        self.remote_root: str = os.path.expanduser(self.RMAKE_REMOTE_ROOT)
        self.src_dir: str = ""
        self.dst_dir: str = ""
        self.rsync_args: List[str] = list(self.RSYNC_ARGS)
        self.make_targets: List[str] = list(self.MAKE_TARGETS)
        self.commands: List[str] = []
        self.make_vars: List[str] = []
        self.exec_cmd_args: List[str] = []
        self.workspace_dir: str = RsyncMake.get_workspace_dir(__file__)

        self.has_synced_forward: bool = False
        self.need_sync_backward: bool = False

    def _run(self, args: Any) -> int:
        self.args = args
        self.src_dir = os.path.realpath(self.args.src_dir or self.workspace_dir)

        if self.args.dst_dir:
            self.dst_dir = self.args.dst_dir
        else:
            git_home_base = os.path.basename(self.remote_root)
            idx = self.src_dir.find(os.sep + git_home_base + os.sep)
            if idx >= 0:
                self.dst_dir = (
                    self.remote_root
                    + self.src_dir[idx + len(git_home_base) + 1 :]
                )
            else:
                from urllib.parse import quote, urlparse
                origin_url = self.git_config_get(
                    "remote.{}.url".format(self.args.git_origin)
                )
                git_url = urlparse(origin_url)
                git_hostname = git_url.hostname or git_url.netloc
                git_path = git_url.path.strip("/\\")
                if git_path.endswith(".git"):
                    git_path = os.path.splitext(git_path)[0]
                if not git_hostname or not git_path:
                    self.error(
                        '\n'.join(
                            [
                                '"{}" does not have an ancestor directory named "{}"'.format(
                                    self.src_dir, git_home_base
                                ),
                                'Please move the source repository into a directory named "{}"'.format(
                                    git_home_base
                                ),
                                "or specify the destination directory with the option: --dst-dir <dst_dir>",
                            ]
                        )
                    )
                self.dst_dir = os.path.join(
                    os.path.dirname(self.remote_root),
                    quote(git_hostname),
                    git_path,
                )
        self.dst_dir = os.path.realpath(self.dst_dir)

        self.rsync_args.extend(self.args.rsync_args or [])
        if not list(
            filter(lambda x: x.startswith("--include-from="), self.rsync_args)
        ):
            include_from = os.path.join(self.src_dir, self.RMAKE_INCLUDES)
            if os.path.isfile(include_from):
                self.rsync_args.append("--include-from=" + include_from)
        if not list(
            filter(lambda x: x.startswith("--exclude-from="), self.rsync_args)
        ):
            exclude_from = os.path.join(self.src_dir, self.RMAKE_EXCLUDES)
            if not os.path.isfile(exclude_from):
                exclude_from = os.path.join(self.src_dir, ".gitignore")
                if not os.path.isfile(exclude_from):
                    exclude_from = ""
            if exclude_from:
                self.rsync_args.append("--exclude-from=" + exclude_from)

        self.commands.extend(x for x in self.args.commands if "=" not in x)
        if not self.commands:
            self.commands.append("build")
        self.make_vars.extend(x for x in self.args.commands if "=" in x)

        if not os.path.isdir(self.src_dir):
            self.error('"{}" is not a directory.'.format(self.src_dir))

        if self.src_dir.startswith(self.dst_dir) or self.dst_dir.startswith(
            self.src_dir
        ):
            self.error(
                "The source directory and the destination directory "
                "can't be nested within each other."
            )

        print(
            "rsync: [ {} ] -- [ {} ]".format(self.src_dir, self.dst_dir),
            flush=True,
        )

        if os.path.isdir(self.dst_dir):
            os.chdir(self.dst_dir)

        for item in self.args.env_vars or []:
            kv = item.split("=", 1)
            if len(kv) == 2:
                if kv[1]:
                    os.environ[kv[0]] = kv[1]
                elif kv[0] in os.environ:
                    del os.environ[kv[0]]

        self.user.prepare()

        for command in self.commands:
            if command in ("clone", "pull"):
                self.git_checkout(force=True)
            elif command == "checkout":
                self.git_checkout(force=self.args.force)
            elif command == "remove-git":
                if os.path.isdir(self.dst_dir):
                    import shutil
                    os.chdir(os.path.expanduser("~"))
                    print("Removing {} ...".format(self.dst_dir))
                    shutil.rmtree(self.dst_dir)
                    print("Done.")
            elif command == "rsync":
                self.sync_forward(force=True)
            elif command == "rsync-back":
                self.sync_backward()
                self.finish_sync_backward()
            elif command == "exec":
                if self.exec_cmd_args:
                    os.chdir(self.dst_dir)
                    subprocess.check_call(self.exec_cmd_args)
            elif self.user.exec_command(command) != -1:
                pass
            elif re.match(
                "^(?:build|{})$".format(
                    "|".join(self.make_targets).replace("*", ".*")
                ),
                command,
            ):
                self.sync_forward()
                self.run_make(command)
                self.sync_backward()
            else:
                self.error('Unknown command "{}"'.format(command))

        if not self.args.skip_rsync_back and not self.args.skip_rsync_all:
            self.finish_sync_backward()
        return 0

    def error(self, message: str, code: int = 1) -> None:
        """Show error message and exit with code."""
        print("*** [Error {}]".format(code), message, file=sys.stderr)
        sys.exit(code)

    def load_user_script(self, script_path: str) -> None:
        """Load optional custom user script (like .rmake-user.py)."""
        with open(script_path, "r") as fp:
            code = fp.read()
        exec(code, globals(), globals())
        user_cls = globals().get(self.RMAKE_USER_CLASS)
        if not isinstance(user_cls, type) or not issubclass(
            user_cls, RmakeUserBase
        ):
            self.error(
                'Class {} is not defined in "{}".'.format(
                    self.RMAKE_USER_CLASS, script_path
                )
            )
        self.user = user_cls(self)

    def git_config_get(self, key: str) -> str:
        """Query git config value."""
        return subprocess.check_output(
            ["git", "config", "--get", key], text=True
        ).strip()

    def git_remote_branch_exists(self, branch: str) -> bool:
        """Check if remote branch exists."""
        return (
            subprocess.call(
                [
                    "git",
                    "ls-remote",
                    "--exit-code",
                    "--heads",
                    self.args.git_origin,
                    branch,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            == 0
        )

    def git_clone(self) -> None:
        """Perform initial git clone to target remote destination."""
        if os.path.isdir(self.dst_dir):
            os.chdir(self.dst_dir)
            return

        os.chdir(self.src_dir)
        url = self.git_config_get("remote.{}.url".format(self.args.git_origin))
        branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
        ).strip()

        git_clone = ["git", "clone"]
        if self.git_remote_branch_exists(branch):
            git_clone.extend(["--branch", branch])
        git_clone.extend([url, self.dst_dir])
        try:
            os.makedirs(os.path.dirname(self.dst_dir), exist_ok=True)
            subprocess.check_call(git_clone)
            os.chdir(self.dst_dir)
        except (OSError, subprocess.CalledProcessError):
            import shutil
            if os.path.isdir(self.dst_dir):
                os.chdir(os.path.expanduser("~"))
                shutil.rmtree(self.dst_dir)
            raise
        subprocess.check_call(
            ["git", "submodule", "update", "--init", "--recursive"]
        )

    def git_checkout(self, force: bool = False) -> None:
        """Checkout and sync git repository branch at the destination."""
        self.git_clone()
        cwd = os.getcwd()
        try:
            os.chdir(self.src_dir)
            branch = subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                text=True,
            ).strip()
        finally:
            os.chdir(cwd)

        if force:
            subprocess.call(["git", "clean", "--force", "-d"])
            subprocess.call(["git", "checkout", "--force"])
            subprocess.call(
                [
                    "git",
                    "submodule",
                    "foreach",
                    "--recursive",
                    "git",
                    "clean",
                    "--force",
                    "-d",
                ]
            )
            subprocess.call(
                [
                    "git",
                    "submodule",
                    "update",
                    "--init",
                    "--recursive",
                    "--force",
                ]
            )

        current_branch = subprocess.check_output(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            text=True,
        ).strip()
        if current_branch != branch or force:
            subprocess.check_call(["git", "remote", "update"])
            branch_exists = False
            try:
                output = subprocess.check_output(["git", "branch"], text=True)
                branch_exists = branch in [
                    b.strip("* \t\r\n") for b in output.splitlines()
                ]
            except subprocess.CalledProcessError:
                pass

            git_checkout = ["git", "checkout"]
            if force:
                git_checkout.append("--force")
            if branch_exists:
                git_checkout.append(branch)
                subprocess.check_call(git_checkout)
            elif self.git_remote_branch_exists(branch):
                git_checkout.extend(
                    [
                        "-b",
                        branch,
                        "{}/{}".format(self.args.git_origin, branch),
                    ]
                )
                subprocess.check_call(git_checkout)

        subprocess.check_call(["git", "pull"])
        subprocess.check_call(
            ["git", "submodule", "update", "--init", "--recursive"]
        )

    def sync_forward(self, force: bool = False) -> None:
        """Synchronize files forward from source directory to target directory."""
        if not self.has_synced_forward:
            if force or (
                not self.args.skip_rsync and not self.args.skip_rsync_all
            ):
                self.user.sync_forward()
                self.has_synced_forward = True

    def sync_backward(self) -> None:
        """Mark build outputs to sync backward later."""
        self.need_sync_backward = True

    def finish_sync_backward(self) -> None:
        """Trigger sync backward execution if flag is active."""
        if self.need_sync_backward:
            self.user.sync_backward()
            self.need_sync_backward = False

    def run_make(self, target: str) -> None:
        """Trigger make command with target on remote destination."""
        make = ["make"]
        make.extend(self.args.make_options or [])
        make.append(target)
        make.extend(self.make_vars)
        subprocess.check_call(make)

    @staticmethod
    def is_wsl2() -> bool:
        """Check if operating environment is WSL2 Linux."""
        import platform
        return (
            platform.system() == "Linux" and "WSL2" in platform.release()
        )

    @staticmethod
    def is_valid_file_name(file_name: str) -> bool:
        """Validate if file name is clean of prohibited characters."""
        return re.match(r"^[^\\\/:*?\"<>|]{1,255}$", file_name) is not None

    @staticmethod
    def get_workspace_dir(script_path: str) -> str:
        """Retrieve closest parent workspace directory with .git or config file."""
        workspace_dir = os.path.realpath(os.path.dirname(script_path))
        current = workspace_dir
        while True:
            for name in (
                RsyncMake.RMAKE_USER,
                RsyncMake.RMAKE_INCLUDES,
                RsyncMake.RMAKE_EXCLUDES,
            ):
                if os.path.isfile(os.path.join(current, name)):
                    return current
            for name in (".git",):
                if os.path.isdir(os.path.join(current, name)):
                    return current
            parent = os.path.dirname(current)
            if current == parent:
                break
            current = parent
        return workspace_dir

    @classmethod
    def main(cls, main_prog: str, args: Optional[List[str]] = None) -> int:
        """CLI main entry point for RsyncMake sync builder."""
        cmd_args = args or sys.argv[1:]

        if sys.platform == "win32":
            return cls.wsl_main(main_prog, cmd_args)

        rmake = cls()
        user_script = os.path.join(rmake.workspace_dir, rmake.RMAKE_USER)
        if os.path.isfile(user_script):
            rmake.load_user_script(user_script)

        try:
            from argparse import ArgumentParser, RawTextHelpFormatter
            commands: List[str] = []

            def command_type(s: str) -> str:
                commands.append(s)
                return s

            def parse_args(parse_list: List[str]) -> Any:
                commands.clear()
                namespace = parser.parse_intermixed_args(parse_list)
                namespace.commands = commands
                return namespace

            parser = ArgumentParser(
                prog=main_prog,
                formatter_class=RawTextHelpFormatter,
                description="WSL2 sync builder",
            )
            parser.add_argument(
                "--wsl-distribution",
                "--wsl-d",
                metavar="DISTRO",
                action="store",
                type=str,
                default="",
                dest="wsl_distro",
                help="run specified WSL2 distribution",
            )
            parser.add_argument(
                "--wsl-user",
                "--wsl-u",
                metavar="USER",
                action="store",
                type=str,
                default="",
                dest="wsl_user",
                help="run as specified WSL2 user",
            )
            parser.add_argument(
                "-e",
                "--environment",
                metavar="NAME=VALUE",
                action="append",
                type=str,
                dest="env_vars",
                help="environment variables",
            )
            parser.add_argument(
                "--src-dir",
                metavar="DIRECTORY",
                action="store",
                type=str,
                default="",
                dest="src_dir",
                help="local repository path",
            )
            parser.add_argument(
                "--dst-dir",
                metavar="DIRECTORY",
                action="store",
                type=str,
                default="",
                dest="dst_dir",
                help="remote repository path",
            )
            parser.add_argument(
                "--git-origin",
                metavar="ORIGIN",
                action="store",
                type=str,
                default="origin",
                dest="git_origin",
                help="git origin name",
            )
            parser.add_argument(
                "-f",
                "--force",
                action="store_true",
                default=False,
                dest="force",
                help="checkout force option",
            )
            parser.add_argument(
                "--include",
                metavar="PATTERN",
                action="append",
                type=lambda x: "--include=" + x,
                dest="rsync_args",
                help="rsync include filter",
            )
            parser.add_argument(
                "--include-from",
                metavar="FILE",
                action="append",
                type=lambda x: "--include-from=" + x,
                dest="rsync_args",
                help="rsync include file",
            )
            parser.add_argument(
                "--exclude",
                metavar="PATTERN",
                action="append",
                type=lambda x: "--exclude=" + x,
                dest="rsync_args",
                help="rsync exclude filter",
            )
            parser.add_argument(
                "--exclude-from",
                metavar="FILE",
                action="append",
                type=lambda x: "--exclude-from=" + x,
                dest="rsync_args",
                help="rsync exclude file",
            )
            parser.add_argument(
                "--no-perms",
                action="append_const",
                const="--no-perms",
                dest="rsync_args",
                help="rsync no-perms option",
            )
            parser.add_argument(
                "--progress",
                action="append_const",
                const="--progress",
                dest="rsync_args",
                help="rsync progress option",
            )
            parser.add_argument(
                "--skip-rsync",
                action="store_true",
                default=False,
                dest="skip_rsync",
                help="skip forward rsync",
            )
            parser.add_argument(
                "--skip-rsync-back",
                action="store_true",
                default=False,
                dest="skip_rsync_back",
                help="skip backward rsync",
            )
            parser.add_argument(
                "--skip-rsync-all",
                action="store_true",
                default=False,
                dest="skip_rsync_all",
                help="skip both rsync operations",
            )
            if rmake.make_targets:
                parser.add_argument(
                    "--file",
                    "--makefile",
                    metavar="FILE",
                    action="append",
                    type=lambda x: "--file=" + x,
                    dest="make_options",
                    help="makefile option passed to make",
                )
                parser.add_argument(
                    "--make-opt",
                    metavar="OPTION",
                    action="append",
                    type=str,
                    dest="make_options",
                    help="make opt option",
                )
            parser.add_argument(
                "clone",
                type=command_type,
                nargs="?",
                help="clone remote repo",
            )
            parser.add_argument(
                "pull",
                type=command_type,
                nargs="?",
                help="pull remote repo",
            )
            parser.add_argument(
                "checkout",
                type=command_type,
                nargs="?",
                help="checkout remote repo",
            )
            parser.add_argument(
                "remove-git",
                type=command_type,
                nargs="?",
                help="remove remote repo",
            )
            parser.add_argument(
                "rsync",
                type=command_type,
                nargs="?",
                help="sync forward",
            )
            parser.add_argument(
                "rsync-back",
                type=command_type,
                nargs="?",
                help="sync backward",
            )
            parser.add_argument(
                "exec",
                type=command_type,
                nargs="?",
                help="exec shell cmd",
            )
            parser.add_argument(
                "build",
                type=command_type,
                nargs="?",
                help="default sync-build",
            )
            if rmake.make_targets:
                parser.add_argument(
                    " | ".join(rmake.make_targets),
                    type=command_type,
                    nargs="?",
                    help="exec make targets",
                )
            rmake.user.add_arguments(parser, command_type)
            parser.add_argument(
                "commands",
                metavar="COMMAND",
                type=command_type,
                nargs="*",
                help="other custom commands",
            )

            if "exec" in cmd_args:
                start = 0
                while True:
                    try:
                        idx = cmd_args[start:].index("exec")
                    except ValueError:
                        break
                    namespace = parse_args(cmd_args[: idx + 1])
                    if "exec" in namespace.commands:
                        rmake.exec_cmd_args = cmd_args[idx + 1 :]
                        return rmake._run(namespace)
                    start = idx + 1
            return rmake._run(parse_args(cmd_args))

        except KeyboardInterrupt:
            print("^C", file=sys.stderr)
            return 254
        except Exception as e:
            if os.environ.get("CMKABE_DEBUG") == "1":
                import traceback
                traceback.print_exc(file=sys.stderr)
            else:
                print("*** Error:", e, file=sys.stderr)
            return (
                e.returncode
                if (isinstance(e, subprocess.CalledProcessError) and e.returncode > 0)
                else 1
            )

    @classmethod
    def wsl_main(cls, main_prog: str, args: List[str]) -> int:
        """Windows main proxy running under wsl.exe wrapper."""
        rmake_dir = os.path.dirname(os.path.realpath(sys.argv[0]))
        os.chdir(cls.get_workspace_dir(rmake_dir))

        wsl_args = ["wsl.exe", "--shell-type", "login"]
        rmake_args: List[str] = []

        cmd_args = args
        while cmd_args:
            arg = cmd_args[0]
            matched = False
            for option in (
                "--wsl-distribution",
                "--wsl-d",
                "--wsl-user",
                "--wsl-u",
            ):
                if arg == option:
                    wsl_args.append(
                        arg.replace("-wsl" if len(option) > 7 else "--wsl", "")
                    )
                    if len(cmd_args) <= 1:
                        print(
                            "Error: {} requires an argument.".format(arg),
                            file=sys.stderr,
                        )
                        return 1
                    wsl_args.append(cmd_args[1])
                    cmd_args = cmd_args[1:]
                    matched = True
                    break
                elif option.startswith("--") and arg.startswith(option + "="):
                    wsl_args.append(arg)
                    matched = True
                    break
            if not matched:
                rmake_args.append(arg)
            cmd_args = cmd_args[1:]

        rmake_py = os.path.relpath(
            os.path.join(rmake_dir, main_prog)
        ).replace("\\", "/")
        if "/" not in rmake_py:
            rmake_py = "./" + rmake_py

        wsl_args.append(rmake_py)
        wsl_args.extend(rmake_args)
        return subprocess.call(wsl_args)
