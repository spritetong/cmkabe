# -*- coding: utf-8 -*-
"""Parse build target triples and generate configuration files for Make/CMake."""

import glob
import os
import shutil
import subprocess
import sys
from typing import Any, Dict, Generator, List, Optional, Tuple

from cmk.pylib.sys_utils import (
    EXE_EXT,
    GCC_ENV_KEYS,
    HOST_ARCH_MAP,
    HOST_SYSTEM_MAP,
    RUST_ARCH_MAP,
    MSVC_ARCH_MAP,
    VSTOOLS_ARCH_MAP,
    ANDROID_ARCH_MAP,
    ANDROID_ABI_MAP,
    APPLE_ARCH_MAP,
    ZIG_ARCH_MAP,
    ZIG_OS_MAP,
    copy_env_for_cc,
    host_target_info,
    join_triple,
    lock_file,
    need_update,
    ndk_root,
    normpath,
    parse_triple,
)


class TargetParser:
    """Parse compilation target triples and create environment configuration files."""

    def __init__(
        self,
        workspace_dir: str = '',
        target: str = '',
        target_dir: str = '',
        target_cmake_dir: str = '',
        cmake_target_prefix: str = '',
        cargo_target: str = '',
        zig_target: str = '',
        target_cc: str = '',
        make_clean: str = '',
        **_args: Any,
    ) -> None:
        host_info = host_target_info()

        # Host properties
        self.host_system: str = host_info['host_system']
        self.host_system_ext: str = host_info['system']
        self.host_arch: str = host_info['arch']
        self.host_os: str = host_info['os']
        self.host_vendor: str = host_info['vendor']
        self.host_env: str = host_info['env']
        self.host_target: str = host_info['triple']
        self.host_cargo_target: str = host_info['cargo_triple']

        self.script_dir: str = normpath(
            os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        )

        # Paths
        self.workspace_dir: str = normpath(
            os.path.abspath(workspace_dir or os.path.join(self.script_dir, '..'))
        )
        self.target: str = target
        self.target_is_native: bool = False
        self.target_dir: str = normpath(
            os.path.abspath(target_dir or os.path.join(self.workspace_dir, 'target'))
        )
        self.target_cmake_dir: str = normpath(
            os.path.abspath(target_cmake_dir or (self.target_dir + '/.cmake'))
        )
        self.cmake_lock_file: str = normpath(
            os.path.join(self.target_cmake_dir, self.host_system, '.cmake.lock')
        )
        self.cmake_target_prefix: str = normpath(
            os.path.abspath(cmake_target_prefix or (self.workspace_dir + '/installed'))
        )
        self.cmake_prefix_dir: str = ''
        self.cmake_prefix_subdirs: List[str] = []
        self.cargo_target: str = cargo_target
        self.zig_target: str = zig_target
        self.target_cc: str = target_cc
        self.make_clean: bool = make_clean == 'ON'

        # Parsed triple
        self.arch: str = ''
        self.vendor: str = ''
        self.os: str = ''
        self.env: str = ''

        # Target indicators
        self.win32: bool = False
        self.msvc: bool = False
        self.android: bool = False
        self.unix: bool = False
        self.apple: bool = False
        self.ios: bool = False

        # Tools
        self.cargo_target_dir: str = ''
        self.cmake_generator: str = ''
        self.cmake_target_dir: str = ''

        self.msvc_arch: str = ''
        self.msvc_masm: str = ''

        self.android_ndk_root: str = ''
        self.android_ndk_bin: str = ''
        self.android_target: str = ''
        self.android_arch: str = ''
        self.android_abi: str = ''

        self.zig: bool = False
        self.zig_root: str = ''
        self.zig_cc_dir: str = ''

        self.c_includes: List[str] = []
        self.cxx_includes: List[str] = []

    @property
    def host_is_windows(self) -> bool:
        return self.host_system == 'Windows'

    @property
    def host_is_win_posix(self) -> bool:
        return self.host_system_ext in ['mingw', 'cygwin']

    @property
    def host_is_mingw(self) -> bool:
        return self.host_system_ext == 'mingw'

    @property
    def host_is_cygwin(self) -> bool:
        return self.host_system_ext == 'cygwin'

    @property
    def host_is_unix(self) -> bool:
        return self.host_system != 'Windows'

    @property
    def host_is_linux(self) -> bool:
        return self.host_system == 'Linux'

    @property
    def host_is_macos(self) -> bool:
        return self.host_system == 'Darwin'

    @property
    def target_is_runnable(self) -> bool:
        if self.target_is_native or self.cargo_target == self.host_cargo_target:
            return True
        if (
            not self.android
            and not self.ios
            and (self.host_os == self.os)
            and (
                self.host_arch == self.arch
                or (self.host_arch == 'x86_64' and self.arch in ['i586', 'i686'])
            )
            and (self.vendor in ['pc', 'apple', 'unknown'])
            and (self.env in ['msvc', 'gnu', 'musl', ''])
        ):
            return True
        return False

    @property
    def is_cross_compiling(self) -> bool:
        return self.cargo_target != self.host_cargo_target

    @property
    def target_cxx(self) -> str:
        stem, ext = os.path.splitext(os.path.basename(self.target_cc))
        if stem.endswith('clang'):
            cxx = stem[:-5] + 'clang++'
        elif stem.endswith('gcc'):
            cxx = stem[:-3] + 'g++'
        elif stem.endswith('cc'):
            cxx = stem[:-2] + 'c++'
        else:
            cxx = stem
        return self.target_cc[: -(len(stem) + len(ext))] + cxx + ext

    @property
    def cmkabe_target(self) -> str:
        """Get the cmkabe target string."""
        return 'native' if self.target_is_native else self.target

    def cargo_out_dir(self, make: bool = False, cmake: bool = False) -> str:
        """Get the cargo output binary directory path."""
        if self.cargo_target == self.host_cargo_target:
            directory = self.cargo_target_dir
        else:
            directory = '{}/{}'.format(self.cargo_target_dir, self.cargo_target)

        build_type = 'debug'
        if make:
            build_type = '$(CARGO_BUILD_TYPE)'
        elif cmake:
            build_type = '${CARGO_BUILD_TYPE}'
        return '{}/{}'.format(directory, build_type)

    def cmake_build_dir(self) -> str:
        """Get the cmake build directory path."""
        return '{}/$(CMAKE_BUILD_TYPE)'.format(self.cmake_target_dir)

    def enum_prefix_subdirs_of(
        self, subdir: str, quotes: bool = False, make: bool = False, cmake: bool = False
    ) -> List[str]:
        """Enumerate subdirectories in prefix install path."""
        res: List[str] = []
        if subdir in ['bin', 'lib']:
            if make:
                for directory in [
                    self.cargo_out_dir(make=True),
                    self.cmake_build_dir(),
                ]:
                    res.append('"{}"'.format(directory) if quotes else directory)
            elif cmake:
                for directory in [
                    self.cargo_out_dir(cmake=True),
                    '${CMAKE_BINARY_DIR}',
                ]:
                    res.append('"{}"'.format(directory) if quotes else directory)
        for directory in self.cmake_prefix_subdirs:
            item = '{}{}{}'.format(directory, '/' if subdir else '', subdir)
            res.append('"{}"'.format(item) if quotes else item)
        return res

    def parse(self) -> 'TargetParser':
        """Parse target parameters, setup compilers, and directories."""
        self.target_is_native = self.target in ('', 'native')
        if self.target_is_native:
            self.target = self.host_target

        self.arch, self.vendor, self.os, self.env = parse_triple(self.target)
        self.arch = RUST_ARCH_MAP.get(self.arch, self.arch)

        # Detect platform properties
        if self.os == 'windows':
            self.win32 = True
            if self.env == 'msvc':
                self.msvc = True
                self.msvc_arch = MSVC_ARCH_MAP[self.arch]
            self.cargo_target = self.cargo_target or join_triple(
                self.arch, 'pc', 'windows', self.env
            )
            zig_target = join_triple(
                ZIG_ARCH_MAP.get(self.arch, self.arch), '', 'windows', self.env
            )
        elif self.env.startswith('android'):
            self.android = True
            self.unix = True
            self.android_target = join_triple(
                ANDROID_ARCH_MAP[self.arch], '', 'linux', self.env
            )
            self.android_arch = ANDROID_ARCH_MAP[self.arch]
            self.android_abi = ANDROID_ABI_MAP[self.arch]
            self.cargo_target = self.cargo_target or join_triple(
                self.arch, '', 'linux', self.env
            )
            zig_target = join_triple(
                ZIG_ARCH_MAP.get(self.arch, self.arch), '', 'linux', self.env
            )
            self.cmake_generator = 'Ninja'
        elif self.os == 'linux':
            self.unix = True
            self.cargo_target = self.cargo_target or join_triple(
                self.arch, 'unknown', 'linux', self.env
            )
            zig_target = join_triple(
                ZIG_ARCH_MAP.get(self.arch, self.arch), '', 'linux', self.env
            )
        elif self.vendor == 'apple':
            self.apple = True
            self.unix = True
            self.ios = 'ios' in self.os
            self.cargo_target = self.cargo_target or join_triple(
                self.arch, 'apple', self.os, ''
            )
            zig_target = join_triple(
                ZIG_ARCH_MAP.get(self.arch, self.arch),
                '',
                ZIG_OS_MAP.get(self.os, self.os),
                'none',
            )
        else:
            self.unix = True
            self.cargo_target = self.cargo_target or join_triple(
                self.arch, self.vendor, self.os, self.env
            )
            zig_target = join_triple(
                ZIG_ARCH_MAP.get(self.arch, self.arch), '', self.os, self.env
            )

        # Cross compiler checks
        self.zig = os.path.splitext(os.path.basename(self.target_cc))[0] in (
            'zig',
            'zig-cc',
        )
        zig = shutil.which('zig' + EXE_EXT) if self.zig else None
        if (
            not self.target_is_native
            and not self.android
            and (zig is None)
            and (not self.target_cc or not shutil.which(self.target_cc))
            and self.is_cross_compiling
        ):
            target_cc = shutil.which(self.target + '-gcc' + EXE_EXT) or shutil.which(
                self.target + '-cc' + EXE_EXT
            )
            if target_cc:
                self.target_cc = normpath(target_cc)
                self.zig = False
            elif (
                self.vendor != self.host_vendor
                or self.os != self.host_os
                or self.env != self.host_env
            ) or (self.host_is_linux and self.os == 'linux'):
                if zig is None:
                    zig = shutil.which('zig' + EXE_EXT)
                if zig:
                    self.zig = True

        if self.zig and not self.zig_target:
            self.zig_target = zig_target

        if not self.cmake_generator and (
            self.host_is_unix or self.zig or self.target_cc
        ):
            if self.host_is_windows or shutil.which('ninja' + EXE_EXT):
                self.cmake_generator = 'Ninja'
            elif self.host_is_unix:
                self.cmake_generator = 'Unix Makefiles'

        if (
            self.target_is_native or self.cargo_target != self.host_cargo_target
        ) and self.target == self.cargo_target:
            self.cargo_target_dir = self.target_dir
        else:
            self.cargo_target_dir = '{}/{}'.format(self.target_dir, self.target)

        self.cmake_prefix_dir = '{}/{}'.format(self.cmake_target_prefix, self.target)

        def _any_prefix_subdirs() -> Generator[str, None, None]:
            yield self.target
            if self.target != self.cargo_target:
                yield self.cargo_target
            yield join_triple(self.arch, self.vendor, self.os, 'any')
            if self.vendor != '':
                yield join_triple('any', self.vendor, self.os, 'any')
            yield join_triple('any', '', self.os, 'any')
            yield 'any'

        self.cmake_prefix_subdirs = [
            '{}/{}'.format(self.cmake_target_prefix, x) for x in _any_prefix_subdirs()
        ]
        return self

    def _win32_init(self) -> None:
        vswhere = 'vswhere.exe'
        for program_files in [
            'ProgramW6432',
            'ProgramFiles(x86)',
            'ProgramFiles',
        ]:
            path = r'{}\Microsoft Visual Studio\Installer\vswhere.exe'.format(
                os.environ.get(program_files, '')
            )
            if os.path.isfile(path):
                vswhere = path
        try:
            result = subprocess.run(
                [
                    vswhere,
                    '-latest',
                    '-requires',
                    'Microsoft.VisualStudio.Component.VC.Tools.*',
                    '-find',
                    r'VC\Tools\MSVC\**\bin\*{}\{}\ml*.exe'.format(
                        VSTOOLS_ARCH_MAP.get(self.host_arch, self.host_arch),
                        VSTOOLS_ARCH_MAP.get(self.arch, self.arch),
                    ),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
            )
            ml = result.stdout.strip()
            if ml:
                self.msvc_masm = normpath(ml)
        except OSError:
            pass

    def _cmake_init(self) -> None:
        self.cmake_target_dir = '{}/{}/{}'.format(
            self.target_cmake_dir,
            self.host_system,
            'native' if self.target_is_native else self.target,
        )
        os.makedirs(self.cmake_target_dir, exist_ok=True)

    def _zig_init(self) -> None:
        # Zig root path and include directories.
        zig_path = shutil.which('zig' + EXE_EXT)
        if not zig_path:
            raise FileNotFoundError('`zig` is not found')
        self.zig_root = normpath(os.path.realpath(os.path.dirname(zig_path)))

        self.zig_cc_dir = normpath(
            os.path.join(self.target_dir, '.zig', self.host_system)
        )
        src = self.script_dir + '/zig-wrapper.zig'
        exe = self.zig_cc_dir + '/zig-wrapper' + EXE_EXT
        directory = self.zig_cc_dir

        os.makedirs(directory, exist_ok=True)
        if need_update(src, exe) and not self.make_clean:
            for file in glob.glob(os.path.join(directory, '*')):
                if not os.path.isdir(file):
                    os.unlink(file)
            # Compile wrapper using zig build-exe with quoted -femit-bin
            subprocess.run(
                [
                    'zig' + EXE_EXT,
                    'build-exe',
                    '-O',
                    'ReleaseSmall',
                    '-fstrip',
                    '-femit-bin={}'.format(exe),
                    src,
                ],
                env=copy_env_for_cc(),
                check=True,
            )
            os.chmod(exe, 0o755)
            for file in glob.glob(os.path.join(directory, exe + '.*')):
                os.unlink(file)
            for name in [
                'ar',
                'cc',
                'c++',
                'dlltool',
                'lib',
                'link',
                'ranlib',
                'objcopy',
                'rc',
                'windres',
            ]:
                dst = os.path.join(directory, 'zig-' + name + EXE_EXT)
                if os.path.lexists(dst):
                    os.unlink(dst)
                os.symlink(os.path.basename(exe), dst)
            for name in ['dlltool', 'windres']:
                dst = os.path.join(directory, name + EXE_EXT)
                if os.path.lexists(dst):
                    os.unlink(dst)
                os.symlink(os.path.basename(exe), dst)
            for name in ['elf_path_fixer.py']:
                dst = os.path.join(directory, name)
                if os.path.lexists(dst):
                    os.unlink(dst)
                os.symlink(
                    os.path.relpath(
                        os.path.join(self.script_dir, name), directory
                    ).replace('/', os.sep),
                    dst,
                )

        # Override the target CC for Zig.
        self.target_cc = normpath(self.zig_cc_dir + '/zig-cc' + EXE_EXT)

        # Get include paths.
        def cc_cmd_args(cc_tool: str) -> List[str]:
            return [cc_tool, '-target', self.zig_target]

        if not self.make_clean:
            self.c_includes = self._get_cc_includes(cc_cmd_args(self.target_cc), 'c')
            self.cxx_includes = self._get_cc_includes(
                cc_cmd_args(self.target_cxx), 'c++'
            )

    def _cc_init(self) -> None:
        if not os.path.isfile(self.target_cc):
            target_cc = shutil.which(self.target_cc)
            if not target_cc:
                raise FileNotFoundError(
                    'Target CC is not found: {}'.format(self.target_cc)
                )
            self.target_cc = normpath(target_cc)

        # Get include paths.
        self.c_includes = self._get_cc_includes([self.target_cc], 'c')
        self.cxx_includes = self._get_cc_includes([self.target_cxx], 'c++')

    def _android_init(self) -> None:
        self.android_ndk_root = normpath(ndk_root(check_env=True))
        self.android_ndk_bin = self.android_ndk_root + (
            '/toolchains/llvm/prebuilt/{}-{}/bin'.format(
                self.host_system.lower(), self.host_arch.lower()
            )
        )
        if not self.android_ndk_root or not os.path.isdir(self.android_ndk_root):
            raise FileNotFoundError(
                'Android NDK is not found: {}'.format(self.android_ndk_root)
            )
        if not self.android_ndk_bin or not os.path.isdir(self.android_ndk_bin):
            raise FileNotFoundError(
                'Android NDK Clang compiler is not found: {}'.format(
                    self.android_ndk_bin
                )
            )

        # Override the target CC for NDK.
        self.target_cc = '{}/clang{}'.format(self.android_ndk_bin, EXE_EXT)

        # Get include paths.
        def cc_cmd_args(cc_tool: str) -> List[str]:
            return [cc_tool, '--target={}'.format(self.android_target)]

        self.c_includes = self._get_cc_includes(cc_cmd_args(self.target_cc), 'c')
        self.cxx_includes = self._get_cc_includes(cc_cmd_args(self.target_cxx), 'c++')

    @classmethod
    def _get_cc_includes(cls, cmd_args: List[str], lang: str = 'c') -> List[str]:
        result = subprocess.run(
            cmd_args + ['-E', '-x', lang, '-', '-v'],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=copy_env_for_cc(),
        )
        start_marker = '#include <...> search starts here:'
        end_marker = 'End of search list.'
        output = result.stderr
        start = output.find(start_marker)
        end = output.find(end_marker, start)
        if start >= 0 and end >= 0:
            text = output[start + len(start_marker) : end]
            return [
                line
                for line in map(
                    lambda x: x.strip().replace(os.sep, '/'), text.splitlines()
                )
                if line
            ]
        return []

    def build(self) -> None:
        """Run build under locked cmake lock file."""
        file = lock_file(path=self.cmake_lock_file)
        try:
            self._build()
        finally:
            lock_file(unlock=file)

    def _build(self) -> None:
        if self.host_is_windows and self.win32:
            self._win32_init()
        if self.android:
            self._android_init()
        elif self.zig:
            self._zig_init()
        elif self.target_cc:
            self._cc_init()
        self._cmake_init()

        def fwrite(f_obj: Any, s: str) -> None:
            f_obj.write(s.encode('utf-8'))

        def onoff(b: bool) -> str:
            return 'ON' if b else 'OFF'

        def join_paths(
            paths: List[str], subdirs: Optional[List[str]] = None
        ) -> List[str]:
            return (
                ['/'.join([p, s]) for p in paths for s in subdirs] if subdirs else paths
            )

        def make_export_paths(
            name: str, paths: List[str], subdirs: Optional[List[str]] = None
        ) -> str:
            value = (
                os.pathsep + os.pathsep.join(join_paths(paths, subdirs)) + os.pathsep
            )
            export_only = False
            if name == 'PATH':
                value = '$(subst /,$(SEP),{})'.format(value)
                export_only = True
            return ''.join(
                [
                    '# Environment variable `{}`\n'.format(name),
                    '_s := {}\n'.format(value),
                    'ifeq ($(findstring $(_s),$({})),)\n'.format(name),
                    '    {} {} := $(_s)$({})\n'.format(
                        'export' if export_only else 'override', name, name
                    ),
                    '    export {}\n'.format(name) if not export_only else '',
                    'endif\n',
                ]
            )

        def cmake_export_paths(
            name: str, paths: List[str], subdirs: Optional[List[str]] = None
        ) -> str:
            env_name = 'ENV{{{}}}'.format(name)
            value = (
                os.pathsep + os.pathsep.join(join_paths(paths, subdirs)) + os.pathsep
            )
            return ''.join(
                [
                    '# Environment variable `{}`\n'.format(name),
                    'set(_s "{}")\n'.format(value),
                    'string(FIND "${}" "${{_s}}" _n)\n'.format(env_name),
                    'if(_n EQUAL -1)\n',
                    '    set({} "${{_s}}${}")\n'.format(env_name, env_name),
                    'endif()\n',
                ]
            )

        with open(
            os.path.join(self.target_cmake_dir, self.host_system, '.host.mk'),
            'wb',
        ) as f:
            fwrite(f, 'override HOST_SYSTEM = {}\n'.format(self.host_system))
            fwrite(f, 'override HOST_TARGET = {}\n'.format(self.host_target))
            fwrite(
                f,
                'override HOST_CARGO_TARGET = {}\n'.format(self.host_cargo_target),
            )
            fwrite(f, 'override HOST_ARCH = {}\n'.format(self.host_arch))
            fwrite(f, 'override HOST_VENDOR = {}\n'.format(self.host_vendor))
            fwrite(f, 'override HOST_OS = {}\n'.format(self.host_os))
            fwrite(f, 'override HOST_ENV = {}\n'.format(self.host_env))
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            fwrite(f, 'override HOST_SEP := $(strip {})\n'.format(os.sep))
            fwrite(f, 'override HOST_PATHSEP = {}\n'.format(os.pathsep))
            fwrite(f, 'override HOST_EXE_EXT = {}\n'.format(EXE_EXT))
            fwrite(f, '\n')
            fwrite(
                f,
                '# Unexport environment variables that may affect the CC compiler.\n',
            )
            for key in GCC_ENV_KEYS:
                fwrite(f, 'unexport {}\n'.format(key))

        with open(
            os.path.join(self.target_cmake_dir, self.host_system, '.host.cmake'),
            'wb',
        ) as f:
            fwrite(f, 'set(HOST_SYSTEM "{}")\n'.format(self.host_system))
            fwrite(f, 'set(HOST_TARGET "{}")\n'.format(self.host_target))
            fwrite(
                f,
                'set(HOST_CARGO_TARGET "{}")\n'.format(self.host_cargo_target),
            )
            fwrite(f, 'set(HOST_ARCH "{}")\n'.format(self.host_arch))
            fwrite(f, 'set(HOST_VENDOR "{}")\n'.format(self.host_vendor))
            fwrite(f, 'set(HOST_OS "{}")\n'.format(self.host_os))
            fwrite(f, 'set(HOST_ENV "{}")\n'.format(self.host_env))
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            fwrite(f, 'set(HOST_SEP "{}")\n'.format(os.sep.replace('\\', '\\\\')))
            fwrite(f, 'set(HOST_PATHSEP "{}")\n'.format(os.pathsep))
            fwrite(f, 'set(HOST_EXE_EXT "{}")\n'.format(EXE_EXT))

        with open(os.path.join(self.cmake_target_dir, '.settings.mk'), 'wb') as f:
            fwrite(f, '# Home directory\n')
            fwrite(f, 'override CMKABE_HOME = {}\n'.format(self.script_dir))
            fwrite(f, '\n')

            fwrite(f, '# Constants for the target platform\n')
            fwrite(
                f,
                'override TARGET_SEP := $(strip {})\n'.format(
                    '\\' if self.win32 else '/'
                ),
            )
            fwrite(
                f,
                'override TARGET_PATHSEP = {}\n'.format(';' if self.win32 else ':'),
            )
            fwrite(
                f,
                'override TARGET_EXE_EXT = {}\n'.format('.exe' if self.win32 else ''),
            )
            fwrite(f, '\n')

            fwrite(f, '# Build configuration\n')
            fwrite(f, 'ifeq ($(CMAKE_BUILD_TYPE),)\n')
            fwrite(f, '    $(error CMAKE_BUILD_TYPE is not set)\n')
            fwrite(f, 'endif\n')
            fwrite(f, 'ifeq ($(DEBUG),)\n')
            fwrite(f, '    $(error DEBUG is not set)\n')
            fwrite(f, 'endif\n')
            fwrite(
                f,
                'override CARGO_BUILD_TYPE := $(call bsel,$(DEBUG),debug,release)\n',
            )
            fwrite(f, '\n')

            fwrite(f, '# Constant directories\n')
            fwrite(f, 'override WORKSPACE_DIR = {}\n'.format(self.workspace_dir))
            fwrite(f, 'override TARGET_DIR = {}\n'.format(self.target_dir))
            fwrite(
                f,
                'override TARGET_CMAKE_DIR = {}\n'.format(self.target_cmake_dir),
            )
            fwrite(
                f,
                'override CMAKE_LOCK_FILE = {}\n'.format(self.cmake_lock_file),
            )
            fwrite(
                f,
                'override CMAKE_TARGET_PREFIX = {}\n'.format(self.cmake_target_prefix),
            )
            fwrite(
                f,
                'override CMAKE_PREFIX_DIR = {}\n'.format(self.cmake_prefix_dir),
            )
            fwrite(
                f,
                'override CMAKE_PREFIX_SUBDIRS = {}\n'.format(
                    ' '.join(self.enum_prefix_subdirs_of('', make=True))
                ),
            )
            fwrite(
                f,
                'override CMAKE_PREFIX_BINS := {}\n'.format(
                    ' '.join(self.enum_prefix_subdirs_of('bin', make=True))
                ),
            )
            fwrite(
                f,
                'override CMAKE_PREFIX_LIBS := {}\n'.format(
                    ' '.join(self.enum_prefix_subdirs_of('lib', make=True))
                ),
            )
            fwrite(
                f,
                'override CMAKE_PREFIX_INCLUDES = {}\n'.format(
                    ' '.join(self.enum_prefix_subdirs_of('include', make=True))
                ),
            )
            fwrite(f, '\n')

            fwrite(f, '# Cargo\n')
            fwrite(f, 'override TARGET = {}\n'.format(self.target))
            fwrite(f, 'override TARGET_ARCH = {}\n'.format(self.arch))
            fwrite(f, 'override TARGET_VENDOR = {}\n'.format(self.vendor))
            fwrite(f, 'override TARGET_OS = {}\n'.format(self.os))
            fwrite(f, 'override TARGET_ENV = {}\n'.format(self.env))
            fwrite(f, 'override TARGET_CC = {}\n'.format(self.target_cc))
            fwrite(f, 'override CARGO_TARGET = {}\n'.format(self.cargo_target))
            fwrite(
                f,
                'override CARGO_TARGET_UNDERSCORE = {}\n'.format(
                    self.cargo_target.replace('-', '_')
                ),
            )
            fwrite(
                f,
                'override CARGO_TARGET_UNDERSCORE_UPPER = {}\n'.format(
                    self.cargo_target.replace('-', '_').upper()
                ),
            )
            fwrite(
                f,
                'override CARGO_TARGET_DIR = {}\n'.format(self.cargo_target_dir),
            )
            fwrite(
                f,
                'override CARGO_OUT_DIR := {}\n'.format(self.cargo_out_dir(make=True)),
            )
            fwrite(f, '\n')

            fwrite(f, '# CMake\n')
            fwrite(
                f,
                'override CMAKE_GENERATOR = {}\n'.format(self.cmake_generator),
            )
            fwrite(
                f,
                'override CMAKE_TARGET_DIR = {}\n'.format(self.cmake_target_dir),
            )
            fwrite(
                f,
                'override CMAKE_BUILD_DIR = {}\n'.format(self.cmake_build_dir()),
            )
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, 'override MSVC_ARCH = {}\n'.format(self.msvc_arch))
            fwrite(f, 'override MSVC_MASM = {}\n'.format(self.msvc_masm))
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            fwrite(
                f,
                'override ANDROID_TARGET = {}{}\n'.format(
                    self.android_target,
                    '$(ANDROID_SDK_VERSION)' if self.android_target else '',
                ),
            )
            fwrite(f, 'override ANDROID_ARCH = {}\n'.format(self.android_arch))
            fwrite(f, 'override ANDROID_ABI = {}\n'.format(self.android_abi))
            if self.android_ndk_root:
                fwrite(
                    f,
                    'override ANDROID_NDK_ROOT = {}\n'.format(self.android_ndk_root),
                )
            if self.android_ndk_bin:
                fwrite(
                    f,
                    'override ANDROID_NDK_BIN = {}\n'.format(self.android_ndk_bin),
                )
            if self.android:
                fwrite(
                    f,
                    'override CMAKE_SYSTEM_VERSION = $(ANDROID_SDK_VERSION)\n',
                )
            fwrite(f, '\n')

            fwrite(f, '# Zig\n')
            fwrite(f, 'override ZIG = {}\n'.format(onoff(self.zig)))
            fwrite(f, 'override ZIG_TARGET = {}\n'.format(self.zig_target))
            fwrite(f, 'override ZIG_CC_DIR = {}\n'.format(self.zig_cc_dir))
            fwrite(f, 'override ZIG_ROOT = {}\n'.format(self.zig_root))
            fwrite(f, '\n')

            fwrite(f, '# Target related conditions\n')
            fwrite(
                f,
                'override TARGET_IS_NATIVE = {}\n'.format(onoff(self.target_is_native)),
            )
            fwrite(
                f,
                'override TARGET_IS_RUNNABLE = {}\n'.format(
                    onoff(self.target_is_runnable)
                ),
            )
            fwrite(f, 'override TARGET_IS_WIN32 = {}\n'.format(onoff(self.win32)))
            fwrite(f, 'override TARGET_IS_MSVC = {}\n'.format(onoff(self.msvc)))
            fwrite(
                f,
                'override TARGET_IS_ANDROID = {}\n'.format(onoff(self.android)),
            )
            fwrite(f, 'override TARGET_IS_UNIX = {}\n'.format(onoff(self.unix)))
            fwrite(f, 'override TARGET_IS_APPLE = {}\n'.format(onoff(self.apple)))
            fwrite(f, 'override TARGET_IS_IOS = {}\n'.format(onoff(self.ios)))

        with open(os.path.join(self.cmake_target_dir, '.settings.cmake'), 'wb') as f:
            fwrite(f, '# Home directory\n')
            fwrite(f, 'set(CMKABE_HOME "{}")\n'.format(self.script_dir))
            fwrite(f, '\n')

            fwrite(f, '# Constants for the target platform\n')
            fwrite(
                f,
                'set(TARGET_SEP "{}")\n'.format('\\\\' if self.win32 else '/'),
            )
            fwrite(
                f,
                'set(TARGET_PATHSEP "{}")\n'.format(';' if self.win32 else ':'),
            )
            fwrite(
                f,
                'set(TARGET_EXE_EXT "{}")\n'.format('.exe' if self.win32 else ''),
            )
            fwrite(f, '\n')

            fwrite(f, '# Build configuration\n')
            fwrite(f, 'if(NOT CMAKE_BUILD_TYPE)\n')
            fwrite(f, '    set(CMAKE_BUILD_TYPE "Release")\n')
            fwrite(f, 'endif()\n')
            fwrite(
                f,
                'string(TOLOWER "${CMAKE_BUILD_TYPE}" CMAKE_BUILD_TYPE_LOWER)\n',
            )
            fwrite(f, 'if(CMAKE_BUILD_TYPE_LOWER STREQUAL "debug")\n')
            fwrite(f, '    set(CARGO_BUILD_TYPE "debug")\n')
            fwrite(f, 'else()\n')
            fwrite(f, '    set(CARGO_BUILD_TYPE "release")\n')
            fwrite(f, 'endif()\n')
            fwrite(f, '\n')

            fwrite(f, '# Constant directories\n')
            fwrite(f, 'set(WORKSPACE_DIR "{}")\n'.format(self.workspace_dir))
            fwrite(f, 'set(TARGET_DIR "{}")\n'.format(self.target_dir))
            fwrite(f, 'set(TARGET_CMAKE_DIR "{}")\n'.format(self.target_cmake_dir))
            fwrite(f, 'set(TARGET_LOCK_FILE "{}")\n'.format(self.cmake_lock_file))
            fwrite(f, 'set(TARGET_PREFIX "{}")\n'.format(self.cmake_target_prefix))
            fwrite(f, 'set(TARGET_PREFIX_DIR "{}")\n'.format(self.cmake_prefix_dir))
            fwrite(
                f,
                'set(TARGET_PREFIX_SUBDIRS {})\n'.format(
                    ' '.join(self.enum_prefix_subdirs_of('', quotes=True, cmake=True))
                ),
            )
            fwrite(
                f,
                'set(TARGET_PREFIX_BINS {})\n'.format(
                    ' '.join(
                        self.enum_prefix_subdirs_of('bin', quotes=True, cmake=True)
                    )
                ),
            )
            fwrite(
                f,
                'set(TARGET_PREFIX_LIBS {})\n'.format(
                    ' '.join(
                        self.enum_prefix_subdirs_of('lib', quotes=True, cmake=True)
                    )
                ),
            )
            fwrite(
                f,
                'set(TARGET_PREFIX_INCLUDES {})\n'.format(
                    ' '.join(
                        self.enum_prefix_subdirs_of('include', quotes=True, cmake=True)
                    )
                ),
            )
            fwrite(f, '\n')

            fwrite(f, '# Cargo\n')
            fwrite(f, 'set(TARGET "{}")\n'.format(self.target))
            fwrite(f, 'set(TARGET_ARCH "{}")\n'.format(self.arch))
            fwrite(f, 'set(TARGET_VENDOR "{}")\n'.format(self.vendor))
            fwrite(f, 'set(TARGET_OS "{}")\n'.format(self.os))
            fwrite(f, 'set(TARGET_ENV "{}")\n'.format(self.env))
            fwrite(f, 'set(TARGET_CC "{}")\n'.format(self.target_cc))
            fwrite(f, 'set(CARGO_TARGET "{}")\n'.format(self.cargo_target))
            fwrite(
                f,
                'set(CARGO_TARGET_UNDERSCORE "{}")\n'.format(
                    self.cargo_target.replace('-', '_')
                ),
            )
            fwrite(
                f,
                'set(CARGO_TARGET_UNDERSCORE_UPPER "{}")\n'.format(
                    self.cargo_target.replace('-', '_').upper()
                ),
            )
            fwrite(f, 'set(CARGO_TARGET_DIR "{}")\n'.format(self.cargo_target_dir))
            fwrite(
                f,
                'set(CARGO_OUT_DIR "{}")\n'.format(self.cargo_out_dir(cmake=True)),
            )
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, 'set(MSVC_ARCH "{}")\n'.format(self.msvc_arch))
            fwrite(f, 'set(MSVC_MASM "{}")\n'.format(self.msvc_masm))
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            fwrite(
                f,
                'set(ANDROID_TARGET "{}{}")\n'.format(
                    self.android_target,
                    '${ANDROID_SDK_VERSION}' if self.android_target else '',
                ),
            )
            fwrite(f, 'set(ANDROID_ARCH "{}")\n'.format(self.android_arch))
            fwrite(f, 'set(ANDROID_ABI "{}")\n'.format(self.android_abi))
            if self.android_ndk_root:
                fwrite(
                    f,
                    'set(ANDROID_NDK_ROOT "{}")\n'.format(self.android_ndk_root),
                )
            if self.android_ndk_bin:
                fwrite(
                    f,
                    'set(ANDROID_NDK_BIN "{}")\n'.format(self.android_ndk_bin),
                )
            if self.android:
                fwrite(
                    f,
                    'set(CMAKE_SYSTEM_VERSION "${ANDROID_SDK_VERSION}")\n',
                )
            fwrite(f, '\n')

            fwrite(f, '# Zig\n')
            fwrite(f, 'set(ZIG {})\n'.format(onoff(self.zig)))
            fwrite(f, 'set(ZIG_TARGET "{}")\n'.format(self.zig_target))
            fwrite(f, 'set(ZIG_CC_DIR "{}")\n'.format(self.zig_cc_dir))
            fwrite(f, 'set(ZIG_ROOT "{}")\n'.format(self.zig_root))
            fwrite(f, '\n')

            fwrite(f, '# Target related conditions\n')
            fwrite(
                f,
                'set(TARGET_IS_NATIVE {})\n'.format(onoff(self.target_is_native)),
            )
            fwrite(
                f,
                'set(TARGET_IS_RUNNABLE {})\n'.format(onoff(self.target_is_runnable)),
            )
            fwrite(f, 'set(TARGET_IS_WIN32 {})\n'.format(onoff(self.win32)))
            fwrite(f, 'set(TARGET_IS_MSVC {})\n'.format(onoff(self.msvc)))
            fwrite(f, 'set(TARGET_IS_ANDROID {})\n'.format(onoff(self.android)))
            fwrite(f, 'set(TARGET_IS_UNIX {})\n'.format(onoff(self.unix)))
            fwrite(f, 'set(TARGET_IS_APPLE {})\n'.format(onoff(self.apple)))
            fwrite(f, 'set(TARGET_IS_IOS {})\n'.format(onoff(self.ios)))
            fwrite(f, '\n')
            fwrite(f, '# Suppress warnings\n')
            fwrite(f, 'set(ignoreMe "${CMAKE_VERBOSE_MAKEFILE}")\n')

        cc_exports: List[str] = []
        cc_options: List[str] = []
        linker_options: List[str] = []
        linker, ar, cc, cxx, ranlib, strip, rc = '', '', '', '', '', '', ''
        if self.android:
            cc_exports.append('ANDROID_NDK_ROOT = {}'.format(self.android_ndk_root))
            cc_options.append(
                '--target={}$(ANDROID_SDK_VERSION)'.format(self.android_target)
            )
            linker_options.extend(map(lambda x: '-C link-arg=' + x, cc_options))
            linker = '{}/clang++{}'.format(self.android_ndk_bin, EXE_EXT)
            ar = '{}/llvm-ar{}'.format(self.android_ndk_bin, EXE_EXT)
            cc = '{}/clang{}'.format(self.android_ndk_bin, EXE_EXT)
            cxx = '{}/clang++{}'.format(self.android_ndk_bin, EXE_EXT)
            ranlib = '{}/llvm-ranlib{}'.format(self.android_ndk_bin, EXE_EXT)
            strip = '{}/llvm-strip{}'.format(self.android_ndk_bin, EXE_EXT)
        elif self.zig:
            cc_exports.append('ZIG_WRAPPER_TARGET = {}'.format(self.zig_target))
            cc_exports.append('ZIG_WRAPPER_CLANG_TARGET = {}'.format(self.cargo_target))
            cc_options.append('--disable-dllexport')
            if (
                (self.os == 'windows' and self.env == 'gnu')
                or (self.os == 'linux' and self.env == 'musl')
                or self.os.startswith('wasi')
            ):
                linker_options.append('-C linker-flavor=gcc')
                linker_options.append('-C link-self-contained=no')
            linker = '{}/zig-c++{}'.format(self.zig_cc_dir, EXE_EXT)
            ar = '{}/zig-ar{}'.format(self.zig_cc_dir, EXE_EXT)
            cc = '{}/zig-cc{}'.format(self.zig_cc_dir, EXE_EXT)
            cxx = '{}/zig-c++{}'.format(self.zig_cc_dir, EXE_EXT)
            ranlib = '{}/zig-ranlib{}'.format(self.zig_cc_dir, EXE_EXT)
            strip = '{}/zig-strip{}'.format(self.zig_cc_dir, EXE_EXT)
            rc = '{}/zig-rc{}'.format(self.zig_cc_dir, EXE_EXT)
        elif self.target_cc:
            target_cc_noext, cc_ext = os.path.splitext(self.target_cc)
            target_cc_abs = normpath(os.path.abspath(target_cc_noext))
            if self.host_is_windows:
                cc_ext = cc_ext.lower()
            if target_cc_abs.endswith('-gcc'):
                cc_prefix = target_cc_abs[:-4]
                cxx = cc_prefix + '-g++' + cc_ext
            elif target_cc_abs.endswith('-cc'):
                cc_prefix = target_cc_abs[:-3]
                cxx = cc_prefix + '-c++' + cc_ext
            else:
                raise ValueError('Unrecognized target CC: {}'.format(self.target_cc))
            linker = target_cc_abs + cc_ext
            cc = target_cc_abs + cc_ext
            ar = cc_prefix + '-ar' + cc_ext
            ranlib = cc_prefix + '-ranlib' + cc_ext
            strip = cc_prefix + '-strip' + cc_ext

        with open(os.path.join(self.cmake_target_dir, '.environ.mk'), 'wb') as f:
            if cc_exports:
                for line in cc_exports:
                    k, v = list(map(lambda x: x.strip(), line.split('=', 1)))
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
            fwrite(
                f,
                'override {}_RUSTFLAGS := {} $(TARGET_RUSTFLAGS)\n'.format(
                    cargo_target, ' '.join(linker_options)
                ),
            )
            fwrite(f, 'export {}_RUSTFLAGS\n'.format(cargo_target))
            fwrite(f, '\n')

            cargo_target_under = self.cargo_target.replace('-', '_')
            if cc:
                fwrite(f, '# AR, CC, CXX, RANLIB, STRIP\n')
                fwrite(f, 'export AR_{} = {}\n'.format(cargo_target_under, ar))
                fwrite(f, 'export CC_{} = {}\n'.format(cargo_target_under, cc))
                fwrite(f, 'export CXX_{} = {}\n'.format(cargo_target_under, cxx))
                fwrite(
                    f,
                    'export RANLIB_{} = {}\n'.format(cargo_target_under, ranlib),
                )
                fwrite(f, 'export STRIP_{} = {}\n'.format(cargo_target_under, strip))
                fwrite(f, '\n')
            fwrite(f, '# ARFLAGS, CFLAGS, CXXFLAGS, RANLIBFLAGS\n')
            fwrite(
                f,
                'override ARFLAGS_{} := $(TARGET_ARFLAGS)\n'.format(cargo_target_under),
            )
            fwrite(f, 'export ARFLAGS_{}\n'.format(cargo_target_under))
            fwrite(
                f,
                'override CFLAGS_{} := {} $(TARGET_CFLAGS)\n'.format(
                    cargo_target_under, ' '.join(cc_options)
                ),
            )
            fwrite(f, 'export CFLAGS_{}\n'.format(cargo_target_under))
            fwrite(
                f,
                'override CXXFLAGS_{} := {} $(TARGET_CXXFLAGS)\n'.format(
                    cargo_target_under, ' '.join(cc_options)
                ),
            )
            fwrite(f, 'export CXXFLAGS_{}\n'.format(cargo_target_under))
            fwrite(
                f,
                'override RANLIBFLAGS_{} := $(TARGET_RANLIBFLAGS)\n'.format(
                    cargo_target_under
                ),
            )
            fwrite(f, 'export RANLIBFLAGS_{}\n'.format(cargo_target_under))
            fwrite(f, '\n')

            fwrite(f, '# For Rust bingen + libclang\n')
            bindgen_includes = (
                self.enum_prefix_subdirs_of('include', make=True) + self.cxx_includes
            )
            fwrite(
                f,
                'override BINDGEN_EXTRA_CLANG_ARGS := $(TARGET_BINDGEN_CLANG_ARGS) {} {}\n'.format(
                    '-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST'
                    + (
                        ''
                        if self.apple
                        else ' -D_LIBCPP_HAS_NO_VENDOR_AVAILABILITY_ANNOTATIONS=1'
                    ),
                    ' '.join(map(lambda x: '-I"{}"'.format(x), bindgen_includes)),
                ),
            )
            fwrite(f, 'export BINDGEN_EXTRA_CLANG_ARGS\n')
            fwrite(f, '\n')

            fwrite(f, '# For Rust cmake\n')
            fwrite(
                f,
                'export CMAKE_TOOLCHAIN_FILE_{} = {}/.toolchain.cmake\n'.format(
                    cargo_target_under, self.cmake_target_dir
                ),
            )
            if self.cmake_generator:
                fwrite(
                    f,
                    'export CMAKE_GENERATOR_{} = {}\n'.format(
                        cargo_target_under, self.cmake_generator
                    ),
                )
            else:
                fwrite(
                    f,
                    'unexport CMAKE_GENERATOR_{}\n'.format(cargo_target_under),
                )
            fwrite(f, '\n')

            fwrite(f, '# Configure the cross compile pkg-config.\n')
            fwrite(
                f,
                'export PKG_CONFIG_ALLOW_CROSS = {}\n'.format(
                    1 if self.is_cross_compiling else 0
                ),
            )
            fwrite(
                f,
                make_export_paths(
                    'PKG_CONFIG_PATH_' + cargo_target_under,
                    self.enum_prefix_subdirs_of('lib/pkgconfig', make=True),
                    [],
                ),
            )
            fwrite(f, '\n')

            fwrite(f, '# Set system paths.\n')
            if self.target_is_runnable:
                fwrite(
                    f,
                    make_export_paths(
                        'PATH',
                        [self.zig_cc_dir]
                        + self.enum_prefix_subdirs_of('bin', make=True),
                        [],
                    ),
                )
                if not self.host_is_windows:
                    fwrite(
                        f,
                        make_export_paths(
                            'LD_LIBRARY_PATH',
                            self.enum_prefix_subdirs_of('lib', make=True),
                            [],
                        ),
                    )
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
            fwrite(
                f,
                'export CARGO_WORKSPACE_DIR = {}\n'.format(self.workspace_dir),
            )
            fwrite(f, 'export CMKABE_HOST_TARGET = {}\n'.format(self.host_target))
            fwrite(f, 'export CMKABE_TARGET = {}\n'.format(self.cmkabe_target))
            fwrite(f, 'export CMKABE_TARGET_DIR = {}\n'.format(self.target_dir))
            fwrite(
                f,
                'export CMKABE_TARGET_CMAKE_DIR = {}\n'.format(self.target_cmake_dir),
            )
            fwrite(
                f,
                'export CMKABE_TARGET_PREFIX = {}\n'.format(self.cmake_target_prefix),
            )
            fwrite(f, 'export CMKABE_TARGET_CC = {}\n'.format(self.target_cc))
            fwrite(
                f,
                'export CMKABE_CARGO_TARGET = {}\n'.format(self.cargo_target),
            )
            fwrite(f, 'export CMKABE_ZIG_TARGET = {}\n'.format(self.zig_target))
            fwrite(f, 'export CMKABE_DEBUG := $(DEBUG)\n')
            fwrite(f, 'export CMKABE_MINSIZE := $(MINSIZE)\n')
            fwrite(f, 'export CMKABE_DBGINFO := $(DBGINFO)\n')
            fwrite(f, 'export CMKABE_CMAKE_BUILD_TYPE := $(CMAKE_BUILD_TYPE)\n')
            fwrite(f, 'export CMKABE_CMAKE_BUILD_DIR := $(CMAKE_BUILD_DIR)\n')
            fwrite(
                f,
                'export CMKABE_CARGO_OUT_DIR := {}\n'.format(
                    self.cargo_out_dir(make=True)
                ),
            )
            fwrite(
                f,
                'export CMKABE_MAKE_BUILD_VARS = {}\n'.format(
                    ';'.join(_make_build_vars)
                ),
            )
            fwrite(
                f,
                'export CMKABE_LINK_DIRS := {}\n'.format(
                    os.path.pathsep.join(self.enum_prefix_subdirs_of('lib', make=True))
                ),
            )
            fwrite(
                f,
                'export CMKABE_INCLUDE_DIRS = {}\n'.format(
                    os.path.pathsep.join(
                        self.enum_prefix_subdirs_of('include', make=True)
                    )
                ),
            )

        with open(os.path.join(self.cmake_target_dir, '.environ.cmake'), 'wb') as f:
            if cc_exports:
                for line in cc_exports:
                    k, v = list(map(lambda x: x.strip(), line.split('=', 1)))
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
            fwrite(
                f,
                'set(ENV{{PKG_CONFIG_ALLOW_CROSS}} "{}")\n'.format(
                    1 if self.is_cross_compiling else 0
                ),
            )
            fwrite(
                f,
                cmake_export_paths(
                    'PKG_CONFIG_PATH',
                    self.enum_prefix_subdirs_of('lib/pkgconfig', cmake=True),
                    [],
                ),
            )
            fwrite(f, '\n')

            fwrite(f, '# Export variables for Cargo build.rs and CMake\n')
            fwrite(
                f,
                'set(ENV{{CARGO_WORKSPACE_DIR}} "{}")\n'.format(self.workspace_dir),
            )
            fwrite(
                f,
                'set(ENV{{CMKABE_HOST_TARGET}} "{}")\n'.format(self.host_target),
            )
            fwrite(f, 'set(ENV{{CMKABE_TARGET}} "{}")\n'.format(self.cmkabe_target))
            fwrite(f, 'set(ENV{{CMKABE_TARGET_DIR}} "{}")\n'.format(self.target_dir))
            fwrite(
                f,
                'set(ENV{{CMKABE_TARGET_CMAKE_DIR}} "{}")\n'.format(
                    self.target_cmake_dir
                ),
            )
            fwrite(
                f,
                'set(ENV{{CMKABE_TARGET_PREFIX}} "{}")\n'.format(
                    self.cmake_target_prefix
                ),
            )
            fwrite(f, 'set(ENV{{CMKABE_TARGET_CC}} "{}")\n'.format(self.target_cc))
            fwrite(
                f,
                'set(ENV{{CMKABE_CARGO_TARGET}} "{}")\n'.format(self.cargo_target),
            )
            fwrite(f, 'set(ENV{{CMKABE_ZIG_TARGET}} "{}")\n'.format(self.zig_target))
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
                f,
                'set(ENV{CMKABE_CMAKE_BUILD_TYPE} "${CMAKE_BUILD_TYPE}")\n',
            )
            fwrite(
                f,
                'set(ENV{CMKABE_CMAKE_BUILD_DIR} "${CMAKE_BINARY_DIR}")\n',
            )
            fwrite(
                f,
                'set(ENV{{CMKABE_CARGO_OUT_DIR}} "{}")\n'.format(
                    self.cargo_out_dir(cmake=True)
                ),
            )
            fwrite(
                f,
                'set(ENV{{CMKABE_MAKE_BUILD_VARS}} "{}")\n'.format(
                    ';'.join(_make_build_vars)
                ),
            )
            fwrite(
                f,
                'set(ENV{{CMKABE_LINK_DIRS}} "{}")\n'.format(
                    os.path.pathsep.join(self.enum_prefix_subdirs_of('lib', cmake=True))
                ),
            )
            fwrite(
                f,
                'set(ENV{{CMKABE_INCLUDE_DIRS}} "{}")\n'.format(
                    os.path.pathsep.join(
                        self.enum_prefix_subdirs_of('include', cmake=True)
                    )
                ),
            )

        with open(os.path.join(self.cmake_target_dir, '.toolchain.cmake'), 'wb') as f:
            fwrite(f, 'cmake_minimum_required(VERSION 3.16)\n')
            fwrite(f, '\n')
            fwrite(
                f,
                'include("{}/.settings.cmake")\n'.format(self.cmake_target_dir),
            )
            fwrite(f, 'set(TARGET "{}")\n'.format(self.cmkabe_target))
            fwrite(f, 'set(ZIG_CC_DISABLE_DLLEXPORT ON)\n')
            fwrite(f, '\n')
            fwrite(f, 'set(TARGET "${TARGET}" CACHE STRING "" FORCE)\n')
            fwrite(f, 'set(TARGET_DIR "${TARGET_DIR}" CACHE STRING "" FORCE)\n')
            fwrite(
                f,
                'set(TARGET_CMAKE_DIR "${TARGET_CMAKE_DIR}" CACHE STRING "" FORCE)\n',
            )
            fwrite(f, '\n')
            fwrite(f, 'include("${CMKABE_HOME}/cmake/toolchain.cmake")\n')
            fwrite(f, '_cmkabe_apply_extra_flags()\n')

        return self
