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
   - Injects `#pragma GCC visibility push(hidden)` and `#pragma GCC visibility pop` into C files.
   - Re-decorates `__declspec(dllimport)` declarations with `__attribute__((visibility("default")))`
     to prevent compiler warnings/errors regarding conflicting visibility attributes.
   - Fallback auto-detection employs a robust preprocessor-aware logic that:
     1. Strips comments and string/character literals (`_clean_c_code`) to prevent them from interfering.
     2. Identifies the first code block boundary (`limit_line_idx` based on `{`) to ignore `#include`s inside functions.
     3. Checks if open conditional preprocessor blocks at the last include exit before the code block begins.
     4. If they exit, pushes visibility outside the conditional block and pops at the end of the file.
     5. If they wrap function definitions, balances the push/pop pairs locally inside each branch (e.g. `#if`, `#elif`, `#else`), ensuring correct scoping and matching regardless of which compile-time path is taken.

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
from typing import Callable, Dict, List, Optional, Set

from .sys_utils import EXE_EXT, HostTargetInfo, copy_env_for_cc, need_update

EFAIL: int = 1


def zig_build_wrapper(
    zig_root: Optional[str] = None,
    zig_cc_dir: Optional[str] = None,
    prefix: str = 'zig',
    force: bool = False,
    vcpkg_root: Optional[str] = None,
):
    # Zig root path
    if not zig_root:
        zig_path = shutil.which(f'zig{EXE_EXT}')
        if not zig_path:
            raise FileNotFoundError('`zig` is not found')
    else:
        zig_path = f'{zig_root}/zig{EXE_EXT}'

    cmkabe_home = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    src = os.path.join(cmkabe_home, 'zig-wrapper', 'main.zig')

    if not zig_cc_dir:
        if vcpkg_root:
            zig_cc_dir = os.path.join(
                vcpkg_root,
                'xpatch',
                '.cache',
                'zig',
                HostTargetInfo.vcpkg_host_triplet(),
            )
        else:
            raise ValueError('`zig_cc_dir` is not set')
    os.makedirs(zig_cc_dir, exist_ok=True)

    exe = os.path.join(zig_cc_dir, f'zig-wrapper{EXE_EXT}')

    need_rebuild = force or any(
        need_update(zf, exe)
        for zf in glob.glob(
            os.path.join(os.path.dirname(src), '**/*.zig'), recursive=True
        )
    )
    if need_rebuild:
        if vcpkg_root:
            if os.path.exists(exe):
                os.unlink(exe)
            for file in glob.glob(os.path.join(zig_cc_dir, f'{prefix}-*')):
                if os.path.exists(file):
                    os.unlink(file)
        else:
            for file in glob.glob(os.path.join(zig_cc_dir, '*')):
                if not os.path.isdir(file):
                    os.unlink(file)

        # Compile wrapper using zig build-exe with quoted -femit-bin
        subprocess.run(
            [
                f'zig{EXE_EXT}',
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
        for file in glob.glob(os.path.join(zig_cc_dir, exe + '.*')):
            os.unlink(file)

        for name in [
            'ar',
            'gcc' if vcpkg_root else 'cc',
            'g++' if vcpkg_root else 'c++',
            'dlltool',
            'lib',
            'link',
            'ranlib',
            'objcopy',
            'rc',
            'windres',
        ]:
            dst = os.path.join(zig_cc_dir, f'{prefix}-{name}{EXE_EXT}')
            if os.path.lexists(dst):
                os.unlink(dst)
            try:
                os.symlink(os.path.basename(exe), dst)
            except OSError:
                shutil.copy2(exe, dst)
        for name in ['dlltool', 'windres']:
            dst = os.path.join(zig_cc_dir, f'{name}{EXE_EXT}')
            if os.path.lexists(dst):
                os.unlink(dst)
            try:
                os.symlink(os.path.basename(exe), dst)
            except OSError:
                shutil.copy2(exe, dst)
    return 0


def zig_clean_cache(zig_root: Optional[str] = None, verbose: bool = False) -> None:
    """Clean the global Zig cache directory."""
    import ast

    zig_exe = (
        os.path.join(zig_root, f'zig{EXE_EXT}')
        if zig_root and os.path.isdir(zig_root)
        else f'zig{EXE_EXT}'
    )
    try:
        res = subprocess.run(
            [zig_exe, 'env'],
            capture_output=True,
            check=True,
            text=True,
        )
        stdout = res.stdout
    except Exception as e:
        print(f'[WARNING] Failed to run `zig env`: {e}', file=sys.stderr)
        return

    global_cache = None
    try:
        zig_env = json.loads(stdout)
        global_cache = zig_env.get('global_cache_dir')
    except json.JSONDecodeError:
        # Fallback to parsing Zig struct literal format using regex
        match = re.search(r'\.global_cache_dir\s*=\s*("[^"]*")', stdout)
        if match:
            try:
                global_cache = ast.literal_eval(match.group(1))
            except Exception:
                global_cache = match.group(1).strip('"')

    if verbose and global_cache:
        clean_cache_path = global_cache.replace('\\', '/')
        print(f'Removing {clean_cache_path}')

    if global_cache and os.path.isdir(global_cache):
        shutil.rmtree(global_cache, ignore_errors=True)


def patch_file(
    filename: str,
    search: bytes,
    insert: bytes = b'',
    replace: Optional[bytes] = None,
    count: int = 1,
) -> bool:
    """Patch a binary/text file in-place by searching and inserting/replacing contents (line-ending agnostic)."""
    with open(filename, 'rb') as file:
        content = file.read()

    # Detect line endings and normalize to LF in memory
    has_crlf = b'\r\n' in content
    content_lf = content.replace(b'\r\n', b'\n')
    search_lf = search.replace(b'\r\n', b'\n')
    insert_lf = insert.replace(b'\r\n', b'\n')
    replace_lf = replace.replace(b'\r\n', b'\n') if replace is not None else None

    slices: List[bytes] = []
    changed = False
    temp_content = content_lf

    while count > 0:
        index = temp_content.find(search_lf)
        if index < 0:
            break
        insert_position = index + len(search_lf)
        if (
            temp_content[insert_position : insert_position + len(insert_lf)]
            != insert_lf
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
        print(f'Patching {filename}')
        patched_lf = b''.join(slices)
        content_to_write = (
            patched_lf.replace(b'\n', b'\r\n') if has_crlf else patched_lf
        )
        with open(filename, 'wb') as file:
            file.write(content_to_write)
    return changed


def _clean_c_code(content: bytes) -> bytes:
    """Strip C-style comments, string literals, and char literals from content, preserving line layout."""
    out = bytearray(content)
    n = len(content)
    i = 0
    in_line_comment = False
    in_block_comment = False
    in_string = False
    in_char = False

    while i < n:
        if (in_string or in_char) and content[i] == ord('\\'):
            i += 2
            continue

        if in_line_comment:
            if content[i] == ord('\n'):
                in_line_comment = False
            else:
                out[i] = ord(' ')
        elif in_block_comment:
            if content[i : i + 2] == b'*/':
                out[i] = ord(' ')
                out[i + 1] = ord(' ')
                in_block_comment = False
                i += 1
            elif content[i] != ord('\n'):
                out[i] = ord(' ')
        elif in_string:
            if content[i] == ord('"'):
                in_string = False
            elif content[i] != ord('\n'):
                out[i] = ord(' ')
        elif in_char:
            if content[i] == ord("'"):
                in_char = False
            elif content[i] != ord('\n'):
                out[i] = ord(' ')
        else:
            if content[i : i + 2] == b'//':
                out[i] = ord(' ')
                out[i + 1] = ord(' ')
                in_line_comment = True
                i += 1
            elif content[i : i + 2] == b'/*':
                out[i] = ord(' ')
                out[i + 1] = ord(' ')
                in_block_comment = True
                i += 1
            elif content[i] == ord('"'):
                in_string = True
            elif content[i] == ord("'"):
                in_char = True
        i += 1
    return bytes(out)


def patch_visibility(filename: str) -> bool:
    """Patch symbol visibility in C source files for mingw.

    This function automatically injects `#pragma GCC visibility push(hidden)` and
    `#pragma GCC visibility pop` to enforce internal visibility on mingw runtime libraries.

    Implementation Details:
      1. Strips comments, string and character literals (retaining line count/layout)
         using `_clean_c_code` to make preprocessor token tracking robust.
      2. Finds the line of the first code block start (`limit_line_idx` containing `{`)
         and restricts parsing to lines before it, ignoring any `#include` directives
         inside function scopes.
      3. Parses the preprocessor stack state at the last valid `#include` line.
      4. Branching decisions:
         a. Exitable conditional (header-only block): If the outermost conditional block
            closes before `limit_line_idx`, it places the `push(hidden)` directly after its
            `#endif` (exiting the conditional scope) and appends `pop` to the end of the file.
         b. Wrapped / branching conditional: If the block wraps function/global definitions,
            we place the visibility boundary inside it, balancing it across all sibling branches:
              - `push` after the last include.
              - `pop` before any `#elif` or `#else` sibling lines at that depth.
              - `push` after each sibling branch directive.
              - `pop` before the closing `#endif` of that conditional block.
      5. Reconstructs the C source file line-by-line using the computed insertion points.
    """
    dll_import = b'__declspec(dllimport)'
    vis_default = b'__attribute__((visibility("default")))'

    insert = b'\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility push(hidden)\n\n'
    append = b'\n/* XPATCH: do not export symbols. */\n#pragma GCC visibility pop\n'

    # Precise matching targets for headers with conditional compilation blocks.
    # We use LF-only formatting for mapping checks.
    file_map: Dict[str, bytes] = {
        # 'thread.c': b'#include "winpthread_internal.h"\n',
    }

    with open(filename, 'rb') as file:
        content = file.read()

    has_crlf = b'\r\n' in content
    content_lf = content.replace(b'\r\n', b'\n')

    # If the patch is already applied, do not apply it again.
    if insert.strip() in content_lf:
        return False

    if dll_import in content_lf and vis_default not in content_lf:
        content_lf = content_lf.replace(dll_import, dll_import + b' ' + vis_default)

    insert_position = 0
    search = file_map.get(os.path.basename(filename))
    if search:
        index = content_lf.find(search)
        if index >= 0:
            insert_position = index + len(search)

    if insert_position > 0:
        print(f'Patching {filename}')
        patched_lf = (
            content_lf[:insert_position]
            + insert
            + content_lf[insert_position:]
            + append
        )
    else:
        # Fallback auto-detection if not specified in mapping or pattern not found
        lines = content_lf.split(b'\n')
        clean_content = _clean_c_code(content_lf)
        clean_lines = clean_content.split(b'\n')

        # Find limit line (first code block start: line start or end is '{')
        limit_line_idx = len(lines)
        for idx, line in enumerate(clean_lines):
            clean_line = line.strip()
            if clean_line.startswith(b'{') or clean_line.endswith(b'{'):
                limit_line_idx = idx
                break

        directive_pat = re.compile(rb'^\s*#\s*(if|ifdef|ifndef|elif|else|endif)\b')
        include_pat = re.compile(rb'^\s*#\s*include\s*[<"]')

        stack = []
        last_include_line_idx = -1
        stack_at_include = []

        # Only scan up to limit_line_idx for preprocessor blocks and last include
        for idx in range(min(limit_line_idx, len(lines))):
            line = clean_lines[idx]
            if include_pat.match(line):
                last_include_line_idx = idx
                stack_at_include = list(stack)

            m = directive_pat.match(line)
            if m:
                op = m.group(1)
                if op in (b'if', b'ifdef', b'ifndef'):
                    stack.append(idx)
                elif op == b'endif':
                    if stack:
                        stack.pop()

        push_lines = set()
        pop_lines = set()
        append_pop_to_end = False

        if last_include_line_idx >= 0:
            # Determine if we can exit the conditional blocks before code starts
            exited = False
            exit_line_idx = -1
            if stack_at_include:
                scan_stack = list(stack_at_include)
                target_block = stack_at_include[0]
                for idx in range(last_include_line_idx + 1, limit_line_idx):
                    line = clean_lines[idx]
                    m = directive_pat.match(line)
                    if m:
                        op = m.group(1)
                        if op in (b'if', b'ifdef', b'ifndef'):
                            scan_stack.append(idx)
                        elif op == b'endif':
                            if scan_stack:
                                popped = scan_stack.pop()
                                if popped == target_block:
                                    exit_line_idx = idx
                                    break
                if exit_line_idx >= 0:
                    exited = True

            if exited or not stack_at_include:
                push_lines.add(exit_line_idx if exited else last_include_line_idx)
                append_pop_to_end = True
            else:
                # We insert push inside the conditional block(s) and track sibling branches
                push_lines.add(last_include_line_idx)

                scan_stack = list(stack_at_include)
                target_block = stack_at_include[-1]
                sibling_lines = []
                pop_line_idx = -1

                for idx in range(last_include_line_idx + 1, len(lines)):
                    line = clean_lines[idx]
                    m = directive_pat.match(line)
                    if m:
                        op = m.group(1)
                        if op in (b'if', b'ifdef', b'ifndef'):
                            scan_stack.append(idx)
                        elif op == b'endif':
                            if scan_stack:
                                popped = scan_stack.pop()
                                if popped == target_block:
                                    pop_line_idx = idx
                                    break
                        elif op in (b'elif', b'else'):
                            if len(scan_stack) == len(stack_at_include):
                                sibling_lines.append(idx)

                for sib in sibling_lines:
                    pop_lines.add(sib)
                    push_lines.add(sib)
                if pop_line_idx >= 0:
                    pop_lines.add(pop_line_idx)

        if last_include_line_idx < 0:
            push_lines.add(-1)
            append_pop_to_end = True

        print(f'Patching {filename}')
        new_lines = []
        if -1 in push_lines:
            new_lines.extend([insert.strip(), b''])

        for idx, line in enumerate(lines):
            if idx in pop_lines:
                new_lines.extend([b'', append.strip(), b''])
            new_lines.append(line)
            if idx in push_lines:
                new_lines.extend([b'', insert.strip(), b''])

        if append_pop_to_end:
            new_lines.extend([b'', append.strip(), b''])

        patched_lf = b'\n'.join(new_lines)

    content_to_write = patched_lf.replace(b'\n', b'\r\n') if has_crlf else patched_lf
    with open(filename, 'wb') as file:
        file.write(content_to_write)
    return True


def patch_visibility_mingw_S(filename: str) -> bool:
    """Patch symbol visibility in assembly (.S) files for mingw."""
    pattern_mingw = re.compile(rb'\b__MINGW_USYMBOL\((\w+)\)')
    pattern_globl = re.compile(rb'\.(?:globl|global)\s+([a-zA-Z0-9_]+)')
    symbols: Set[bytes] = set()

    with open(filename, 'rb') as file:
        content = file.read()

    has_crlf = b'\r\n' in content
    content_lf = content.replace(b'\r\n', b'\n')

    for line in content_lf.splitlines():
        # Match MinGW symbol macro wrapper
        for match in pattern_mingw.findall(line):
            symbols.add(match.strip())
        # Match standard assembly global declarations
        for match in pattern_globl.findall(line):
            sym = match.strip()
            if not sym.startswith(b'__MINGW_USYMBOL'):
                symbols.add(sym)

    sorted_symbols = list(sorted(symbols)) + [b'_' + x for x in sorted(symbols)]
    if not sorted_symbols:
        return False

    code = b'\n/* XPATCH: do not export symbols. */\n.section .drectve,"yni"\n'
    code += b'\n'.join(
        f'.ascii " -exclude-symbols:{x.decode()} "'.encode() for x in sorted_symbols
    )
    code += b'\n'

    if content_lf.endswith(code):
        return False

    print(f'Patching {filename}')
    patched_lf = content_lf + code
    content_to_write = patched_lf.replace(b'\n', b'\r\n') if has_crlf else patched_lf
    with open(filename, 'wb') as file:
        file.write(content_to_write)
    return True


def zig_patch(zig_root: Optional[str] = None) -> None:
    """Patch Zig source libraries to hide internal exports (such as libunwind, mingw32)."""
    if not zig_root:
        zig_path = shutil.which(f'zig{EXE_EXT}')
        if not zig_path:
            return
        zig_root = os.path.realpath(os.path.dirname(zig_path))
    else:
        zig_root = os.path.realpath(zig_root)

    any_linux_any = os.path.join(zig_root, 'lib', 'libc', 'include', 'any-linux-any')
    lib_src_patched = False

    # 1. fix `lib/compiler_rt/stack_probe.zig` with Zig <= 0.13.
    if patch_file(
        os.path.join(zig_root, 'lib', 'compiler_rt', 'stack_probe.zig'),
        b'.linkage = strong_linkage',
        b'',
        replace=b'.linkage = linkage',
        count=sys.maxsize,
    ):
        lib_src_patched = True

    # 2. Set symbol visibility to `hidden` in `libunwind`.
    libunwind_src = os.path.join(zig_root, 'lib', 'libunwind', 'src')
    for file, tag in [
        ('assembly.h', 'UNWIND_ASSEMBLY_H'),
        ('config.h', 'LIBUNWIND_CONFIG_H'),
    ]:
        if patch_file(
            os.path.join(libunwind_src, file),
            b'#define ' + tag.encode(),
            b'\n\n/* XPATCH: do not export symbols. */\n#ifndef _LIBUNWIND_HIDE_SYMBOLS\n#define _LIBUNWIND_HIDE_SYMBOLS\n#endif\n',
        ):
            lib_src_patched = True
    for search, insert in [
        (
            b'#define _LIBUNWIND_HIDE_SYMBOLS\n#endif\n',
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
        if patch_file(os.path.join(libunwind_src, 'assembly.h'), search, insert):
            lib_src_patched = True

    # 3. Set symbol visibility to `hidden` in `mingw32`.
    for libc in ['mingw']:
        zig_libc = os.path.join(zig_root, 'lib', 'libc', libc)
        mingw_libsrc = '/mingw/libsrc/'
        for ext, patch_func in [
            ('c', patch_visibility),
            ('S', patch_visibility_mingw_S),
        ]:
            # Specify type for glob files to satisfy type checks
            glob_files: List[str] = glob.glob(f'{zig_libc}/**/*.{ext}', recursive=True)
            for file_path in glob_files:
                if mingw_libsrc not in file_path.replace('\\', '/'):
                    # Use a cast-like helper or exact annotation matching
                    func: Callable[[str], bool] = patch_func
                    if func(file_path):
                        lib_src_patched = True

    # 4. <sys/sysctl.h> is required by ffmpeg 6.0
    sys_ctl_h = os.path.join(any_linux_any, 'sys', 'sysctl.h')
    sys_ctl_h_src = os.path.join(any_linux_any, 'linux', 'sysctl.h')
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
        zig_clean_cache(zig_root)


def zig_dll2lib(
    dll_file: str, out_path: Optional[str] = None, force: bool = False
) -> int:
    """Generate a MSVC-compatible import library (.lib) from a DLL using pefile and zig dlltool."""
    try:
        import pefile  # pyright: ignore[reportMissingImports]
    except ImportError:
        print(
            '`pefile` is not installed. Try: pip install pefile',
            file=sys.stderr,
        )
        return EFAIL

    # Load the DLL file
    pe = pefile.PE(dll_file)

    # Mapping of PE machine types to `dlltool` machine types
    machine_types = {
        0x014C: 'i386',  # x86
        0x8664: 'i386:x86-64',  # x64 (AMD64)"
        0x01C4: 'arm',  # ARMv7
        0xAA64: 'arm64',  # ARM64
    }
    machine = machine_types.get(pe.FILE_HEADER.Machine, None)
    if machine is None:
        print(
            f'Unsupported machine type {pe.FILE_HEADER.Machine} in {dll_file}',
            file=sys.stderr,
        )
        return EFAIL

    # Check if the DLL has an export directory
    if not hasattr(pe, 'DIRECTORY_ENTRY_EXPORT'):
        print(
            f'No export symbols found in {dll_file}',
            file=sys.stderr,
        )
        return EFAIL

    dll_name = os.path.splitext(os.path.basename(dll_file))[0]
    out_dir = out_path or '.'
    out_file = dll_name + '.lib'
    if out_path:
        if out_path.endswith('.lib') or out_path.endswith('.a'):
            out_dir = os.path.dirname(out_path) or '.'
            out_file = os.path.basename(out_path)

    def_file = os.path.splitext(out_file)[0] + '.def'
    if os.path.exists(os.path.join(out_dir, out_file)) and not force:
        print(
            f'"{out_file}" already exists in "{out_dir}"',
            file=sys.stderr,
        )
        return EFAIL

    with open(os.path.join(out_dir, def_file), 'wb') as f:
        f.write(f'LIBRARY {dll_name}\r\n'.encode())
        f.write(b'EXPORTS\r\n')
        for symbol in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            name = symbol.name.decode() if symbol.name else None
            ordinal = symbol.ordinal if symbol.ordinal else None
            if name is not None:
                if ordinal is not None:
                    f.write(f'    {name} @{ordinal}\r\n'.encode())
                else:
                    f.write(f'    {name}\r\n'.encode())

    subprocess.run(
        [
            f'zig{EXE_EXT}',
            'dlltool',
            '-m',
            machine,
            '-D',
            dll_file,
            '-d',
            os.path.join(out_dir, def_file),
            '-l',
            os.path.join(out_dir, out_file),
        ],
        check=True,
    )
    return 0
