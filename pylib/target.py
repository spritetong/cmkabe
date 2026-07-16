# -*- coding: utf-8 -*-
# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe

"""Parse build target triples and generate configuration files for Make/CMake."""

import os
import shutil
import subprocess
import sys
from typing import Generator, List, Optional

from .sys_utils import (
    ANDROID_ABI_MAP,
    ANDROID_ARCH_MAP,
    EXE_EXT,
    GCC_ENV_KEYS,
    MSVC_ARCH_MAP,
    RUST_ARCH_MAP,
    VSTOOLS_ARCH_MAP,
    ZIG_ARCH_MAP,
    ZIG_OS_MAP,
    HostTargetInfo,
    cmkabe_home,
    copy_env_for_cc,
    join_triple,
    lock_file,
    ndk_root,
    normpath,
    parse_triple,
)


class TargetParser:
    """Parse compilation target triples and create environment configuration files."""

    def __init__(
        self,
        *,
        workspace_dir: str = '',
        target: str = '',
        target_dir: str = '',
        target_cmake_dir: str = '',
        target_dependency_prefixes: str = '',
        target_cc: str = '',
        cargo_target: str = '',
        zig_target: str = '',
        #
        debug: str = 'OFF',  # unused
        minsize: str = 'OFF',  # unused
        dbginfo: str = 'OFF',  # unused
    ) -> None:
        self.host: HostTargetInfo = HostTargetInfo.host()
        self.cmkabe_dir: str = normpath(cmkabe_home())

        # Paths
        self.workspace_dir: str = normpath(
            os.path.abspath(workspace_dir or os.path.join(self.cmkabe_dir, '..'))
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
            os.path.join(self.target_cmake_dir, self.host.host_system, '.cmake.lock')
        )
        self.target_dependency_prefixes: List[str] = [
            normpath(os.path.abspath(p.strip()))
            for p in (target_dependency_prefixes or '').split(os.pathsep)
            if p.strip()
        ]

        self.cargo_target: str = cargo_target
        self.zig_target: str = zig_target
        self.target_cc: str = target_cc
        self.target_prefix_subdirs: List[str] = []

        # Parsed triple
        self.arch: str = ''
        self.vendor: str = ''
        self.os: str = ''
        self.env: str = ''
        self.version: str = ''
        self.version_sep: str = ''

        # Target indicators
        self.win32: bool = False
        self.msvc: bool = False
        self.android: bool = False
        self.unix: bool = False
        self.apple: bool = False
        self.ios: bool = False
        self.wasm: bool = False

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
        return self.host.host_system == 'Windows'

    @property
    def host_is_win_posix(self) -> bool:
        return self.host.system in ['mingw', 'cygwin']

    @property
    def host_is_mingw(self) -> bool:
        return self.host.system == 'mingw'

    @property
    def host_is_cygwin(self) -> bool:
        return self.host.system == 'cygwin'

    @property
    def host_is_unix(self) -> bool:
        return self.host.host_system != 'Windows'

    @property
    def host_is_linux(self) -> bool:
        return self.host.host_system == 'Linux'

    @property
    def host_is_macos(self) -> bool:
        return self.host.host_system == 'Darwin'

    @property
    def target_is_runnable(self) -> bool:
        if self.target_is_native or self.cargo_target == self.host.cargo_triple:
            return True
        if (
            not self.android
            and not self.ios
            and (self.host.os == self.os)
            and (
                self.host.arch == self.arch
                or (self.host.arch == 'x86_64' and self.arch in ['i586', 'i686'])
            )
            and (self.vendor in ['pc', 'apple', 'unknown'])
            and (self.env in ['msvc', 'gnu', 'musl', ''])
        ):
            return True
        return False

    @property
    def is_cross_compiling(self) -> bool:
        return self.cargo_target != self.host.cargo_triple

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
        if self.cargo_target == self.host.cargo_triple:
            directory = self.cargo_target_dir
        else:
            directory = f'{self.cargo_target_dir}/{self.cargo_target}'

        build_type = 'debug'
        if make:
            build_type = '$(CARGO_BUILD_TYPE)'
        elif cmake:
            build_type = '${CARGO_BUILD_TYPE}'
        return f'{directory}/{build_type}'

    def cmake_build_dir(self) -> str:
        """Get the cmake build directory path."""
        return f'{self.cmake_target_dir}/$(CMAKE_BUILD_TYPE)'

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
                    res.append(f'"{directory}"' if quotes else directory)
            elif cmake:
                for directory in [
                    self.cargo_out_dir(cmake=True),
                    '${CMAKE_BINARY_DIR}',
                ]:
                    res.append(f'"{directory}"' if quotes else directory)
        for directory in self.target_prefix_subdirs:
            item = f'{directory}{"/" if subdir else ""}{subdir}'
            if os.path.isdir(item):
                res.append(f'"{item}"' if quotes else item)
        return res

    def parse(self) -> 'TargetParser':
        """Parse target parameters, setup compilers, and directories."""
        self.target_is_native = self.target in ('', 'native')
        if self.target_is_native:
            self.target = self.host.triple

        self.arch, self.vendor, self.os, self.env, self.version, self.version_sep = (
            parse_triple(self.target)
        )
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
        elif self.arch in ('wasm32', 'wasm64') or self.os.startswith('wasi'):
            self.wasm = True
            self.cargo_target = self.cargo_target or join_triple(
                self.arch, self.vendor, self.os, self.env
            )
            zig_os = ZIG_OS_MAP.get(self.os, self.os)
            zig_target = f'{ZIG_ARCH_MAP.get(self.arch, self.arch)}-{zig_os}'
        else:
            self.unix = True
            self.cargo_target = self.cargo_target or join_triple(
                self.arch, self.vendor, self.os, self.env
            )
            zig_target = join_triple(
                ZIG_ARCH_MAP.get(self.arch, self.arch), '', self.os, self.env
            )

        if self.version:
            zig_target += f'.{self.version}'

        # Cross compiler checks
        self.zig = os.path.splitext(os.path.basename(self.target_cc))[0] in (
            'zig',
            'zig-cc',
        )
        zig = shutil.which(f'zig{EXE_EXT}') if self.zig else None
        if (
            not self.target_is_native
            and not self.android
            and (zig is None)
            and (not self.target_cc or not shutil.which(self.target_cc))
            and self.is_cross_compiling
        ):
            target_cc = shutil.which(f'{self.target}-gcc{EXE_EXT}') or shutil.which(
                f'{self.target}-cc{EXE_EXT}'
            )
            if target_cc:
                self.target_cc = normpath(target_cc)
                self.zig = False
            elif (
                self.vendor != self.host.vendor
                or self.os != self.host.os
                or self.env != self.host.env
            ) or (self.host_is_linux and self.os == 'linux'):
                if zig is None:
                    zig = shutil.which(f'zig{EXE_EXT}')
                if zig:
                    self.zig = True

        if not self.zig_target:
            self.zig_target = zig_target

        if not self.cmake_generator and (
            self.host_is_unix or self.zig or self.target_cc
        ):
            if self.host_is_windows or shutil.which(f'ninja{EXE_EXT}'):
                self.cmake_generator = 'Ninja'
            elif self.host_is_unix:
                self.cmake_generator = 'Unix Makefiles'

        if (
            self.target_is_native or self.cargo_target != self.host.cargo_triple
        ) and self.target == self.cargo_target:
            self.cargo_target_dir = self.target_dir
        else:
            self.cargo_target_dir = f'{self.target_dir}/{self.target}'

        def _any_prefix_subdirs(prefixes: List[str]) -> Generator[str, None, None]:
            for prefix in prefixes:
                yield f'{prefix}/{self.target}'
            if self.target != self.cargo_target:
                for prefix in prefixes:
                    yield f'{prefix}/{self.cargo_target}'
            for vendor in [self.vendor, 'unknown', 'any', '']:
                for prefix in prefixes:
                    yield f'{prefix}/{join_triple(self.arch, vendor, self.os, "any")}'
            if self.vendor != '':
                for prefix in prefixes:
                    yield f'{prefix}/{join_triple("any", self.vendor, self.os, "any")}'
            for prefix in prefixes:
                yield f'{prefix}/{join_triple("any", "", self.os, "any")}'
            for prefix in prefixes:
                yield f'{prefix}/any'

        self.target_prefix_subdirs = list(
            dict.fromkeys(
                normpath(dir)
                for dir in _any_prefix_subdirs(self.target_dependency_prefixes)
                if os.path.isdir(dir)
            )
        )
        return self

    def _win32_init(self) -> None:
        vswhere = 'vswhere.exe'
        for program_files in [
            'ProgramW6432',
            'ProgramFiles(x86)',
            'ProgramFiles',
        ]:
            path = rf'{os.environ.get(program_files, "")}\Microsoft Visual Studio\Installer\vswhere.exe'
            if os.path.isfile(path):
                vswhere = path

        if self.arch == 'aarch64':
            masm_pattern = 'armasm64.exe'
        elif self.arch in ('arm', 'armv7'):
            masm_pattern = 'armasm.exe'
        else:
            masm_pattern = 'ml*.exe'

        host_arch = VSTOOLS_ARCH_MAP.get(self.host.arch, self.host.arch)
        target_arch = VSTOOLS_ARCH_MAP.get(self.arch, self.arch)

        try:
            result = subprocess.run(
                [
                    vswhere,
                    '-latest',
                    '-requires',
                    'Microsoft.VisualStudio.Component.VC.Tools.*',
                    '-find',
                    f'VC/Tools/MSVC/**/bin/*{host_arch}/{target_arch}/{masm_pattern}',
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
            )
            lines = [
                line.strip() for line in result.stdout.splitlines() if line.strip()
            ]
            if lines:
                self.msvc_masm = normpath(sorted(lines)[-1])
        except OSError:
            pass

    def _cmake_init(self) -> None:
        self.cmake_target_dir = (
            f'{self.target_cmake_dir}/{self.host.host_system}/{self.cmkabe_target}'
        )
        os.makedirs(self.cmake_target_dir, exist_ok=True)

    def _zig_init(self, *, probe_only: bool = False) -> None:
        from .zig import zig_build_wrapper

        # Zig root path and include directories.
        zig_path = shutil.which(f'zig{EXE_EXT}')
        if zig_path:
            self.zig_root = normpath(os.path.realpath(os.path.dirname(zig_path)))
        elif not probe_only:
            raise FileNotFoundError('`zig` is not found')

        self.zig_cc_dir = normpath(
            os.path.join(self.target_dir, '.zig', self.host.host_system)
        )
        if probe_only:
            return

        zig_build_wrapper(zig_root=self.zig_root, out_dir=self.zig_cc_dir)

        # Override the target CC for Zig.
        self.target_cc = normpath(f'{self.zig_cc_dir}/zig-cc{EXE_EXT}')

        # Get include paths.
        def cc_cmd_args(cc_tool: str) -> List[str]:
            return [cc_tool, '-target', self.zig_target]

        self.c_includes = self._get_cc_includes(cc_cmd_args(self.target_cc), 'c')
        self.cxx_includes = self._get_cc_includes(cc_cmd_args(self.target_cxx), 'c++')

    def _cc_init(self) -> None:
        if not os.path.isfile(self.target_cc):
            target_cc = shutil.which(self.target_cc)
            if not target_cc:
                raise FileNotFoundError(f'Target CC is not found: {self.target_cc}')
            self.target_cc = normpath(target_cc)

        # Get include paths.
        self.c_includes = self._get_cc_includes([self.target_cc], 'c')
        self.cxx_includes = self._get_cc_includes([self.target_cxx], 'c++')

    def _android_init(self) -> None:
        self.android_ndk_root = normpath(ndk_root(check_env=True))
        self.android_ndk_bin = self.android_ndk_root + (
            f'/toolchains/llvm/prebuilt/{self.host.host_system.lower()}-{self.host.arch.lower()}/bin'
        )
        if not self.android_ndk_root or not os.path.isdir(self.android_ndk_root):
            raise FileNotFoundError(
                f'Android NDK is not found: {self.android_ndk_root}'
            )
        if not self.android_ndk_bin or not os.path.isdir(self.android_ndk_bin):
            raise FileNotFoundError(
                f'Android NDK Clang compiler is not found: {self.android_ndk_bin}'
            )

        # Override the target CC for NDK.
        self.target_cc = f'{self.android_ndk_bin}/clang{EXE_EXT}'

        # Get include paths.
        def cc_cmd_args(cc_tool: str) -> List[str]:
            return [cc_tool, f'--target={self.android_target}']

        self.c_includes = self._get_cc_includes(cc_cmd_args(self.target_cc), 'c')
        self.cxx_includes = self._get_cc_includes(cc_cmd_args(self.target_cxx), 'c++')

    @classmethod
    def _get_cc_includes(cls, cmd_args: List[str], lang: str = 'c') -> List[str]:
        result = subprocess.run(
            cmd_args + ['-v', '-E', '-x', lang, '-'],
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
        if not self.zig:
            self._zig_init(probe_only=True)
        self._cmake_init()

        def onoff(b: bool) -> str:
            return 'ON' if b else 'OFF'

        def join_paths(
            paths: List[str], subdirs: Optional[List[str]] = None
        ) -> List[str]:
            return (
                ['/'.join([p, s]) for p in paths for s in subdirs] if subdirs else paths
            )

        def make_export_paths(
            lines: List[str],
            name: str,
            paths: List[str],
            subdirs: Optional[List[str]] = None,
        ):
            value = (
                os.pathsep + os.pathsep.join(join_paths(paths, subdirs)) + os.pathsep
            )
            export_only = False
            if name == 'PATH':
                value = f'$(subst /,$(SEP),{value})'
                export_only = True
            lines.append(f'# Environment variable `{name}`')
            lines.append(f'_s := {value}')
            lines.append(f'ifeq ($(findstring $(_s),$({name})),)')
            lines.append(
                f'    {"export" if export_only else "override"} {name} := $(_s)$({name})'
            )
            if not export_only:
                lines.append(f'    export {name}')
            lines.append('endif')

        # ===================== Generate .host.mk =====================
        lines: List[str] = []
        lines.append(f'override HOST_SYSTEM = {self.host.host_system}')
        lines.append(f'override HOST_TARGET = {self.host.triple}')
        lines.append(f'override HOST_CARGO_TARGET = {self.host.cargo_triple}')
        lines.append(f'override HOST_ARCH = {self.host.arch}')
        lines.append(f'override HOST_VENDOR = {self.host.vendor}')
        lines.append(f'override HOST_OS = {self.host.os}')
        lines.append(f'override HOST_ENV = {self.host.env}')
        lines.append('')
        lines.append('# Constants for the host platform')
        lines.append(f'override HOST_SEP := $(strip {os.sep})')
        lines.append(f'override HOST_PATHSEP = {os.pathsep}')
        lines.append(f'override HOST_EXE_EXT = {EXE_EXT}')
        lines.append('')
        lines.append(
            '# Unexport environment variables that may affect the CC compiler.'
        )
        lines.append('')
        for key in GCC_ENV_KEYS:
            lines.append(f'unexport {key}')
        with open(
            os.path.join(self.target_cmake_dir, self.host.host_system, '.host.mk'),
            'wb',
        ) as f:
            f.write('\n'.join(lines).encode('utf-8'))

        # ===================== Generate .host.cmake =====================
        lines.clear()
        lines.append(f'set(HOST_SYSTEM "{self.host.host_system}")')
        lines.append(f'set(HOST_TARGET "{self.host.triple}")')
        lines.append(f'set(HOST_CARGO_TARGET "{self.host.cargo_triple}")')
        lines.append(f'set(HOST_ARCH "{self.host.arch}")')
        lines.append(f'set(HOST_VENDOR "{self.host.vendor}")')
        lines.append(f'set(HOST_OS "{self.host.os}")')
        lines.append(f'set(HOST_ENV "{self.host.env}")')
        lines.append('')
        lines.append('# Constants for the host platform')
        lines.append(f'set(HOST_SEP "$(strip {os.sep})")')
        lines.append(f'set(HOST_PATHSEP "{os.pathsep}")')
        lines.append(f'set(HOST_EXE_EXT "{EXE_EXT}")')
        lines.append('')
        lines.append(
            '# Unexport environment variables that may affect the CC compiler.'
        )
        lines.append('')
        with open(
            os.path.join(self.target_cmake_dir, self.host.host_system, '.host.cmake'),
            'wb',
        ) as f:
            for key in GCC_ENV_KEYS:
                lines.append(f'unexport {key}')
            f.write('\n'.join(lines).encode('utf-8'))

        # ===================== Generate .settings.mk =====================
        lines.clear()
        lines.append(f'set(HOST_SYSTEM "{self.host.host_system}")')
        lines.append(f'set(HOST_TARGET "{self.host.triple}")')
        lines.append(f'set(HOST_CARGO_TARGET "{self.host.cargo_triple}")')
        lines.append(f'set(HOST_ARCH "{self.host.arch}")')
        lines.append(f'set(HOST_VENDOR "{self.host.vendor}")')
        lines.append(f'set(HOST_OS "{self.host.os}")')
        lines.append(f'set(HOST_ENV "{self.host.env}")')
        lines.append('')
        lines.append('# Constants for the host platform')
        host_sep_escaped = os.sep.replace('\\', '\\\\')
        lines.append(f'set(HOST_SEP "{host_sep_escaped}")')
        lines.append(f'set(HOST_PATHSEP "{os.pathsep}")')
        lines.append(f'set(HOST_EXE_EXT "{EXE_EXT}")')
        lines.append('')
        with open(
            os.path.join(self.target_cmake_dir, self.host.host_system, '.host.cmake'),
            'wb',
        ) as f:
            f.write('\n'.join(lines).encode('utf-8'))

        lines.clear()
        lines.append('# Home directory')
        lines.append(f'override CMKABE_HOME = {self.cmkabe_dir}')
        lines.append('')

        lines.append('# Constants for the target platform')
        target_sep = '\\' if self.win32 else '/'
        lines.append(f'override TARGET_SEP := $(strip {target_sep})')
        target_pathsep = ';' if self.win32 else ':'
        lines.append(f'override TARGET_PATHSEP = {target_pathsep}')
        target_exe_ext = '.exe' if self.win32 else ''
        lines.append(f'override TARGET_EXE_EXT = {target_exe_ext}')
        lines.append('')

        lines.append('# Build configuration')
        lines.append('ifeq ($(CMAKE_BUILD_TYPE),)')
        lines.append('    $(error CMAKE_BUILD_TYPE is not set)')
        lines.append('endif')
        lines.append('ifeq ($(DEBUG),)')
        lines.append('    $(error DEBUG is not set)')
        lines.append('endif')
        lines.append('override CARGO_BUILD_TYPE := $(call bsel,$(DEBUG),debug,release)')
        lines.append('')

        lines.append('# Constant directories')
        lines.append(f'override WORKSPACE_DIR = {self.workspace_dir}')
        lines.append(f'override TARGET_DIR = {self.target_dir}')
        lines.append(f'override TARGET_CMAKE_DIR = {self.target_cmake_dir}')
        lines.append(f'override CMAKE_LOCK_FILE = {self.cmake_lock_file}')
        lines.append(
            f'override TARGET_DEPENDENCY_PREFIXES = {" ".join(self.target_dependency_prefixes)}',
        )
        lines.append('')

        lines.append('# Cargo')
        lines.append(f'override TARGET = {self.target}')
        lines.append(f'override TARGET_ARCH = {self.arch}')
        lines.append(f'override TARGET_VENDOR = {self.vendor}')
        lines.append(f'override TARGET_OS = {self.os}')
        lines.append(f'override TARGET_ENV = {self.env}')
        lines.append(f'override TARGET_CC = {self.target_cc}')
        lines.append(f'override CARGO_TARGET = {self.cargo_target}')
        lines.append(
            f'override CARGO_TARGET_UNDERSCORE = {self.cargo_target.replace("-", "_")}',
        )
        lines.append(
            f'override CARGO_TARGET_UNDERSCORE_UPPER = {self.cargo_target.replace("-", "_").upper()}'
        )
        lines.append(f'override CARGO_TARGET_DIR = {self.cargo_target_dir}')
        lines.append(f'override CARGO_OUT_DIR := {self.cargo_out_dir(make=True)}')
        lines.append('')

        lines.append('# CMake')
        lines.append(f'override CMAKE_GENERATOR = {self.cmake_generator}')
        lines.append(f'override CMAKE_TARGET_DIR = {self.cmake_target_dir}')
        lines.append(f'override CMAKE_BUILD_DIR = {self.cmake_build_dir()}')
        lines.append('')

        lines.append('# MSVC')
        lines.append(f'override MSVC_ARCH = {self.msvc_arch}')
        lines.append(f'override MSVC_MASM = {self.msvc_masm}')
        lines.append('')

        lines.append('# Android')
        if self.android and self.version:
            lines.append(f'override ANDROID_SDK_VERSION = {self.version}')
        lines.append(
            f'override ANDROID_TARGET = {self.android_target}{"$(ANDROID_SDK_VERSION)" if self.android_target else ""}',
        )
        lines.append(f'override ANDROID_ARCH = {self.android_arch}')
        lines.append(f'override ANDROID_ABI = {self.android_abi}')
        if self.android_ndk_root:
            lines.append(f'override ANDROID_NDK_ROOT = {self.android_ndk_root}')
        if self.android_ndk_bin:
            lines.append(f'override ANDROID_NDK_BIN = {self.android_ndk_bin}')
        if self.android:
            lines.append('override CMAKE_SYSTEM_VERSION = $(ANDROID_SDK_VERSION)')
        lines.append('')

        lines.append('# Zig')
        lines.append(f'override ZIG = {onoff(self.zig)}')
        lines.append(f'override ZIG_TARGET = {self.zig_target}')
        lines.append(f'override ZIG_CC_DIR = {self.zig_cc_dir}')
        lines.append(f'override ZIG_ROOT = {self.zig_root}')
        lines.append('')

        lines.append('# Target related conditions')
        lines.append(f'override TARGET_IS_NATIVE = {onoff(self.target_is_native)}')
        lines.append(
            f'override TARGET_IS_CROSS_COMPILING = {onoff(self.is_cross_compiling)}'
        )
        lines.append(f'override TARGET_IS_RUNNABLE = {onoff(self.target_is_runnable)}')
        lines.append(f'override TARGET_IS_WIN32 = {onoff(self.win32)}')
        lines.append(f'override TARGET_IS_MSVC = {onoff(self.msvc)}')
        lines.append(f'override TARGET_IS_ANDROID = {onoff(self.android)}')
        lines.append(f'override TARGET_IS_UNIX = {onoff(self.unix)}')
        lines.append(f'override TARGET_IS_APPLE = {onoff(self.apple)}')
        lines.append(f'override TARGET_IS_IOS = {onoff(self.ios)}')
        lines.append(f'override TARGET_IS_WASM = {onoff(self.wasm)}')
        lines.append('')
        with open(os.path.join(self.cmake_target_dir, '.settings.mk'), 'wb') as f:
            f.write('\n'.join(lines).encode('utf-8'))

        # ===================== Generate .settings.cmake =====================
        lines.clear()
        lines.append('# Home directory')
        lines.append(f'set(CMKABE_HOME "{self.cmkabe_dir}")')
        lines.append('')

        lines.append('# Constants for the target platform')
        cmake_target_sep = '\\\\' if self.win32 else '/'
        lines.append(f'set(TARGET_SEP "{cmake_target_sep}")')
        cmake_target_pathsep = ';' if self.win32 else ':'
        lines.append(f'set(TARGET_PATHSEP "{cmake_target_pathsep}")')
        cmake_target_exe_ext = '.exe' if self.win32 else ''
        lines.append(f'set(TARGET_EXE_EXT "{cmake_target_exe_ext}")')
        lines.append('')

        def _cmake_add_build_type(lines: List[str]):
            lines.append('if(NOT CMAKE_BUILD_TYPE)')
            lines.append('    if(CMAKE_INSTALL_CONFIG_NAME)')
            lines.append('        set(CMAKE_BUILD_TYPE "${CMAKE_INSTALL_CONFIG_NAME}")')
            lines.append('    else()')
            lines.append('        set(CMAKE_BUILD_TYPE "Release")')
            lines.append('    endif()')
            lines.append('endif()')
            lines.append('string(TOLOWER "${CMAKE_BUILD_TYPE}" CMAKE_BUILD_TYPE_LOWER)')
            lines.append('if(CMAKE_BUILD_TYPE_LOWER STREQUAL "debug")')
            lines.append('    set(CARGO_BUILD_TYPE "debug")')
            lines.append('else()')
            lines.append('    set(CARGO_BUILD_TYPE "release")')
            lines.append('endif()')

        lines.append('# Build configuration')
        _cmake_add_build_type(lines)
        lines.append('')

        lines.append('# Constant directories')
        lines.append(f'set(WORKSPACE_DIR "{self.workspace_dir}")')
        lines.append(f'set(TARGET_DIR "{self.target_dir}")')
        lines.append(f'set(TARGET_CMAKE_DIR "{self.target_cmake_dir}")')
        lines.append(f'set(TARGET_LOCK_FILE "{self.cmake_lock_file}")')
        lines.append(
            f"""set(TARGET_DEPENDENCY_PREFIXES {' '.join(f'"{p}"' for p in self.target_dependency_prefixes)})"""
        )
        lines.append(
            f"""set(TARGET_PREFIX_SUBDIRS {' '.join(f'"{p}"' for p in self.target_prefix_subdirs)})"""
        )
        lines.append(
            f'set(TARGET_BIN_DIRS {" ".join(self.enum_prefix_subdirs_of("bin", quotes=True, cmake=True))})'
        )
        lines.append(
            f'set(TARGET_LIB_DIRS {" ".join(self.enum_prefix_subdirs_of("lib", quotes=True, cmake=True))})'
        )
        lines.append(
            f'set(TARGET_INCLUDE_DIRS {" ".join(self.enum_prefix_subdirs_of("include", quotes=True, cmake=True))})'
        )
        lines.append('')

        lines.append('# Cargo')
        lines.append(f'set(TARGET "{self.target}")')
        lines.append(f'set(TARGET_ARCH "{self.arch}")')
        lines.append(f'set(TARGET_VENDOR "{self.vendor}")')
        lines.append(f'set(TARGET_OS "{self.os}")')
        lines.append(f'set(TARGET_ENV "{self.env}")')
        lines.append(f'set(TARGET_CC "{self.target_cc}")')
        lines.append(f'set(CARGO_TARGET "{self.cargo_target}")')
        lines.append(
            f'set(CARGO_TARGET_UNDERSCORE "{self.cargo_target.replace("-", "_")}")',
        )
        lines.append(
            f'set(CARGO_TARGET_UNDERSCORE_UPPER "{self.cargo_target.replace("-", "_").upper()}")',
        )
        lines.append(f'set(CARGO_TARGET_DIR "{self.cargo_target_dir}")')
        lines.append(f'set(CARGO_OUT_DIR "{self.cargo_out_dir(cmake=True)}")')
        lines.append('')

        lines.append('# MSVC')
        lines.append(f'set(MSVC_ARCH "{self.msvc_arch}")')
        lines.append(f'set(MSVC_MASM "{self.msvc_masm}")')
        lines.append('')

        lines.append('# Android')
        if self.android and self.version:
            lines.append(f'set(ANDROID_SDK_VERSION "{self.version}")')
        android_target_val = (
            f'{self.android_target}${{ANDROID_SDK_VERSION}}'
            if self.android_target
            else ''
        )
        lines.append(
            f'set(ANDROID_TARGET "{android_target_val}")',
        )
        lines.append(f'set(ANDROID_ARCH "{self.android_arch}")')
        lines.append(f'set(ANDROID_ABI "{self.android_abi}")')
        if self.android_ndk_root:
            lines.append(
                f'set(ANDROID_NDK_ROOT "{self.android_ndk_root}")',
            )
        if self.android_ndk_bin:
            lines.append(
                f'set(ANDROID_NDK_BIN "{self.android_ndk_bin}")',
            )
        if self.android:
            lines.append(
                'set(CMAKE_SYSTEM_VERSION "${ANDROID_SDK_VERSION}")',
            )
        lines.append('')

        lines.append('# Zig')
        lines.append(f'set(ZIG {onoff(self.zig)})')
        lines.append(f'set(ZIG_TARGET "{self.zig_target}")')
        lines.append(f'set(ZIG_CC_DIR "{self.zig_cc_dir}")')
        lines.append(f'set(ZIG_ROOT "{self.zig_root}")')
        lines.append('')

        lines.append('# Target related conditions')
        lines.append(f'set(TARGET_IS_NATIVE {onoff(self.target_is_native)})')
        lines.append(f'set(TARGET_IS_CROSS_COMPILING {onoff(self.is_cross_compiling)})')
        lines.append(f'set(TARGET_IS_RUNNABLE {onoff(self.target_is_runnable)})')
        lines.append(f'set(TARGET_IS_WIN32 {onoff(self.win32)})')
        lines.append(f'set(TARGET_IS_MSVC {onoff(self.msvc)})')
        lines.append(f'set(TARGET_IS_ANDROID {onoff(self.android)})')
        lines.append(f'set(TARGET_IS_UNIX {onoff(self.unix)})')
        lines.append(f'set(TARGET_IS_APPLE {onoff(self.apple)})')
        lines.append(f'set(TARGET_IS_IOS {onoff(self.ios)})')
        lines.append(f'set(TARGET_IS_WASM {onoff(self.wasm)})')
        lines.append('')
        lines.append('# Suppress warnings')
        lines.append('set(ignoreMe "${CMAKE_VERBOSE_MAKEFILE}")')
        lines.append('')
        with open(os.path.join(self.cmake_target_dir, '.settings.cmake'), 'wb') as f:
            f.write('\n'.join(lines).encode('utf-8'))

        # ==========================================
        cc_exports: List[str] = []
        cc_options: List[str] = []
        linker_options: List[str] = []
        linker, ar, cc, cxx, ranlib, strip, rc = '', '', '', '', '', '', ''
        if self.android:
            cc_exports.append(f'ANDROID_NDK_ROOT = {self.android_ndk_root}')
            cc_options.append(f'--target={self.android_target}$(ANDROID_SDK_VERSION)')
            linker_options.extend(map(lambda x: '-C link-arg=' + x, cc_options))
            linker = f'{self.android_ndk_bin}/clang++{EXE_EXT}'
            ar = f'{self.android_ndk_bin}/llvm-ar{EXE_EXT}'
            cc = f'{self.android_ndk_bin}/clang{EXE_EXT}'
            cxx = f'{self.android_ndk_bin}/clang++{EXE_EXT}'
            ranlib = f'{self.android_ndk_bin}/llvm-ranlib{EXE_EXT}'
            strip = f'{self.android_ndk_bin}/llvm-strip{EXE_EXT}'
        elif self.zig:
            cc_exports.append(f'ZIG_WRAPPER_TARGET = {self.zig_target}')
            cc_exports.append(f'ZIG_WRAPPER_CLANG_TARGET = {self.cargo_target}')
            cc_options.append('--disable-dllexport')
            if (
                (self.os == 'windows' and self.env == 'gnu')
                or (self.os == 'linux' and self.env == 'musl')
                or self.os.startswith('wasi')
            ):
                linker_options.append('-C linker-flavor=gcc')
                linker_options.append('-C link-self-contained=no')
            linker = f'{self.zig_cc_dir}/zig-c++{EXE_EXT}'
            ar = f'{self.zig_cc_dir}/zig-ar{EXE_EXT}'
            cc = f'{self.zig_cc_dir}/zig-cc{EXE_EXT}'
            cxx = f'{self.zig_cc_dir}/zig-c++{EXE_EXT}'
            ranlib = f'{self.zig_cc_dir}/zig-ranlib{EXE_EXT}'
            strip = f'{self.zig_cc_dir}/zig-strip{EXE_EXT}'
            rc = f'{self.zig_cc_dir}/zig-rc{EXE_EXT}'
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
                raise ValueError(f'Unrecognized target CC: {self.target_cc}')
            linker = target_cc_abs + cc_ext
            cc = target_cc_abs + cc_ext
            ar = cc_prefix + '-ar' + cc_ext
            ranlib = cc_prefix + '-ranlib' + cc_ext
            strip = cc_prefix + '-strip' + cc_ext

        # ===================== Generate .environ.mk =====================
        lines.clear()
        if cc_exports:
            for line in cc_exports:
                k, v = list(map(lambda x: x.strip(), line.split('=', 1)))
                if k.endswith('+'):
                    k = k[:-1].strip()
                    make_export_paths(lines, k, [v])
                else:
                    lines.append(f'export {k} = {v}')
            lines.append('')

        cargo_target = 'CARGO_TARGET_' + self.cargo_target.upper().replace('-', '_')
        if cc:
            lines.append('# LINKER')
            lines.append(f'export {cargo_target}_LINKER = {linker}')
        lines.append('# RUSTFLAGS')
        lines.append(
            f'override {cargo_target}_RUSTFLAGS := {" ".join(linker_options)} $(TARGET_RUSTFLAGS)',
        )
        lines.append(f'export {cargo_target}_RUSTFLAGS')
        lines.append('')

        cargo_target_under = self.cargo_target.replace('-', '_')
        if cc:
            lines.append('# AR, CC, CXX, RANLIB, STRIP')
            lines.append(f'export AR_{cargo_target_under} = {ar}')
            lines.append(f'export CC_{cargo_target_under} = {cc}')
            lines.append(f'export CXX_{cargo_target_under} = {cxx}')
            lines.append(
                f'export RANLIB_{cargo_target_under} = {ranlib}',
            )
            lines.append(f'export STRIP_{cargo_target_under} = {strip}')
            lines.append('')
        lines.append('# ARFLAGS, CFLAGS, CXXFLAGS, RANLIBFLAGS')
        lines.append(
            f'override ARFLAGS_{cargo_target_under} := $(TARGET_ARFLAGS)',
        )
        lines.append(f'export ARFLAGS_{cargo_target_under}')
        lines.append(
            f'override CFLAGS_{cargo_target_under} := {" ".join(cc_options)} $(TARGET_CFLAGS)',
        )
        lines.append(f'export CFLAGS_{cargo_target_under}')
        lines.append(
            f'override CXXFLAGS_{cargo_target_under} := {" ".join(cc_options)} $(TARGET_CXXFLAGS)',
        )
        lines.append(f'export CXXFLAGS_{cargo_target_under}')
        lines.append(
            f'override RANLIBFLAGS_{cargo_target_under} := $(TARGET_RANLIBFLAGS)',
        )
        lines.append(f'export RANLIBFLAGS_{cargo_target_under}')
        lines.append('')

        lines.append('# Configure the cross compile pkg-config.')
        lines.append(
            f'export PKG_CONFIG_ALLOW_CROSS = {1 if self.is_cross_compiling else 0}'
        )
        lines.append(
            f'override PKG_CONFIG_PATH_{cargo_target_under} := $(TARGET_PKG_CONFIG_PATH)$(if $(TARGET_PKG_CONFIG_PATH),{os.pathsep},)'
            + os.pathsep.join(
                join_paths(self.enum_prefix_subdirs_of('lib/pkgconfig', make=True), [])
            )
        )
        lines.append(f'export PKG_CONFIG_PATH_{cargo_target_under}')
        lines.append('')

        lines.append('# For Rust bingen + libclang')
        bindgen_includes = (
            self.enum_prefix_subdirs_of('include', make=True) + self.cxx_includes
        )
        hardening_mode = '-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST' + (
            '' if self.apple else ' -D_LIBCPP_HAS_NO_VENDOR_AVAILABILITY_ANNOTATIONS=1'
        )
        includes_str = ' '.join(f'-I"{x}"' for x in bindgen_includes)
        lines.append(
            f'override BINDGEN_EXTRA_CLANG_ARGS := $(TARGET_BINDGEN_CLANG_ARGS) {hardening_mode} {includes_str}',
        )
        lines.append('export BINDGEN_EXTRA_CLANG_ARGS')
        lines.append('')

        lines.append('# For Rust cmake')
        lines.append(
            f'export CMAKE_TOOLCHAIN_FILE_{cargo_target_under} = {self.cmake_target_dir}/.toolchain.cmake',
        )
        if self.cmake_generator:
            lines.append(
                f'export CMAKE_GENERATOR_{cargo_target_under} = {self.cmake_generator}',
            )
        else:
            lines.append(
                f'unexport CMAKE_GENERATOR_{cargo_target_under}',
            )
        lines.append('')

        lines.append('# Set system paths.')
        if self.target_is_runnable:
            make_export_paths(
                lines,
                'PATH',
                [self.zig_cc_dir] + self.enum_prefix_subdirs_of('bin', make=True),
                [],
            )
            if not self.host_is_windows:
                make_export_paths(
                    lines,
                    'LD_LIBRARY_PATH',
                    self.enum_prefix_subdirs_of('lib', make=True),
                    [],
                )
        lines.append('')

        _make_build_vars = [
            'TARGET',
            'TARGET_DIR',
            'TARGET_CMAKE_DIR',
            'TARGET_DEPENDENCY_PREFIXES',
            'TARGET_CC',
            'CARGO_TARGET',
            'ZIG_TARGET',
            'TARGET_INSTALL_PREFIX',
            'CMAKE_INSTALL_PREFIX',
            'DEBUG',
            'MINSIZE',
            'DBGINFO',
        ]
        lines.append('# Export variables for Cargo build.rs and CMake')
        lines.append(f'export CARGO_WORKSPACE_DIR = {self.workspace_dir}')
        lines.append(f'export CMKABE_HOME = {self.cmkabe_dir}')
        lines.append(f'export CMKABE_HOST_TARGET = {self.host.triple}')
        lines.append(f'export CMKABE_TARGET = {self.cmkabe_target}')
        lines.append(f'export CMKABE_TARGET_DIR = {self.target_dir}')
        lines.append(f'export CMKABE_TARGET_CMAKE_DIR = {self.target_cmake_dir}')
        lines.append(
            f'export CMKABE_TARGET_DEPENDENCY_PREFIXES = {os.path.pathsep.join(self.target_dependency_prefixes)}'
        )
        lines.append(f'export CMKABE_TARGET_CC = {self.target_cc}')
        lines.append(f'export CMKABE_CARGO_TARGET = {self.cargo_target}')
        lines.append(f'export CMKABE_ZIG_TARGET = {self.zig_target}')
        lines.append('export CMKABE_TARGET_INSTALL_PREFIX := $(TARGET_INSTALL_PREFIX)')
        lines.append(
            'export CMKABE_CMAKE_INSTALL_PREFIX := $(TARGET_INSTALL_PREFIX)/$(TARGET)'
        )
        lines.append('export CMKABE_DEBUG := $(DEBUG)')
        lines.append('export CMKABE_MINSIZE := $(MINSIZE)')
        lines.append('export CMKABE_DBGINFO := $(DBGINFO)')
        lines.append('export CMKABE_CMAKE_BUILD_TYPE := $(CMAKE_BUILD_TYPE)')
        lines.append('export CMKABE_CMAKE_BUILD_DIR := $(CMAKE_BUILD_DIR)')
        lines.append(f'export CMKABE_CARGO_OUT_DIR := {self.cargo_out_dir(make=True)}')
        lines.append(f'export CMKABE_MAKE_BUILD_VARS = {",".join(_make_build_vars)}')
        lines.append(
            f'export CMKABE_PREFIX_SUBDIRS := {os.path.pathsep.join(self.target_prefix_subdirs)}'
        )
        lines.append(
            f'export CMKABE_BIN_DIRS := {os.path.pathsep.join(self.enum_prefix_subdirs_of("bin", make=True))}'
        )
        lines.append(
            f'export CMKABE_LIB_DIRS := {os.path.pathsep.join(self.enum_prefix_subdirs_of("lib", make=True))}'
        )
        lines.append(
            f'export CMKABE_INCLUDE_DIRS := {os.path.pathsep.join(self.enum_prefix_subdirs_of("include", make=True))}'
        )
        lines.append('')
        lines.append('# export CMKABE_COMPLETED_PROJECTS which is from command line.')
        lines.append('ifeq ($(origin CMKABE_COMPLETED_PROJECTS),command line)')
        lines.append('    export CMKABE_COMPLETED_PROJECTS')
        lines.append('else')
        lines.append('    undefine CMKABE_COMPLETED_PROJECTS')
        lines.append('    unexport CMKABE_COMPLETED_PROJECTS')
        lines.append('endif')
        lines.append('')

        with open(os.path.join(self.cmake_target_dir, '.environ.mk'), 'wb') as f:
            f.write('\n'.join(lines).encode('utf-8'))

        # ===================== Generate .environ.cmake =====================
        lines.clear()
        lines.append('# AR, CC, CXX, RANLIB, STRIP, RC')
        lines.append(f'set(TARGET_AR "{ar}")')
        lines.append(f'set(TARGET_CC "{cc}")')
        lines.append(f'set(TARGET_CXX "{cxx}")')
        lines.append(f'set(TARGET_RANLIB "{ranlib}")')
        lines.append(f'set(TARGET_STRIP "{strip}")')
        lines.append(f'set(TARGET_RC "{rc}")')
        lines.append('')

        lines.append('# Build configuration')
        _cmake_add_build_type(lines)
        lines.append('if(CMAKE_BUILD_TYPE_LOWER STREQUAL "debug")')
        lines.append('    set(CMKABE_DEBUG ON)')
        lines.append('    set(CMKABE_MINSIZE OFF)')
        lines.append('    set(CMKABE_DBGINFO ON)')
        lines.append('elseif(CMAKE_BUILD_TYPE_LOWER STREQUAL "minsizerel")')
        lines.append('    set(CMKABE_DEBUG OFF)')
        lines.append('    set(CMKABE_MINSIZE ON)')
        lines.append('    set(CMKABE_DBGINFO OFF)')
        lines.append('elseif(CMAKE_BUILD_TYPE_LOWER STREQUAL "relwithdebinfo")')
        lines.append('    set(CMKABE_DEBUG OFF)')
        lines.append('    set(CMKABE_MINSIZE OFF)')
        lines.append('    set(CMKABE_DBGINFO ON)')
        lines.append('else()')
        lines.append('    set(CMKABE_DEBUG OFF)')
        lines.append('    set(CMKABE_MINSIZE OFF)')
        lines.append('    set(CMKABE_DBGINFO OFF)')
        lines.append('endif()')
        lines.append('if(CMAKE_INSTALL_CONFIG_NAME)')
        lines.append(
            f'    set(CMKABE_CMAKE_BUILD_DIR "{self.cmake_target_dir}/${{CMAKE_BUILD_TYPE}}")'
        )
        lines.append('else()')
        lines.append('    set(CMKABE_CMAKE_BUILD_DIR "${CMAKE_BINARY_DIR}")')
        lines.append('endif()')
        lines.append('')

        lines.append('# Find `CMKABE_TARGET_INSTALL_PREFIX` by `CMAKE_INSTALL_PREFIX')
        lines.append('function(_cmkabe_get_target_install_prefix result)')
        lines.append(
            '    string(REPLACE "\\\\" "/" clean_dir "${CMAKE_INSTALL_PREFIX}")'
        )
        lines.append('    string(REGEX REPLACE "/+$" "" clean_dir "${clean_dir}")')
        lines.append(
            '    get_filename_component(_current_basename "${clean_dir}" NAME)'
        )
        lines.append(
            f'    if((_current_basename STREQUAL "{self.target}") OR (_current_basename STREQUAL "{self.cmkabe_target}"))'
        )
        lines.append(
            '        get_filename_component(result_dir "${clean_dir}" DIRECTORY)'
        )
        lines.append('    else()')
        lines.append('        set(result_dir "${CMAKE_INSTALL_PREFIX}")')
        lines.append('    endif()')
        lines.append('    set(${result} "${result_dir}" PARENT_SCOPE)')
        lines.append('endfunction()')
        lines.append('_cmkabe_get_target_install_prefix(CMKABE_TARGET_INSTALL_PREFIX)')
        lines.append('')

        # For CMAKE list, escape semicolon.
        def cmk_lst_esc(value):
            return value.replace(';', '$<SEMICOLON>').replace(
                '${CMAKE_BINARY_DIR}', '${CMKABE_CMAKE_BUILD_DIR}'
            )

        lines.append('set(CMKABE_ENV_BLOCK')
        if cc_exports:
            for line in cc_exports:
                k, v = list(map(lambda x: x.strip(), line.split('=', 1)))
                if k.endswith('+'):
                    print(f'Skip {line} (It is not supported yet.)', file=sys.stderr)
                else:
                    lines.append(cmk_lst_esc(f'"{k}={v}"'))

        lines.append(cmk_lst_esc(f'"CARGO_WORKSPACE_DIR={self.workspace_dir}"'))
        lines.append(cmk_lst_esc(f'"CMKABE_HOME={self.cmkabe_dir}"'))
        lines.append(cmk_lst_esc(f'"CMKABE_HOST_TARGET={self.host.triple}"'))
        lines.append(cmk_lst_esc(f'"CMKABE_TARGET={self.cmkabe_target}"'))
        lines.append(cmk_lst_esc(f'"CMKABE_TARGET_DIR={self.target_dir}"'))
        lines.append(cmk_lst_esc(f'"CMKABE_TARGET_CMAKE_DIR={self.target_cmake_dir}"'))
        lines.append(
            cmk_lst_esc(
                f'"CMKABE_TARGET_DEPENDENCY_PREFIXES={os.path.pathsep.join(self.target_dependency_prefixes)}"'
            )
        )
        lines.append(cmk_lst_esc(f'"CMKABE_TARGET_CC={self.target_cc}"'))
        lines.append(cmk_lst_esc(f'"CMKABE_CARGO_TARGET={self.cargo_target}"'))
        lines.append(cmk_lst_esc(f'"CMKABE_ZIG_TARGET={self.zig_target}"'))
        lines.append(
            cmk_lst_esc(
                '"CMKABE_TARGET_INSTALL_PREFIX=${CMKABE_TARGET_INSTALL_PREFIX}"'
            )
        )
        lines.append(
            cmk_lst_esc('"CMKABE_CMAKE_INSTALL_PREFIX=${CMAKE_INSTALL_PREFIX}"')
        )
        lines.append(cmk_lst_esc('"CMKABE_DEBUG=${CMKABE_DEBUG}"'))
        lines.append(cmk_lst_esc('"CMKABE_MINSIZE=${CMKABE_MINSIZE}"'))
        lines.append(cmk_lst_esc('"CMKABE_DBGINFO=${CMKABE_DBGINFO}"'))
        lines.append(cmk_lst_esc('"CMKABE_CMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}"'))
        lines.append(cmk_lst_esc('"CMKABE_CMAKE_BUILD_DIR=${CMAKE_BINARY_DIR}"'))
        lines.append(
            cmk_lst_esc(f'"CMKABE_CARGO_OUT_DIR={self.cargo_out_dir(cmake=True)}"')
        )
        lines.append(
            cmk_lst_esc(f'"CMKABE_MAKE_BUILD_VARS={",".join(_make_build_vars)}"')
        )
        lines.append(
            cmk_lst_esc(
                f'"CMKABE_PREFIX_SUBDIRS={os.path.pathsep.join(self.target_prefix_subdirs)}"'
            )
        )
        lines.append(
            cmk_lst_esc(
                f'"CMKABE_BIN_DIRS={os.path.pathsep.join(self.enum_prefix_subdirs_of("bin", cmake=True))}"'
            )
        )
        lines.append(
            cmk_lst_esc(
                f'"CMKABE_LIB_DIRS={os.path.pathsep.join(self.enum_prefix_subdirs_of("lib", cmake=True))}"'
            )
        )
        lines.append(
            cmk_lst_esc(
                f'"CMKABE_INCLUDE_DIRS={os.path.pathsep.join(self.enum_prefix_subdirs_of("include", cmake=True))}"'
            )
        )
        lines.append(')')
        lines.append('')
        with open(os.path.join(self.cmake_target_dir, '.environ.cmake'), 'wb') as f:
            f.write('\n'.join(lines).encode('utf-8'))

        # ===================== Generate .toolchain.cmake =====================
        lines.clear()
        lines.append('cmake_minimum_required(VERSION 3.16)')
        lines.append('')
        lines.append(f'include("{self.cmake_target_dir}/.settings.cmake")')
        lines.append(f'set(TARGET "{self.cmkabe_target}")')
        lines.append('set(ZIG_CC_DISABLE_DLLEXPORT ON)')
        lines.append('')
        lines.append('set(TARGET "${TARGET}" CACHE STRING "" FORCE)')
        lines.append('set(TARGET_DIR "${TARGET_DIR}" CACHE STRING "" FORCE)')
        lines.append(
            'set(TARGET_CMAKE_DIR "${TARGET_CMAKE_DIR}" CACHE STRING "" FORCE)'
        )
        lines.append('')
        lines.append('include("${CMKABE_HOME}/cmake/toolchain.cmake")')
        lines.append('_cmkabe_apply_extra_flags()')
        lines.append('')
        with open(os.path.join(self.cmake_target_dir, '.toolchain.cmake'), 'wb') as f:
            f.write('\n'.join(lines).encode('utf-8'))
