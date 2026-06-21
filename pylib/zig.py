# -*- coding: utf-8 -*-
"""Zig toolchain support utility functions, including cache cleaning and compiler patcher.

================================================================================
Zig Compiler Library Patching (zig_patch) Design & Details
================================================================================

1. Purpose & Motivation:
-------------------------
When building dynamic shared libraries (.dll on Windows, .so on Linux) in hybrid 
Rust + C/C++ projects, the Zig compiler statically links helper runtimes, namely:
  - `libunwind`: C++ exception unwinding runtime.
  - `mingw-w64`: C runtime start files and standard libraries for Windows targets.
  - `compiler_rt`: Low-level target-specific helper functions (like stack probing).

By default, these statically-linked libraries export their internal symbols globally
(e.g., `_Unwind_*`, CRT helper routines, math asm symbols). If multiple dynamic 
libraries in the same process statically link these, it causes:
  - Severe duplicate symbol conflicts at runtime.
  - Pollution of the dynamic library's public API export tables.

To solve this, `zig_patch` modifies the compiler's source libraries on disk to enforce 
internal symbol hiding (`visibility("hidden")` or `-exclude-symbols`).

2. Key Implementation Modules:
-------------------------------
A. Line-Ending Agnostic binary patching (`patch_file`):
   - Prior to matching, any binary text is normalized to LF (`\n`) in memory. 
   - Search, insert, and replacement patterns are also normalized to LF.
   - If modifications are made, the file is written back with its original line 
     endings (CRLF or LF) preserved, preventing patching failures on Windows systems
     with custom Git checkout configurations.

B. Symbol Visibility Hiding for C files (`patch_visibility`):
   - Injects `#pragma GCC visibility push(hidden)` after the last header include 
     directive, and `#pragma GCC visibility pop` at the end of the file.
   - Employs a robust, line-ending agnostic fallback search that automatically 
     detects the end of the last `#include <` or `#include "` line, removing reliance 
     on fragile string matching for standard files.
   - Re-decorates `__declspec(dllimport)` declarations with `__attribute__((visibility("default")))`
     to prevent compiler warnings/errors regarding conflicting visibility attributes.

C. Exclude symbols from Assembly (.S) files (`patch_visibility_mingw_S`):
   - Analyzes assembly files and extracts all global symbol names.
   - Searches for both standard global directives (`.globl`, `.global`) and MinGW 
     macro wrappers (`__MINGW_USYMBOL(...)`).
   - Appends a `.drectve` section to the assembly code instructing the PE linker to
     exclude those symbols from export (`-exclude-symbols:<symbol_name>`), covering 
     both raw and underscore-prefixed symbols for multi-arch compatibility (x86, x64, ARM).

D. Exception Unwinder Hiding (`libunwind`):
   - Patches `assembly.h` and `config.h` in `libunwind` to define `_LIBUNWIND_HIDE_SYMBOLS`.
   - On Windows, this overrides the default behavior of exporting `_Unwind_*` via 
     `__declspec(dllexport)` or `-export:` linker options.

E. OS Compatibility & Idempotency:
   - All routines check for existing patches to prevent redundant edits (idempotent).
   - Dynamically catches `OSError` when symlinking `sysctl.h` on Windows (which requires 
     Developer Mode or elevated permissions), automatically falling back to a robust 
     file copy to ensure the script does not crash.
"""

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
    """Patch a binary/text file in-place by searching and inserting/replacing contents (line-ending agnostic)."""
    with open(filename, "rb") as file:
        content = file.read()

    # Detect line endings and normalize to LF in memory
    has_crlf = b"\r\n" in content
    content_lf = content.replace(b"\r\n", b"\n")
    search_lf = search.replace(b"\r\n", b"\n")
    insert_lf = insert.replace(b"\r\n", b"\n")
    replace_lf = replace.replace(b"\r\n", b"\n") if replace is not None else None

    slices: List[bytes] = []
    changed = False
    temp_content = content_lf

    while count > 0:
        index = temp_content.find(search_lf)
        if index < 0:
            break
        insert_position = index + len(search_lf)
        if (
            temp_content[insert_position : insert_position + len(insert_lf)] != insert_lf
            or replace_lf is not None
        ):
            slices.append(temp_content[:index])
            if replace_lf is not None:
                slices.append(replace_lf)
            else:
                slices.append(temp_content[index:insert_position])
            slices.append(insert_lf)
            changed = True
        else:
            insert_position += len(insert_lf)
            slices.append(temp_content[:insert_position])
        temp_content = temp_content[insert_position:]
        count -= 1
    slices.append(temp_content)

    if changed:
        print("Patching {}".format(filename))
        patched_lf = b"".join(slices)
        content_to_write = patched_lf.replace(b"\n", b"\r\n") if has_crlf else patched_lf
        with open(filename, "wb") as file:
            file.write(content_to_write)
    return changed


def patch_visibility(filename: str) -> bool:
    """Patch symbol visibility in C source files for mingw."""
    dll_import = b"__declspec(dllimport)"
    vis_default = b"__attribute__((visibility(\"default\")))"

    insert = b"\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility push(hidden)\n\n"
    append = b"\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility pop\n"

    # Precise matching targets for headers with conditional compilation blocks.
    # We use LF-only formatting for mapping checks.
    file_map = {
        "crtexewin.c": b"#include <mbctype.h>\n#endif\n",
        "wdirent.c": b"#include \"dirent.c\"\n",
        "ucrtexewin.c": b"#include \"crtexewin.c\"\n",
        "pseudo-reloc.c": b"# define NO_COPY\n#endif\n",
        "thread.c": b"#include \"winpthread_internal.h\"\n",
    }

    with open(filename, "rb") as file:
        content = file.read()

    has_crlf = b"\r\n" in content
    content_lf = content.replace(b"\r\n", b"\n")

    # If the patch is already applied, do not apply it again.
    if insert in content_lf:
        return False

    if dll_import in content_lf and vis_default not in content_lf:
        content_lf = content_lf.replace(
            dll_import, dll_import + b" " + vis_default
        )

    insert_position = 0
    search = file_map.get(os.path.basename(filename))
    if search:
        index = content_lf.find(search)
        if index >= 0:
            insert_position = index + len(search)

    # Fallback auto-detection if not specified in mapping or pattern not found
    if insert_position == 0:
        # Locate the last #include directive in the file (covers <...> and "...")
        last_include_idx = max(content_lf.rfind(b"#include <"), content_lf.rfind(b"#include \""))
        if last_include_idx >= 0:
            eol_idx = content_lf.find(b"\n", last_include_idx)
            if eol_idx >= 0:
                insert_position = eol_idx + 1

    # Fallback to the top of the file if no includes are found
    if insert_position == 0:
        insert_position = 0

    print("Patching {}".format(filename))
    patched_lf = (
        content_lf[:insert_position] +
        insert +
        content_lf[insert_position:] +
        append
    )

    content_to_write = patched_lf.replace(b"\n", b"\r\n") if has_crlf else patched_lf
    with open(filename, "wb") as file:
        file.write(content_to_write)
    return True


def patch_visibility_mingw_S(filename: str) -> bool:
    """Patch symbol visibility in assembly (.S) files for mingw."""
    pattern_mingw = re.compile(rb"\b__MINGW_USYMBOL\((\w+)\)")
    pattern_globl = re.compile(rb"\.(?:globl|global)\s+([a-zA-Z0-9_]+)")
    symbols: Set[bytes] = set()

    with open(filename, "rb") as file:
        content = file.read()

    has_crlf = b"\r\n" in content
    content_lf = content.replace(b"\r\n", b"\n")

    for line in content_lf.splitlines():
        # Match MinGW symbol macro wrapper
        for match in pattern_mingw.findall(line):
            symbols.add(match.strip())
        # Match standard assembly global declarations
        for match in pattern_globl.findall(line):
            sym = match.strip()
            if not sym.startswith(b"__MINGW_USYMBOL"):
                symbols.add(sym)

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

    if content_lf.endswith(code):
        return False

    print("Patching {}".format(filename))
    patched_lf = content_lf + code
    content_to_write = patched_lf.replace(b"\n", b"\r\n") if has_crlf else patched_lf
    with open(filename, "wb") as file:
        file.write(content_to_write)
    return True


def zig_patch(zig_root: Optional[str] = None) -> None:
    """Patch Zig source libraries to hide internal exports (such as libunwind, mingw32)."""
    if not zig_root:
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
        try:
            os.symlink(
                os.path.relpath(sys_ctl_h_src, os.path.dirname(sys_ctl_h)),
                sys_ctl_h,
            )
        except OSError:
            # Fallback to copy if symlink creation is not permitted (e.g., on Windows without Developer Mode)
            shutil.copy2(sys_ctl_h_src, sys_ctl_h)

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
