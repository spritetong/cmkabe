# -*- coding: utf-8 -*-
"""Zig toolchain support utility functions, including cache cleaning and mingw patch."""

import glob
import json
import os
import re
import shutil
import subprocess
import sys
from typing import Callable, List, Optional, Set, Tuple

from cmk.pylib.sys_utils import EXE_EXT, copy_env_for_cc

EFAIL: int = 1


def zig_clean_cache() -> None:
    """Clean the global Zig cache directory."""
    zig_env = json.loads(
        subprocess.run(
            ["zig" + EXE_EXT, "env"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout
    )
    global_cache = zig_env.get("global_cache_dir")
    if global_cache and os.path.isdir(global_cache):
        shutil.rmtree(global_cache, ignore_errors=True)


def patch_file(
    filename: str,
    search: bytes,
    insert: bytes = b"",
    replace: Optional[bytes] = None,
    count: int = 1,
) -> bool:
    """Patch a binary/text file in-place by searching and inserting/replacing contents."""
    with open(filename, "rb") as file:
        content = file.read()
    slices: List[bytes] = []
    changed = False
    while count > 0:
        index = content.find(search)
        if index < 0:
            break
        insert_position = index + len(search)
        if (
            content[insert_position : insert_position + len(insert)] != insert
            or replace is not None
        ):
            slices.append(content[:index])
            if replace is not None:
                slices.append(replace)
            else:
                slices.append(content[index:insert_position])
            slices.append(insert)
            changed = True
        else:
            insert_position += len(insert)
            slices.append(content[:insert_position])
        content = content[insert_position:]
        count -= 1
    slices.append(content)
    if changed:
        print("Patching {}".format(filename))
        with open(filename, "wb") as file:
            for s in slices:
                file.write(s)
    return changed


def patch_visibility(filename: str) -> bool:
    """Patch symbol visibility in C source files for mingw."""
    dll_import = b"__declspec(dllimport)"
    vis_default = b"__attribute__((visibility(\"default\")))"

    insert = b"\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility push(hidden)\n\n"
    append = b"\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility pop\n"

    file_map = {
        "crtexewin.c": b"#include <mbctype.h>\n#endif\n",
        "wdirent.c": b"#include \"dirent.c\"\n",
        "ucrtexewin.c": b"#include \"crtexewin.c\"\n",
        "pseudo-reloc.c": b"# define NO_COPY\n#endif\n",
        "thread.c": b"#include \"winpthread_internal.h\"\n",
    }

    with open(filename, "rb") as file:
        content = file.read()

    if dll_import in content and vis_default not in content:
        content = content.replace(
            dll_import, dll_import + b" " + vis_default
        )

    insert_position = 0
    search = file_map.get(os.path.basename(filename))
    if search:
        index = content.find(search)
        if index >= 0:
            insert_position = index + len(search)
    if insert_position == 0 and (
        content.find(b"<windows.h>") >= 0
        or content.find(b"<stdlib.h>") >= 0
        or content.find(b"<wchar.h>") >= 0
    ):
        index = content.rfind(b"#include <")
        if index >= 0:
            insert_position = index + content[index:].find(b"\n") + 1

    if content[insert_position : insert_position + len(insert)] == insert:
        return False

    print("Patching {}".format(filename))
    with open(filename, "wb") as file:
        file.write(content[:insert_position])
        file.write(insert)
        file.write(content[insert_position:])
        file.write(append)
    return True


def patch_visibility_mingw_S(filename: str) -> bool:
    """Patch symbol visibility in assembly (.S) files for mingw."""
    pattern = re.compile(rb"\b__MINGW_USYMBOL\((\w+)\)")
    symbols: Set[bytes] = set()

    with open(filename, "rb") as file:
        content = file.read()
    for line in content.splitlines():
        matches = pattern.findall(line)
        for match in matches:
            symbols.add(match.strip())
    sorted_symbols = list(sorted(symbols)) + [
        b"_" + x for x in sorted(symbols)
    ]
    if not sorted_symbols:
        return False
    code = (
        b"\n/* XPATCH: do not export symbols. */\n.section .drectve,\"yni\"\n"
    )
    code += b"\n".join(
        '.ascii " -exclude-symbols:{} "'.format(x.decode()).encode()
        for x in sorted_symbols
    )
    code += b"\n"

    if content.endswith(code):
        return False

    print("Patching {}".format(filename))
    with open(filename, "wb") as file:
        file.write(content)
        file.write(code)
    return True


def zig_patch() -> None:
    """Patch Zig source libraries to hide internal exports (such as libunwind, mingw32)."""
    zig_path = shutil.which("zig" + EXE_EXT)
    if not zig_path:
        return
    zig_root = os.path.realpath(os.path.dirname(zig_path))
    any_linux_any = os.path.join(
        zig_root, "lib", "libc", "include", "any-linux-any"
    )
    lib_src_patched = False

    # 1. fix `lib/compiler_rt/stack_probe.zig` with Zig <= 0.13.
    if patch_file(
        os.path.join(zig_root, "lib", "compiler_rt", "stack_probe.zig"),
        b".linkage = strong_linkage",
        b"",
        replace=b".linkage = linkage",
        count=sys.maxsize,
    ):
        lib_src_patched = True

    # 2. Set symbol visibility to `hidden` in `libunwind`.
    libunwind_src = os.path.join(zig_root, "lib", "libunwind", "src")
    for file, tag in [
        ("assembly.h", "UNWIND_ASSEMBLY_H"),
        ("config.h", "LIBUNWIND_CONFIG_H"),
    ]:
        if patch_file(
            os.path.join(libunwind_src, file),
            b"#define " + tag.encode(),
            b"\n\n/* XPATCH: do not export symbols. */\n#define _LIBUNWIND_HIDE_SYMBOLS",
        ):
            lib_src_patched = True
    for search, insert in [
        (
            b"#define _LIBUNWIND_HIDE_SYMBOLS\n",
            b"""#if defined(__MINGW32__) && defined(_LIBUNWIND_HIDE_SYMBOLS)
#define XPATCH_HIDDEN_SYMBOL(name)                                             \\
  .section .drectve,"yni" SEPARATOR                                            \\
  .ascii " -exclude-symbols:", #name, " " SEPARATOR                            \\
  .text
#else
#define XPATCH_HIDDEN_SYMBOL(name)
#endif
""",
        ),
        (
            b"""#if defined(__MINGW32__)
#define WEAK_ALIAS(name, aliasname)                                            \\
""",
            b"""  XPATCH_HIDDEN_SYMBOL(aliasname) SEPARATOR                                    \\
""",
        ),
        (
            b"""#else
#define DEFINE_LIBUNWIND_FUNCTION(name)                                        \\
""",
            b"""  XPATCH_HIDDEN_SYMBOL(name) SEPARATOR                                         \\
""",
        ),
    ]:
        if patch_file(
            os.path.join(libunwind_src, "assembly.h"), search, insert
        ):
            lib_src_patched = True

    # 3. Set symbol visibility to `hidden` in `mingw32`.
    for libc in ["mingw"]:
        zig_libc = os.path.join(zig_root, "lib", "libc", libc)
        mingw_libsrc = "/mingw/libsrc/"
        for ext, patch_func in [
            ("c", patch_visibility),
            ("S", patch_visibility_mingw_S),
        ]:
            # Specify type for glob files to satisfy type checks
            glob_files: List[str] = glob.glob(
                "{}/**/*.{}".format(zig_libc, ext), recursive=True
            )
            for file_path in glob_files:
                if mingw_libsrc not in file_path.replace("\\", "/"):
                    # Use a cast-like helper or exact annotation matching
                    func: Callable[[str], bool] = patch_func
                    if func(file_path):
                        lib_src_patched = True

    # 4. <sys/sysctl.h> is required by ffmpeg 6.0
    sys_ctl_h = os.path.join(any_linux_any, "sys", "sysctl.h")
    sys_ctl_h_src = os.path.join(any_linux_any, "linux", "sysctl.h")
    if not os.path.exists(sys_ctl_h) and os.path.isfile(sys_ctl_h_src):
        os.makedirs(os.path.dirname(sys_ctl_h), exist_ok=True)
        os.symlink(
            os.path.relpath(sys_ctl_h_src, os.path.dirname(sys_ctl_h)),
            sys_ctl_h,
        )

    if lib_src_patched:
        zig_clean_cache()


def zig_dll2lib(
    dll_file: str, out_path: Optional[str] = None, force: bool = False
) -> int:
    """Generate a MSVC-compatible import library (.lib) from a DLL using pefile and zig dlltool."""
    try:
        import pefile
    except ImportError:
        print(
            "`pefile` is not installed. Try: pip install pefile",
            file=sys.stderr,
        )
        return EFAIL

    # Load the DLL file
    pe = pefile.PE(dll_file)

    # Mapping of PE machine types to `dlltool` machine types
    machine_types = {
        0x014C: "i386",  # x86
        0x8664: "i386:x86-64",  # x64 (AMD64)"
        0x01C4: "arm",  # ARMv7
        0xAA64: "arm64",  # ARM64
    }
    machine = machine_types.get(pe.FILE_HEADER.Machine, None)
    if machine is None:
        print(
            "Unsupported machine type {} in {}".format(
                pe.FILE_HEADER.Machine, dll_file
            ),
            file=sys.stderr,
        )
        return EFAIL

    # Check if the DLL has an export directory
    if not hasattr(pe, "DIRECTORY_ENTRY_EXPORT"):
        print(
            "No export symbols found in {}".format(dll_file),
            file=sys.stderr,
        )
        return EFAIL

    dll_name = os.path.splitext(os.path.basename(dll_file))[0]
    out_dir = out_path or "."
    out_file = dll_name + ".lib"
    if out_path:
        if out_path.endswith(".lib") or out_path.endswith(".a"):
            out_dir = os.path.dirname(out_path) or "."
            out_file = os.path.basename(out_path)

    def_file = os.path.splitext(out_file)[0] + ".def"
    if os.path.exists(os.path.join(out_dir, out_file)) and not force:
        print(
            '"{}" already exists in "{}"'.format(out_file, out_dir),
            file=sys.stderr,
        )
        return EFAIL

    with open(os.path.join(out_dir, def_file), "wb") as f:
        f.write("LIBRARY {}\r\n".format(dll_name).encode())
        f.write(b"EXPORTS\r\n")
        for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            name = symbol.name.decode() if symbol.name else None
            ordinal = symbol.ordinal if symbol.ordinal else None
            if name is not None:
                if ordinal is not None:
                    f.write("    {} @{}\r\n".format(name, ordinal).encode())
                else:
                    f.write("    {}\r\n".format(name).encode())

    subprocess.run(
        [
            "zig" + EXE_EXT,
            "dlltool",
            "-m",
            machine,
            "-D",
            dll_file,
            "-d",
            os.path.join(out_dir, def_file),
            "-l",
            os.path.join(out_dir, out_file),
        ],
        check=True,
    )
    return 0
