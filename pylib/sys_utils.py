# -*- coding: utf-8 -*-
"""System utility functions for building and cross-compilation."""

import os
import platform
import re
import sys
from typing import Dict, List, Tuple, Union, Optional, Any, Set, Tuple

EXE_EXT: str = ".exe" if os.name == "nt" else ""

GCC_ENV_KEYS: Tuple[str, ...] = (
    "BINDGEN_EXTRA_CLANG_ARGS",
    "CPATH",
    "C_INCLUDE_PATH",
    "CPLUS_INCLUDE_PATH",
    "OBJC_INCLUDE_PATH",
    "COMPILER_PATH",
    "LIBRARY_PATH",
)

HOST_SYSTEM_MAP: Tuple[Tuple[str, str], ...] = (
    ("cygwin_nt", "cygwin"),
    ("msys_nt", "mingw"),
    ("mingw32_nt", "mingw"),
    ("mingw64_nt", "mingw"),
    ("darwin", "macos"),
)

# Host ARCH -> Rust ARCH
HOST_ARCH_MAP: Dict[str, str] = {
    "x86": "i686",
    "i686": "i686",
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "aarch64": "aarch64",
}

VENDOR_LIST: Tuple[str, ...] = ("pc", "apple", "sun", "nvidia", "unknown")
OS_LIST: Tuple[str, ...] = (
    "windows",
    "linux",
    "macos",
    "darwin",
    "ios",
    "freebsd",
    "netbsd",
    "solaris",
    "redox",
    "fuchsia",
    "cuda",
    "uefi",
    "none",
)
OS_PREFIXES: Tuple[str, ...] = ("wasi",)
ENV_LIST: Tuple[str, ...] = ("msvc", "android", "gnu", "musl", "sgx", "elf", "ohos")
ENV_PREFIXES: Tuple[str, ...] = ("msvc", "android", "gnu", "musl")
ENV_SUFFIXES: Tuple[str, ...] = ("eabi", "eabihf", "llvm")

RUST_ARCH_MAP: Dict[str, str] = {
    "arm": "armv7",  # Upgrade arm to armv7
    "armv7": "armv7",
    "armv7a": "armv7",
    "thumb": "thumbv7neon",
    "thumbv7neon": "thumbv7neon",
    "arm64": "aarch64",
    "aarch64": "aarch64",
    "x86": "i686",
    "i586": "i686",  # Upgrade i586 to i686
    "i686": "i686",
    "win32": "i686",
    "x64": "x86_64",
    "x86_64": "x86_64",
}

# Rust ARCH -> MSVC ARCH
MSVC_ARCH_MAP: Dict[str, str] = {
    "aarch64": "ARM64",
    "i586": "Win32",
    "i686": "Win32",
    "x86_64": "x64",
}

# Rust ARCH -> Visual Studio ARCH
VSTOOLS_ARCH_MAP: Dict[str, str] = {
    "aarch64": "arm64",
    "i586": "x86",
    "i686": "x86",
    "x86_64": "x64",
}

# Rust ARCH -> Android ARCH
ANDROID_ARCH_MAP: Dict[str, str] = {
    "i686": "i686",
    "x86_64": "x86_64",
    "armv7": "armv7a",
    "thumbv7neon": "armv7a",
    "aarch64": "aarch64",
}

# Rust ARCH -> Android ABI (JNI Directory Name)
ANRDOID_ABI_MAP: Dict[str, str] = {
    "i686": "x86",
    "x86_64": "x86_64",
    "armv7": "armeabi-v7a",
    "thumbv7neon": "armeabi-v7a",
    "aarch64": "arm64-v8a",
}

# Rust ARCH -> Apple ARCH
APPLE_ARCH_MAP: Dict[str, str] = {
    "x86_64": "x86_64",
    "aarch64": "aarch64",
}

# Rust ARCH -> Zig ARCH
ZIG_ARCH_MAP: Dict[str, str] = {
    "i686": "x86",
    "x86_64": "x86_64",
    "armv7": "arm",
    "thumbv7neon": "thumb",
    "aarch64": "aarch64",
}

# Rust OS -> Zig OS
ZIG_OS_MAP: Dict[str, str] = {
    "darwin": "macos",
    "ios-sim": "ios",
}


def normpath(path: str) -> str:
    """Normalize path using forward slashes for cross-platform consistency."""
    return os.path.normpath(path).replace("\\", "/")


def need_update(source_file: str, dest_file: str) -> bool:
    """Check if the dest_file needs to be updated (does not exist or older than source)."""
    return not os.path.isfile(dest_file) or (
        os.path.getmtime(dest_file) < os.path.getmtime(source_file)
    )


def join_triple(arch: str, vendor: str, os_name: str, env: str) -> str:
    """Join target triple components into a standard string representation."""
    return "{}{}{}{}{}{}{}".format(
        arch,
        "-" if vendor else "",
        vendor or "",
        "-" if os_name else "",
        os_name or "",
        "-" if env else "",
        env or "",
    )


def parse_triple(target_triple: str) -> Tuple[str, str, str, str]:
    """Parse a target triple string into (arch, vendor, os, env)."""
    triple = target_triple.lower().split("-")

    # Fix up '-ios-sim'
    if len(triple) > 2 and triple[-1] == "sim":
        triple[-2] += "-" + triple[-1]
        triple = triple[:-1]

    arch: str = triple[0]
    vendor: str = ""
    os_str: str = ""
    env_str: str = ""

    def is_vendor_str(s: str) -> bool:
        return s in VENDOR_LIST

    def is_os_str(s: str) -> bool:
        return s in OS_LIST or any(s.startswith(x) for x in OS_PREFIXES)

    def is_env_str(s: str) -> bool:
        return (
            s in ENV_LIST
            or any(s.startswith(x) for x in ENV_PREFIXES)
            or any(s.endswith(x) for x in ENV_SUFFIXES)
        )

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

    rust_arch = RUST_ARCH_MAP.get(arch, arch)
    if "windows" in target_triple and (
        os_str != "windows" or rust_arch not in MSVC_ARCH_MAP
    ):
        raise ValueError("Invalid ARCH for Windows: {}".format(target_triple))
    if "android" in target_triple and (
        not env_str.startswith("android")
        or os_str != "linux"
        or rust_arch not in ANDROID_ARCH_MAP
    ):
        raise ValueError("Invalid ARCH for Android: {}".format(target_triple))
    if "apple" in target_triple and (
        vendor != "apple" and rust_arch not in APPLE_ARCH_MAP
    ):
        raise ValueError("Invalid ARCH for Apple: {}".format(target_triple))

    parsed_triple = join_triple(arch, vendor, os_str, env_str)
    if not arch or not os_str or parsed_triple != target_triple:
        raise ValueError("Invalid target triple: {}".format(target_triple))

    return (arch, vendor, os_str, env_str)


def host_target_info() -> Dict[str, Any]:
    """Retrieve details about the host target system."""
    # (compatible with Make & CMake) Windows, Linux, Darwin
    host_system: str = "Windows" if os.name == "nt" else platform.uname()[0]
    # (not for Cargo) windows, linux, macos, mingw, cygwin
    target_system: str = ""
    # windows, unix, wasm
    target_family: str = ""
    # windows, linux, macos, android, ios ..., none
    target_os: str = ""
    # i686(i586, ???x86), x86_64, arm, aarch64, ...
    target_arch: str = ""
    # pc, apple, fortanix, unknown
    target_vendor: str = ""
    cargo_target_vendor: str = ""
    # msvc, gnu, musl, sgx, ...
    target_env: str = ""
    target_pointer_width: int = 64
    target_endian: str = sys.byteorder
    target_feature: str = ""

    # target_system <- platform.system()
    if os.environ.get("MSYSTEM") in ("MSYS", "MINGW32", "MINGW64"):
        target_system = "mingw"
    else:
        target_system = platform.system().lower()
        for k, v in HOST_SYSTEM_MAP:
            if target_system.startswith(k):
                target_system = v
                break

    # target_family, target_os
    if target_system in ("windows", "cygwin", "mingw"):
        target_family = "windows"
        target_os = "windows"
    else:
        target_family = "unix"
        target_os = target_system

    # target_pointer_width, target_arch
    machine = platform.machine()
    if "64" not in machine:
        target_pointer_width = 32
    target_arch = HOST_ARCH_MAP.get(machine.lower(), "")
    if not target_arch:
        raise RuntimeError("Not supported machine architecture: {}".format(machine))

    # target_vendor
    if target_os == "windows":
        target_vendor = "pc"
    elif target_system == "macos":
        target_vendor = "apple"
    elif target_os == "linux":
        target_vendor = "pc"
        cargo_target_vendor = "unknown"
    else:
        target_vendor = "unknown"

    if not cargo_target_vendor:
        cargo_target_vendor = target_vendor

    # target_env
    if target_os == "windows":
        target_env = "msvc"
    elif target_system in ("linux", "cygwin", "mingw"):
        target_env = "gnu"

    # target_triple
    target_triple = join_triple(target_arch, target_vendor, target_os, target_env)
    cargo_target_triple = join_triple(
        target_arch, cargo_target_vendor, target_os, target_env
    )

    return {
        "host_system": host_system,
        "system": target_system,
        "family": target_family,
        "os": target_os,
        "arch": target_arch,
        "vendor": target_vendor,
        "env": target_env,
        "pointer_width": target_pointer_width,
        "endian": target_endian,
        "feature": target_feature,
        "triple": target_triple,
        "cargo_triple": cargo_target_triple,
    }


def win2wsl_path(path: str) -> str:
    """Convert a Windows file path to a WSL path."""
    if os.path.isabs(path):
        path = os.path.abspath(path)
    path = path.replace("\\", "/")
    drive_path = path.split(":", 1)
    if len(drive_path) > 1 and len(drive_path[0]) == 1 and drive_path[0].isalpha():
        path = "/mnt/{}{}".format(drive_path[0].lower(), drive_path[1]).rstrip("/")
    return path


def wsl2win_path(path: str) -> str:
    """Convert a WSL path to a Windows file path."""
    if os.path.isabs(path):
        path = os.path.abspath(path)
    path = path.replace("\\", "/")
    if len(path) >= 6 and path.startswith("/mnt/") and path[5].isalpha():
        if len(path) == 6:
            path = path[5].upper() + ":/"
        elif path[6] == "/":
            path = "{}:{}".format(path[5].upper(), path[6:])
    return path


def lock_file(path: Optional[str] = None, unlock: Optional[Any] = None) -> Any:
    """Cross-platform locking/unlocking of a lock file."""
    if unlock is None:
        assert path is not None
        dir_name = os.path.dirname(path)
        if dir_name and not os.path.isdir(dir_name):
            os.makedirs(dir_name, exist_ok=True)
        f = open(path, "a+")
    else:
        f = unlock

    try:
        # Posix based file locking (Linux, Ubuntu, MacOS, etc.)
        import fcntl

        if unlock is None:
            fcntl.lockf(f, fcntl.LOCK_EX)
            return f
        else:
            fcntl.lockf(f, fcntl.LOCK_UN)
            f.close()
            return None
    except ModuleNotFoundError:
        # Windows file locking
        import msvcrt

        def get_file_size(f_obj: Any) -> int:
            return os.path.getsize(os.path.realpath(f_obj.name))

        if unlock is None:
            msvcrt.locking(f.fileno(), msvcrt.LK_RLCK, get_file_size(f))
            return f
        else:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, get_file_size(f))
            f.close()
            return None


def ndk_root(check_env: bool = False) -> str:
    """Locate the Android NDK root directory."""
    if check_env:
        ndk_root_env = os.environ.get("ANDROID_NDK_ROOT", "")
        if ndk_root_env and os.path.isdir(ndk_root_env):
            os.environ["ANDROID_NDK_HOME"] = ndk_root_env
            return ndk_root_env

    sdk_dir = ""
    if "ANDROID_HOME" in os.environ:
        sdk_dir = os.path.join(os.environ["ANDROID_HOME"], "ndk")
    elif sys.platform != "win32":
        for directory in ("/opt/ndk", "/opt/android/ndk", "/opt/android/sdk/ndk"):
            if os.path.isdir(directory):
                sdk_dir = directory
                break

    if not sdk_dir:
        print(
            "The environment variable `ANDROID_HOME` is not set.",
            file=sys.stderr,
        )
        return ""

    try:
        pattern1 = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:\.\w+)?$")
        pattern2 = re.compile(r"^android-ndk-r(\d+)([a-z]+)$")
        ndk_dirs: List[Tuple[str, List[int]]] = []
        for name in os.listdir(sdk_dir):
            if not os.path.isfile(
                os.path.join(
                    sdk_dir, name, "build", "cmake", "android.toolchain.cmake"
                )
            ):
                continue
            group = pattern1.match(name)
            if group:
                ndk_dirs.append(
                    (name, [int(group[1]), int(group[2]), int(group[3])])
                )
                continue
            group = pattern2.match(name)
            if group:
                ndk_dirs.append(
                    (
                        name,
                        [
                            int(group[1]),
                            int(
                                "".join(
                                    str(ord(x) + ord("0") - ord("a"))
                                    for x in group[2]
                                )
                            ),
                            0,
                        ],
                    )
                )
                continue
        if ndk_dirs:
            directory_name, _ = sorted(
                ndk_dirs, key=lambda x: x[1], reverse=True
            )[0]
            ndk_root_path = os.path.join(sdk_dir, directory_name).replace(
                "\\", "/"
            )
            if check_env:
                os.environ["ANDROID_NDK_ROOT"] = ndk_root_path
                os.environ["ANDROID_NDK_HOME"] = ndk_root_path
            return ndk_root_path
    except OSError:
        pass
    return ""


def copy_env_for_cc() -> Dict[str, str]:
    """Return a copy of current environment scrubbed of generic compiler flags."""
    return {
        k: v for k, v in os.environ.items() if k not in GCC_ENV_KEYS
    }
