#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import print_function
import os
import sys


EFAIL = 1
EINVAL = 8
EINTERRUPT = 9


def printf(fmt, *args, **kwargs):
    f = kwargs.get("file", sys.stdout)
    f.write(fmt.format(*args))
    if kwargs.get("flush", False):
        f.flush()


def run_shell_command(cmd, options, args):
    status = 0
    if cmd == "rm":
        if not options.recursive:
            import glob
            for pattern in args:
                files = glob.glob(pattern)
                if not files and not options.force:
                    printf("Can't find file {0}\n", pattern, file=sys.stderr)
                    return EFAIL
                for file in files:
                    try:
                        if os.path.isfile(file):
                            os.remove(file)
                        elif os.path.isdir(file):
                            os.rmdir(file)
                    except OSError:
                        status = EFAIL
                        if options.force:
                            continue
                        printf("Can't remove file {0}\n",
                               file, file=sys.stderr)
                        return status
        else:
            import shutil
            import glob

            def onerror(func, path, exc_info):
                import stat
                # Is the error an access error?
                if not os.access(path, os.W_OK):
                    os.chmod(path, stat.S_IWUSR)
                    func(path)
                else:
                    raise

            for pattern in args:
                files = glob.glob(pattern)
                if not files and not options.force:
                    printf("Can't find file {0}\n", pattern, file=sys.stderr)
                    return EFAIL
                for file in files:
                    try:
                        if os.path.isfile(file):
                            os.remove(file)
                        elif os.path.isdir(file):
                            shutil.rmtree(
                                file, ignore_errors=False, onerror=onerror)
                    except OSError:
                        status = EFAIL
                        if options.force:
                            continue
                        printf("Can't remove tree {0}\n",
                               file, file=sys.stderr)
                        return status

    elif cmd == "mkdir":
        import time
        for path in args:
            ok = False
            for i in range(100):
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
                status = EFAIL
                if options.force:
                    continue
                printf("Can't make directory {0}\n", path, file=sys.stderr)
                return status

    elif cmd == "rmdir":
        for path in args:
            try:
                os.rmdir(path)
            except OSError:
                status = EFAIL
                if options.force:
                    continue
                printf("Can't remove directory {0}\n", path, file=sys.stderr)
                return status

    elif cmd == "mv":
        import shutil
        import glob
        if len(args) < 2:
            printf("Invalid parameter {0} for mv\n", args, file=sys.stderr)
            return EFAIL
        dst = args[-1]
        files = []
        for pattern in args[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            printf("{0} is not a direcotry\n", dst, file=sys.stderr)
            return EFAIL
        if not files and not options.force:
            printf("Can't find file {0}\n", pattern, file=sys.stderr)
            return EFAIL
        for file in files:
            try:
                shutil.move(file, dst)
            except OSError:
                status = EFAIL
                if not options.force:
                    printf("Can't move {0} to {1}\n",
                           file, dst, file=sys.stderr)
                return status

    elif cmd == "cp":
        import shutil
        import glob
        if len(args) < 1:
            printf("Invalid parameter {0} for cp\n", args, file=sys.stderr)
            return EFAIL
        if len(args) == 1:
            args.append(".")
        dst = args[-1]
        files = []
        for pattern in args[:-1]:
            files += glob.glob(pattern)
        if len(files) > 1 and not os.path.isdir(dst):
            printf("{0} is not a direcotry\n", dst, file=sys.stderr)
            return EFAIL
        if not files and not options.force:
            printf("Can't find file {0}\n", pattern, file=sys.stderr)
            return EFAIL
        for file in files:
            try:
                if os.path.isfile(file):
                    shutil.copy2(file, dst)
                elif options.recursive:
                    shutil.copytree(file, os.path.join(
                        dst, os.path.basename(file)), dirs_exist_ok=True)
            except OSError:
                status = EFAIL
                if not options.force:
                    printf("Can't copy {0} to {1}\n",
                           file, dst, file=sys.stderr)
                return status

    elif cmd == "cwd":
        printf("{0}", os.getcwd().replace("\\", "/"))

    elif cmd == "mydir":
        path = os.path.dirname(__file__)
        if os.path.isdir(path):
            path = os.path.realpath(path)
        else:
            path = os.getcwd()
        printf("{0}", path.replace("\\", "/"))

    elif cmd == "relpath":
        start = None if len(args) <= 1 else args[1]
        try:
            path = args[0]
            path = os.path.relpath(path, start)
        except (IndexError, ValueError, OSError):
            pass
        printf("{0}", path.replace("\\", "/"))

    elif cmd == "touch":
        import glob
        for pattern in args:
            files = glob.glob(pattern)
            if not files:
                try:
                    open(pattern, 'ab').close()
                except OSError:
                    status = EFAIL
                    if options.force:
                        continue
                    printf("Can't create file {0}\n", pattern, file=sys.stderr)
                    return status
            for file in files:
                try:
                    os.utime(file, None)
                except OSError:
                    status = EFAIL
                    if options.force:
                        continue
                    printf("Can't touch file {0}\n", file, file=sys.stderr)
                    return status

    elif cmd == "timestamp":
        import time
        printf("{0}", time.time())

    elif cmd == "cmpver":
        try:
            v1 = [int(x) for x in (args[0] + ".0.0.0").split(".")[:4]]
            v2 = [int(x) for x in (args[1] + ".0.0.0").split(".")[:4]]
            if v1 > v2:
                result = (1, '+')
            elif v1 == v2:
                result = (0, '0')
            else:
                result = (2, '-')
        except (IndexError, ValueError):
            result = (EINVAL, '')
            printf("Invalid arguments\n", file=sys.stderr)
        printf("{0}", result[1])
        status = 0 if options.force else result[0]

    elif cmd == "upload":
        import ftplib
        import urllib.parse
        if len(args) < 2:
            printf(
                "Invalid parameter {0} for upload\n", args, file=sys.stderr)
            return EFAIL

        ftp_path = args[0]
        files = args[1:]

        parsed = urllib.parse.urlparse(ftp_path)
        if not parsed.hostname:
            printf("No hostname\n", args, file=sys.stderr)
            return EFAIL
        addr = '{0}:{1}'.format(
            parsed.hostname, parsed.port) if parsed.port else parsed.hostname
        username = parsed.username or ''
        password = parsed.password or ''
        remote_dir = parsed.path or '/'

        ftp = ftplib.FTP(addr, username, password)
        try:
            ftp.set_pasv(True)
            for item in files:
                pair = item.split('=')
                (local_file, remote_path) = (pair[0], os.path.basename(
                    pair[0])) if len(pair) == 1 else (pair[1], pair[0])
                remote_file = '/'.join([remote_dir,
                                       remote_path]).replace('\\', '/')
                while '//' in remote_file:
                    remote_file = remote_file.replace('//', '/')
                with open(local_file, 'rb') as fp:
                    printf('Upload "{0}"\n', local_file)
                    printf('    to "ftp://{0}{1}" ...\n',
                           addr, remote_file, flush=True)
                    ftp.storbinary('STOR {0}'.format(remote_file), fp,
                                   32 * 1024, callback=lambda sent: print('.', end='', flush=True))
                    print('')
            print('Done.', flush=True)
        finally:
            ftp.quit()

    elif cmd == "winreg":
        try:
            value = None
            try:
                try:
                    import winreg
                except ImportError:
                    winreg = __import__("_winreg")
                root_keys = {
                    "HKEY_CLASSES_ROOT": winreg.HKEY_CLASSES_ROOT,
                    "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
                    "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
                    "HKEY_USERS": winreg.HKEY_USERS,
                    "HKEY_PERFORMANCE_DATA": winreg.HKEY_PERFORMANCE_DATA,
                    "HKEY_CURRENT_CONFIG": winreg.HKEY_CURRENT_CONFIG,
                }
                for arg in args:
                    keys = arg.split("\\")
                    # Read registry.
                    key = root_keys[keys[0]]
                    sub_key = "\\".join(keys[1:-1])
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
            printf("{0}", value or "")
        except (NameError, AttributeError):
            status = EFAIL
            return status

    elif cmd == "cargo-exec":
        import time
        import subprocess
        if len(args) < 1:
            printf("Invalid parameter {0} for cargo-exec\n",
                   args, file=sys.stderr)
            return EFAIL
        ws_dir = os.environ.get("CARGO_WORKSPACE_DIR", ".")
        cfg_file = args[0] if args[0].endswith(
            ".toml") else os.path.join(args[0], "Cargo.toml")
        cargo_toml = os.path.join(ws_dir, cfg_file) if os.path.isfile(
            os.path.join(ws_dir, cfg_file)) else cfg_file
        try:
            import toml
            cargo = toml.load(cargo_toml)
        except ImportError:
            try:
                tomllib = __import__("tomllib")
                with open(cargo_toml, mode="rb") as fp:
                    cargo = tomllib.load(fp)
            except ImportError:
                print("toml is not installed. Please execute: pip install toml\n",
                      cmd, file=sys.stderr)
                status = EFAIL
                return status
        package = cargo["package"]
        os.environ["CARGO_CRATE_NAME"] = package["name"]
        os.environ["CARGO_PKG_NAME"] = package["name"]
        os.environ["CARGO_PKG_VERSION"] = package["version"]
        os.environ["CARGO_MAKE_TIMESTAMP"] = "{0}".format(time.time())
        status = subprocess.call(" ".join(args[1:]), shell=True)

    else:
        printf("Unknown command {0}\n", cmd, file=sys.stderr)
        status = EINVAL
    return status


def main():
    try:
        from optparse import OptionParser
        parser = OptionParser(
            usage=("Usage: %prog [options] command <arguments>\n\n"))
        parser.get_option("-h").help = "Show this help message and exit."
        parser.add_option("-f", "--force",
                          action="store_true", default=False, dest="force",
                          help="ignore errors, never prompt")
        parser.add_option("-r", "-R", "--recursive",
                          action="store_true", default=False, dest="recursive",
                          help="copy/remove directories and their contents recursively")
        (options, args) = parser.parse_args()

        if not args:
            printf("Missing command\n", file=sys.stderr)
            return EINVAL

        return run_shell_command(args[0], options, args[1:])
    except KeyboardInterrupt:
        print("^C")
        return EINTERRUPT


if __name__ == "__main__":
    sys.exit(main())
