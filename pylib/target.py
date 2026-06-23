# -*- coding: utf-8 -*-
"""Parse build target triples and generate configuration files for Make/CMake."""

import glob
import os
import shutil
import subprocess
from typing import Any, Generator, List, Optional

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
    copy_env_for_cc,
    host_target_info,
    join_triple,
    lock_file,
    ndk_root,
    need_update,
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
        self.host: HostTargetInfo = host_target_info()

        self.cmkabe_dir: str = normpath(
            os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        )

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
        for directory in self.cmake_prefix_subdirs:
            item = f'{directory}{"/" if subdir else ""}{subdir}'
            res.append(f'"{item}"' if quotes else item)
        return res

    def parse(self) -> 'TargetParser':
        """Parse target parameters, setup compilers, and directories."""
        self.target_is_native = self.target in ('', 'native')
        if self.target_is_native:
            self.target = self.host.triple

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
                self.vendor != self.host.vendor
                or self.os != self.host.os
                or self.env != self.host.env
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
            self.target_is_native or self.cargo_target != self.host.cargo_triple
        ) and self.target == self.cargo_target:
            self.cargo_target_dir = self.target_dir
        else:
            self.cargo_target_dir = f'{self.target_dir}/{self.target}'

        self.cmake_prefix_dir = f'{self.cmake_target_prefix}/{self.target}'

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
            f'{self.cmake_target_prefix}/{x}' for x in _any_prefix_subdirs()
        ]
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
        try:
            result = subprocess.run(
                [
                    vswhere,
                    '-latest',
                    '-requires',
                    'Microsoft.VisualStudio.Component.VC.Tools.*',
                    '-find',
                    rf'VC\Tools\MSVC\**\bin\*{VSTOOLS_ARCH_MAP.get(self.host.arch, self.host.arch)}\{VSTOOLS_ARCH_MAP.get(self.arch, self.arch)}\ml*.exe',
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
        self.cmake_target_dir = f'{self.target_cmake_dir}/{self.host.host_system}/{"native" if self.target_is_native else self.target}'
        os.makedirs(self.cmake_target_dir, exist_ok=True)

    def _zig_init(self) -> None:
        # Zig root path and include directories.
        zig_path = shutil.which('zig' + EXE_EXT)
        if not zig_path:
            raise FileNotFoundError('`zig` is not found')
        self.zig_root = normpath(os.path.realpath(os.path.dirname(zig_path)))

        self.zig_cc_dir = normpath(
            os.path.join(self.target_dir, '.zig', self.host.host_system)
        )
        src = self.cmkabe_dir + '/zig-wrapper/main.zig'
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
                    f'-femit-bin={exe}',
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
                value = f'$(subst /,$(SEP),{value})'
                export_only = True
            return ''.join(
                [
                    f'# Environment variable `{name}`\n',
                    f'_s := {value}\n',
                    f'ifeq ($(findstring $(_s),$({name})),)\n',
                    f'    {"export" if export_only else "override"} {name} := $(_s)$({name})\n',
                    f'    export {name}\n' if not export_only else '',
                    'endif\n',
                ]
            )

        def cmake_export_paths(
            name: str, paths: List[str], subdirs: Optional[List[str]] = None
        ) -> str:
            env_name = f'ENV{{{name}}}'
            value = (
                os.pathsep + os.pathsep.join(join_paths(paths, subdirs)) + os.pathsep
            )
            return ''.join(
                [
                    f'# Environment variable `{name}`\n',
                    f'set(_s "{value}")\n',
                    f'string(FIND "${env_name}" "${{_s}}" _n)\n',
                    'if(_n EQUAL -1)\n',
                    f'    set({env_name} "${{_s}}${env_name}")\n',
                    'endif()\n',
                ]
            )

        with open(
            os.path.join(self.target_cmake_dir, self.host.host_system, '.host.mk'),
            'wb',
        ) as f:
            fwrite(f, f'override HOST_SYSTEM = {self.host.host_system}\n')
            fwrite(f, f'override HOST_TARGET = {self.host.triple}\n')
            fwrite(
                f,
                f'override HOST_CARGO_TARGET = {self.host.cargo_triple}\n',
            )
            fwrite(f, f'override HOST_ARCH = {self.host.arch}\n')
            fwrite(f, f'override HOST_VENDOR = {self.host.vendor}\n')
            fwrite(f, f'override HOST_OS = {self.host.os}\n')
            fwrite(f, f'override HOST_ENV = {self.host.env}\n')
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            fwrite(f, f'override HOST_SEP := $(strip {os.sep})\n')
            fwrite(f, f'override HOST_PATHSEP = {os.pathsep}\n')
            fwrite(f, f'override HOST_EXE_EXT = {EXE_EXT}\n')
            fwrite(f, '\n')
            fwrite(
                f,
                '# Unexport environment variables that may affect the CC compiler.\n',
            )
            for key in GCC_ENV_KEYS:
                fwrite(f, f'unexport {key}\n')

        with open(
            os.path.join(self.target_cmake_dir, self.host.host_system, '.host.cmake'),
            'wb',
        ) as f:
            fwrite(f, f'set(HOST_SYSTEM "{self.host.host_system}")\n')
            fwrite(f, f'set(HOST_TARGET "{self.host.triple}")\n')
            fwrite(
                f,
                f'set(HOST_CARGO_TARGET "{self.host.cargo_triple}")\n',
            )
            fwrite(f, f'set(HOST_ARCH "{self.host.arch}")\n')
            fwrite(f, f'set(HOST_VENDOR "{self.host.vendor}")\n')
            fwrite(f, f'set(HOST_OS "{self.host.os}")\n')
            fwrite(f, f'set(HOST_ENV "{self.host.env}")\n')
            fwrite(f, '\n')
            fwrite(f, '# Constants for the host platform\n')
            host_sep_escaped = os.sep.replace('\\', '\\\\')
            fwrite(f, f'set(HOST_SEP "{host_sep_escaped}")\n')
            fwrite(f, f'set(HOST_PATHSEP "{os.pathsep}")\n')
            fwrite(f, f'set(HOST_EXE_EXT "{EXE_EXT}")\n')

        with open(os.path.join(self.cmake_target_dir, '.settings.mk'), 'wb') as f:
            fwrite(f, '# Home directory\n')
            fwrite(f, f'override CMKABE_HOME = {self.cmkabe_dir}\n')
            fwrite(f, '\n')

            fwrite(f, '# Constants for the target platform\n')
            target_sep = '\\' if self.win32 else '/'
            fwrite(
                f,
                f'override TARGET_SEP := $(strip {target_sep})\n',
            )
            target_pathsep = ';' if self.win32 else ':'
            fwrite(
                f,
                f'override TARGET_PATHSEP = {target_pathsep}\n',
            )
            target_exe_ext = '.exe' if self.win32 else ''
            fwrite(
                f,
                f'override TARGET_EXE_EXT = {target_exe_ext}\n',
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
            fwrite(f, f'override WORKSPACE_DIR = {self.workspace_dir}\n')
            fwrite(f, f'override TARGET_DIR = {self.target_dir}\n')
            fwrite(
                f,
                f'override TARGET_CMAKE_DIR = {self.target_cmake_dir}\n',
            )
            fwrite(
                f,
                f'override CMAKE_LOCK_FILE = {self.cmake_lock_file}\n',
            )
            fwrite(
                f,
                f'override CMAKE_TARGET_PREFIX = {self.cmake_target_prefix}\n',
            )
            fwrite(
                f,
                f'override CMAKE_PREFIX_DIR = {self.cmake_prefix_dir}\n',
            )
            fwrite(
                f,
                f'override CMAKE_PREFIX_SUBDIRS = {" ".join(self.enum_prefix_subdirs_of("", make=True))}\n',
            )
            fwrite(
                f,
                f'override CMAKE_PREFIX_BINS := {" ".join(self.enum_prefix_subdirs_of("bin", make=True))}\n',
            )
            fwrite(
                f,
                f'override CMAKE_PREFIX_LIBS := {" ".join(self.enum_prefix_subdirs_of("lib", make=True))}\n',
            )
            fwrite(
                f,
                f'override CMAKE_PREFIX_INCLUDES = {" ".join(self.enum_prefix_subdirs_of("include", make=True))}\n',
            )
            fwrite(f, '\n')

            fwrite(f, '# Cargo\n')
            fwrite(f, f'override TARGET = {self.target}\n')
            fwrite(f, f'override TARGET_ARCH = {self.arch}\n')
            fwrite(f, f'override TARGET_VENDOR = {self.vendor}\n')
            fwrite(f, f'override TARGET_OS = {self.os}\n')
            fwrite(f, f'override TARGET_ENV = {self.env}\n')
            fwrite(f, f'override TARGET_CC = {self.target_cc}\n')
            fwrite(f, f'override CARGO_TARGET = {self.cargo_target}\n')
            fwrite(
                f,
                f'override CARGO_TARGET_UNDERSCORE = {self.cargo_target.replace("-", "_")}\n',
            )
            fwrite(
                f,
                f'override CARGO_TARGET_UNDERSCORE_UPPER = {self.cargo_target.replace("-", "_").upper()}\n',
            )
            fwrite(
                f,
                f'override CARGO_TARGET_DIR = {self.cargo_target_dir}\n',
            )
            fwrite(
                f,
                f'override CARGO_OUT_DIR := {self.cargo_out_dir(make=True)}\n',
            )
            fwrite(f, '\n')

            fwrite(f, '# CMake\n')
            fwrite(
                f,
                f'override CMAKE_GENERATOR = {self.cmake_generator}\n',
            )
            fwrite(
                f,
                f'override CMAKE_TARGET_DIR = {self.cmake_target_dir}\n',
            )
            fwrite(
                f,
                f'override CMAKE_BUILD_DIR = {self.cmake_build_dir()}\n',
            )
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, f'override MSVC_ARCH = {self.msvc_arch}\n')
            fwrite(f, f'override MSVC_MASM = {self.msvc_masm}\n')
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            fwrite(
                f,
                f'override ANDROID_TARGET = {self.android_target}{"$(ANDROID_SDK_VERSION)" if self.android_target else ""}\n',
            )
            fwrite(f, f'override ANDROID_ARCH = {self.android_arch}\n')
            fwrite(f, f'override ANDROID_ABI = {self.android_abi}\n')
            if self.android_ndk_root:
                fwrite(
                    f,
                    f'override ANDROID_NDK_ROOT = {self.android_ndk_root}\n',
                )
            if self.android_ndk_bin:
                fwrite(
                    f,
                    f'override ANDROID_NDK_BIN = {self.android_ndk_bin}\n',
                )
            if self.android:
                fwrite(
                    f,
                    'override CMAKE_SYSTEM_VERSION = $(ANDROID_SDK_VERSION)\n',
                )
            fwrite(f, '\n')

            fwrite(f, '# Zig\n')
            fwrite(f, f'override ZIG = {onoff(self.zig)}\n')
            fwrite(f, f'override ZIG_TARGET = {self.zig_target}\n')
            fwrite(f, f'override ZIG_CC_DIR = {self.zig_cc_dir}\n')
            fwrite(f, f'override ZIG_ROOT = {self.zig_root}\n')
            fwrite(f, '\n')

            fwrite(f, '# Target related conditions\n')
            fwrite(
                f,
                f'override TARGET_IS_NATIVE = {onoff(self.target_is_native)}\n',
            )
            fwrite(
                f,
                f'override TARGET_IS_RUNNABLE = {onoff(self.target_is_runnable)}\n',
            )
            fwrite(f, f'override TARGET_IS_WIN32 = {onoff(self.win32)}\n')
            fwrite(f, f'override TARGET_IS_MSVC = {onoff(self.msvc)}\n')
            fwrite(
                f,
                f'override TARGET_IS_ANDROID = {onoff(self.android)}\n',
            )
            fwrite(f, f'override TARGET_IS_UNIX = {onoff(self.unix)}\n')
            fwrite(f, f'override TARGET_IS_APPLE = {onoff(self.apple)}\n')
            fwrite(f, f'override TARGET_IS_IOS = {onoff(self.ios)}\n')
            fwrite(f, f'override TARGET_IS_WASM = {onoff(self.wasm)}\n')

        with open(os.path.join(self.cmake_target_dir, '.settings.cmake'), 'wb') as f:
            fwrite(f, '# Home directory\n')
            fwrite(f, f'set(CMKABE_HOME "{self.cmkabe_dir}")\n')
            fwrite(f, '\n')

            fwrite(f, '# Constants for the target platform\n')
            cmake_target_sep = '\\\\' if self.win32 else '/'
            fwrite(
                f,
                f'set(TARGET_SEP "{cmake_target_sep}")\n',
            )
            cmake_target_pathsep = ';' if self.win32 else ':'
            fwrite(
                f,
                f'set(TARGET_PATHSEP "{cmake_target_pathsep}")\n',
            )
            cmake_target_exe_ext = '.exe' if self.win32 else ''
            fwrite(
                f,
                f'set(TARGET_EXE_EXT "{cmake_target_exe_ext}")\n',
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
            fwrite(f, f'set(WORKSPACE_DIR "{self.workspace_dir}")\n')
            fwrite(f, f'set(TARGET_DIR "{self.target_dir}")\n')
            fwrite(f, f'set(TARGET_CMAKE_DIR "{self.target_cmake_dir}")\n')
            fwrite(f, f'set(TARGET_LOCK_FILE "{self.cmake_lock_file}")\n')
            fwrite(f, f'set(TARGET_PREFIX "{self.cmake_target_prefix}")\n')
            fwrite(f, f'set(TARGET_PREFIX_DIR "{self.cmake_prefix_dir}")\n')
            fwrite(
                f,
                f'set(TARGET_PREFIX_SUBDIRS {" ".join(self.enum_prefix_subdirs_of("", quotes=True, cmake=True))})\n',
            )
            fwrite(
                f,
                f'set(TARGET_PREFIX_BINS {" ".join(self.enum_prefix_subdirs_of("bin", quotes=True, cmake=True))})\n',
            )
            fwrite(
                f,
                f'set(TARGET_PREFIX_LIBS {" ".join(self.enum_prefix_subdirs_of("lib", quotes=True, cmake=True))})\n',
            )
            fwrite(
                f,
                f'set(TARGET_PREFIX_INCLUDES {" ".join(self.enum_prefix_subdirs_of("include", quotes=True, cmake=True))})\n',
            )
            fwrite(f, '\n')

            fwrite(f, '# Cargo\n')
            fwrite(f, f'set(TARGET "{self.target}")\n')
            fwrite(f, f'set(TARGET_ARCH "{self.arch}")\n')
            fwrite(f, f'set(TARGET_VENDOR "{self.vendor}")\n')
            fwrite(f, f'set(TARGET_OS "{self.os}")\n')
            fwrite(f, f'set(TARGET_ENV "{self.env}")\n')
            fwrite(f, f'set(TARGET_CC "{self.target_cc}")\n')
            fwrite(f, f'set(CARGO_TARGET "{self.cargo_target}")\n')
            fwrite(
                f,
                f'set(CARGO_TARGET_UNDERSCORE "{self.cargo_target.replace("-", "_")}")\n',
            )
            fwrite(
                f,
                f'set(CARGO_TARGET_UNDERSCORE_UPPER "{self.cargo_target.replace("-", "_").upper()}")\n',
            )
            fwrite(f, f'set(CARGO_TARGET_DIR "{self.cargo_target_dir}")\n')
            fwrite(
                f,
                f'set(CARGO_OUT_DIR "{self.cargo_out_dir(cmake=True)}")\n',
            )
            fwrite(f, '\n')

            fwrite(f, '# MSVC\n')
            fwrite(f, f'set(MSVC_ARCH "{self.msvc_arch}")\n')
            fwrite(f, f'set(MSVC_MASM "{self.msvc_masm}")\n')
            fwrite(f, '\n')

            fwrite(f, '# Android\n')
            android_target_val = (
                f'{self.android_target}${{ANDROID_SDK_VERSION}}'
                if self.android_target
                else ''
            )
            fwrite(
                f,
                f'set(ANDROID_TARGET "{android_target_val}")\n',
            )
            fwrite(f, f'set(ANDROID_ARCH "{self.android_arch}")\n')
            fwrite(f, f'set(ANDROID_ABI "{self.android_abi}")\n')
            if self.android_ndk_root:
                fwrite(
                    f,
                    f'set(ANDROID_NDK_ROOT "{self.android_ndk_root}")\n',
                )
            if self.android_ndk_bin:
                fwrite(
                    f,
                    f'set(ANDROID_NDK_BIN "{self.android_ndk_bin}")\n',
                )
            if self.android:
                fwrite(
                    f,
                    'set(CMAKE_SYSTEM_VERSION "${ANDROID_SDK_VERSION}")\n',
                )
            fwrite(f, '\n')

            fwrite(f, '# Zig\n')
            fwrite(f, f'set(ZIG {onoff(self.zig)})\n')
            fwrite(f, f'set(ZIG_TARGET "{self.zig_target}")\n')
            fwrite(f, f'set(ZIG_CC_DIR "{self.zig_cc_dir}")\n')
            fwrite(f, f'set(ZIG_ROOT "{self.zig_root}")\n')
            fwrite(f, '\n')

            fwrite(f, '# Target related conditions\n')
            fwrite(
                f,
                f'set(TARGET_IS_NATIVE {onoff(self.target_is_native)})\n',
            )
            fwrite(
                f,
                f'set(TARGET_IS_RUNNABLE {onoff(self.target_is_runnable)})\n',
            )
            fwrite(f, f'set(TARGET_IS_WIN32 {onoff(self.win32)})\n')
            fwrite(f, f'set(TARGET_IS_MSVC {onoff(self.msvc)})\n')
            fwrite(f, f'set(TARGET_IS_ANDROID {onoff(self.android)})\n')
            fwrite(f, f'set(TARGET_IS_UNIX {onoff(self.unix)})\n')
            fwrite(f, f'set(TARGET_IS_APPLE {onoff(self.apple)})\n')
            fwrite(f, f'set(TARGET_IS_IOS {onoff(self.ios)})\n')
            fwrite(f, f'set(TARGET_IS_WASM {onoff(self.wasm)})\n')
            fwrite(f, '\n')
            fwrite(f, '# Suppress warnings\n')
            fwrite(f, 'set(ignoreMe "${CMAKE_VERBOSE_MAKEFILE}")\n')

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

        with open(os.path.join(self.cmake_target_dir, '.environ.mk'), 'wb') as f:
            if cc_exports:
                for line in cc_exports:
                    k, v = list(map(lambda x: x.strip(), line.split('=', 1)))
                    if k.endswith('+'):
                        k = k[:-1].strip()
                        fwrite(f, make_export_paths(k, [v]))
                    else:
                        fwrite(f, f'export {k} = {v}\n')
                fwrite(f, '\n')

            cargo_target = 'CARGO_TARGET_' + self.cargo_target.upper().replace('-', '_')
            if cc:
                fwrite(f, '# LINKER\n')
                fwrite(f, f'export {cargo_target}_LINKER = {linker}\n')
            fwrite(f, '# RUSTFLAGS\n')
            fwrite(
                f,
                f'override {cargo_target}_RUSTFLAGS := {" ".join(linker_options)} $(TARGET_RUSTFLAGS)\n',
            )
            fwrite(f, f'export {cargo_target}_RUSTFLAGS\n')
            fwrite(f, '\n')

            cargo_target_under = self.cargo_target.replace('-', '_')
            if cc:
                fwrite(f, '# AR, CC, CXX, RANLIB, STRIP\n')
                fwrite(f, f'export AR_{cargo_target_under} = {ar}\n')
                fwrite(f, f'export CC_{cargo_target_under} = {cc}\n')
                fwrite(f, f'export CXX_{cargo_target_under} = {cxx}\n')
                fwrite(
                    f,
                    f'export RANLIB_{cargo_target_under} = {ranlib}\n',
                )
                fwrite(f, f'export STRIP_{cargo_target_under} = {strip}\n')
                fwrite(f, '\n')
            fwrite(f, '# ARFLAGS, CFLAGS, CXXFLAGS, RANLIBFLAGS\n')
            fwrite(
                f,
                f'override ARFLAGS_{cargo_target_under} := $(TARGET_ARFLAGS)\n',
            )
            fwrite(f, f'export ARFLAGS_{cargo_target_under}\n')
            fwrite(
                f,
                f'override CFLAGS_{cargo_target_under} := {" ".join(cc_options)} $(TARGET_CFLAGS)\n',
            )
            fwrite(f, f'export CFLAGS_{cargo_target_under}\n')
            fwrite(
                f,
                f'override CXXFLAGS_{cargo_target_under} := {" ".join(cc_options)} $(TARGET_CXXFLAGS)\n',
            )
            fwrite(f, f'export CXXFLAGS_{cargo_target_under}\n')
            fwrite(
                f,
                f'override RANLIBFLAGS_{cargo_target_under} := $(TARGET_RANLIBFLAGS)\n',
            )
            fwrite(f, f'export RANLIBFLAGS_{cargo_target_under}\n')
            fwrite(f, '\n')

            fwrite(f, '# For Rust bingen + libclang\n')
            bindgen_includes = (
                self.enum_prefix_subdirs_of('include', make=True) + self.cxx_includes
            )
            hardening_mode = '-D_LIBCPP_HARDENING_MODE=_LIBCPP_HARDENING_MODE_FAST' + (
                ''
                if self.apple
                else ' -D_LIBCPP_HAS_NO_VENDOR_AVAILABILITY_ANNOTATIONS=1'
            )
            includes_str = ' '.join(f'-I"{x}"' for x in bindgen_includes)
            fwrite(
                f,
                f'override BINDGEN_EXTRA_CLANG_ARGS := $(TARGET_BINDGEN_CLANG_ARGS) {hardening_mode} {includes_str}\n',
            )
            fwrite(f, 'export BINDGEN_EXTRA_CLANG_ARGS\n')
            fwrite(f, '\n')

            fwrite(f, '# For Rust cmake\n')
            fwrite(
                f,
                f'export CMAKE_TOOLCHAIN_FILE_{cargo_target_under} = {self.cmake_target_dir}/.toolchain.cmake\n',
            )
            if self.cmake_generator:
                fwrite(
                    f,
                    f'export CMAKE_GENERATOR_{cargo_target_under} = {self.cmake_generator}\n',
                )
            else:
                fwrite(
                    f,
                    f'unexport CMAKE_GENERATOR_{cargo_target_under}\n',
                )
            fwrite(f, '\n')

            fwrite(f, '# Configure the cross compile pkg-config.\n')
            fwrite(
                f,
                f'export PKG_CONFIG_ALLOW_CROSS = {1 if self.is_cross_compiling else 0}\n',
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
                f'export CARGO_WORKSPACE_DIR = {self.workspace_dir}\n',
            )
            fwrite(f, f'export CMKABE_HOST_TARGET = {self.host.triple}\n')
            fwrite(f, f'export CMKABE_TARGET = {self.cmkabe_target}\n')
            fwrite(f, f'export CMKABE_TARGET_DIR = {self.target_dir}\n')
            fwrite(
                f,
                f'export CMKABE_TARGET_CMAKE_DIR = {self.target_cmake_dir}\n',
            )
            fwrite(
                f,
                f'export CMKABE_TARGET_PREFIX = {self.cmake_target_prefix}\n',
            )
            fwrite(f, f'export CMKABE_TARGET_CC = {self.target_cc}\n')
            fwrite(
                f,
                f'export CMKABE_CARGO_TARGET = {self.cargo_target}\n',
            )
            fwrite(f, f'export CMKABE_ZIG_TARGET = {self.zig_target}\n')
            fwrite(f, 'export CMKABE_DEBUG := $(DEBUG)\n')
            fwrite(f, 'export CMKABE_MINSIZE := $(MINSIZE)\n')
            fwrite(f, 'export CMKABE_DBGINFO := $(DBGINFO)\n')
            fwrite(f, 'export CMKABE_CMAKE_BUILD_TYPE := $(CMAKE_BUILD_TYPE)\n')
            fwrite(f, 'export CMKABE_CMAKE_BUILD_DIR := $(CMAKE_BUILD_DIR)\n')
            fwrite(
                f,
                f'export CMKABE_CARGO_OUT_DIR := {self.cargo_out_dir(make=True)}\n',
            )
            fwrite(
                f,
                f'export CMKABE_MAKE_BUILD_VARS = {";".join(_make_build_vars)}\n',
            )
            fwrite(
                f,
                f'export CMKABE_LINK_DIRS := {os.path.pathsep.join(self.enum_prefix_subdirs_of("lib", make=True))}\n',
            )
            fwrite(
                f,
                f'export CMKABE_INCLUDE_DIRS = {os.path.pathsep.join(self.enum_prefix_subdirs_of("include", make=True))}\n',
            )

        with open(os.path.join(self.cmake_target_dir, '.environ.cmake'), 'wb') as f:
            if cc_exports:
                for line in cc_exports:
                    k, v = list(map(lambda x: x.strip(), line.split('=', 1)))
                    if k.endswith('+'):
                        k = k[:-1].strip()
                        fwrite(f, cmake_export_paths(k, [v]))
                    else:
                        fwrite(f, f'set(ENV{{{k}}} "{v}")\n')
                fwrite(f, '\n')

            fwrite(f, '# AR, CC, CXX, RANLIB, STRIP, RC\n')
            fwrite(f, f'set(TARGET_AR "{ar}")\n')
            fwrite(f, f'set(TARGET_CC "{cc}")\n')
            fwrite(f, f'set(TARGET_CXX "{cxx}")\n')
            fwrite(f, f'set(TARGET_RANLIB "{ranlib}")\n')
            fwrite(f, f'set(TARGET_STRIP "{strip}")\n')
            fwrite(f, f'set(TARGET_RC "{rc}")\n')
            fwrite(f, '\n')

            fwrite(f, '# Configure the cross compile pkg-config.\n')
            fwrite(
                f,
                f'set(ENV{{PKG_CONFIG_ALLOW_CROSS}} "{1 if self.is_cross_compiling else 0}")\n',
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
                f'set(ENV{{CARGO_WORKSPACE_DIR}} "{self.workspace_dir}")\n',
            )
            fwrite(
                f,
                f'set(ENV{{CMKABE_HOST_TARGET}} "{self.host.triple}")\n',
            )
            fwrite(f, f'set(ENV{{CMKABE_TARGET}} "{self.cmkabe_target}")\n')
            fwrite(f, f'set(ENV{{CMKABE_TARGET_DIR}} "{self.target_dir}")\n')
            fwrite(
                f,
                f'set(ENV{{CMKABE_TARGET_CMAKE_DIR}} "{self.target_cmake_dir}")\n',
            )
            fwrite(
                f,
                f'set(ENV{{CMKABE_TARGET_PREFIX}} "{self.cmake_target_prefix}")\n',
            )
            fwrite(f, f'set(ENV{{CMKABE_TARGET_CC}} "{self.target_cc}")\n')
            fwrite(
                f,
                f'set(ENV{{CMKABE_CARGO_TARGET}} "{self.cargo_target}")\n',
            )
            fwrite(f, f'set(ENV{{CMKABE_ZIG_TARGET}} "{self.zig_target}")\n')
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
                f'set(ENV{{CMKABE_CARGO_OUT_DIR}} "{self.cargo_out_dir(cmake=True)}")\n',
            )
            fwrite(
                f,
                f'set(ENV{{CMKABE_MAKE_BUILD_VARS}} "{";".join(_make_build_vars)}")\n',
            )
            fwrite(
                f,
                f'set(ENV{{CMKABE_LINK_DIRS}} "{os.path.pathsep.join(self.enum_prefix_subdirs_of("lib", cmake=True))}")\n',
            )
            fwrite(
                f,
                f'set(ENV{{CMKABE_INCLUDE_DIRS}} "{os.path.pathsep.join(self.enum_prefix_subdirs_of("include", cmake=True))}")\n',
            )

        with open(os.path.join(self.cmake_target_dir, '.toolchain.cmake'), 'wb') as f:
            fwrite(f, 'cmake_minimum_required(VERSION 3.16)\n')
            fwrite(f, '\n')
            fwrite(
                f,
                f'include("{self.cmake_target_dir}/.settings.cmake")\n',
            )
            fwrite(f, f'set(TARGET "{self.cmkabe_target}")\n')
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
