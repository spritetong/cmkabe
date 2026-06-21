# User Manual & Developer Guide: cmkabe

`cmkabe` is a modular, cross-platform build helper framework designed to simplify the orchestration of hybrid **Rust (Cargo) + C/C++ (CMake/Makefile)** projects. It ensures compatibility with external toolchains and legacy environments, offering simulated POSIX commands on Windows, WSL sync tools, and Zig-based cross-compilation support.

---

## Table of Contents

1. [Basic Usage](#basic-usage)
2. [cmkabe Design Philosophy & Architecture](#cmkabe-design-philosophy--architecture)
3. [Simulated Shell Commands (`shlutil.py`)](#simulated-shell-commands-shlutilpy)
4. [Rsync-Based Remote WSL2 Development Flow](#rsync-based-remote-wsl2-development-flow)
5. [Cross-Compilation & Toolchains (Zig & NDK)](#cross-compilation--toolchains-zig--ndk)
6. [CMake APIs Reference](#cmake-apis-reference)

---

## Basic Usage

Run the build helper via the root `Makefile`:

```bash
make <make_target> [BIN=<binary>] [DEBUG=<debug>] [TARGET=<target_triple>]
```

### Options & Variables

- **`BIN=<binary>`**: Specify the Cargo binary name to build or run (e.g., `make build BIN=app`).
- **`DEBUG=ON|OFF` or `1|0`**: Build in `Debug` mode if `ON` or `1`; build in `Release` mode if `OFF` or `0` (Default: `OFF`).
- **`TARGET=<target_triple>`**: Target triple for cross-compilation (e.g., `aarch64-unknown-linux-gnu`, `x86_64-pc-windows-msvc`, or `native` for host; default is `native`).

### Common Targets

- **`build`**: Build a Cargo binary. Requires `BIN=<binary>`.
- **`<binary>`**: Short-hand to build `BIN=<binary>` directly (e.g., `make app`).
- **`clean`**: Clean all cargo and CMake target artifacts.
- **`cmake` / `cmake-build`**: Configure and build all CMake sub-projects.
- **`cmake-clean`**: Clean CMake build directory for the current active configuration.
- **`cmake-distclean`**: Delete all caches and artifacts of the current configuration.
- **`cmake-rebuild`**: Shortcut for `cmake-clean` followed by `cmake-build`.
- **`lib` / `cargo-lib`**: Compile Rust cargo library crates.
- **`run`**: Run a Cargo binary. Requires `BIN=<binary>`.

---

## cmkabe Design Philosophy & Architecture

Hybrid projects often face friction when linking Rust static/dynamic libraries into C/C++ targets, or vice versa. `cmkabe` addresses this through a declarative, file-based synchronization workflow.

```text
┌─────────────────────┐
│  Host Env Detection │
└────────┬────────────┘
         ▼
┌─────────────────────────────────┐
│     TargetParser (Python)       │ ◄── Reads Target / OS / Env configs
└────────┬────────┬────────┬──────┘
         │        │        │
         ▼        ▼        ▼
┌──────────────┐┌─────────────────┐┌───────────────────────┐
│ .settings.mk ││ .settings.cmake ││ .toolchain.cmake      │
│ .environ.mk  ││ .environ.cmake  ││ (Zig CC/CXX wrappers) │
└──────────────┘└─────────────────┘└───────────────────────┘
         │        │        │
         ▼        ▼        ▼
┌──────────────────┐┌──────────────────┐
│     Makefile     ││      CMake       │ ◄── Source files, libraries
└──────────────────┘└──────────────────┘
```

### 1. Unified Target Parsing (`target.py`)

`cmkabe` automatically inspects target triples, parses them into components (`arch`, `vendor`, `os`, `env`), and exports the discovered environment parameters to clean build configuration files:

- **`make` environment files**: `.settings.mk`, `.environ.mk`
- **`cmake` environment files**: `.settings.cmake`, `.environ.cmake`, `.toolchain.cmake`

These generated files bridge the variable-passing gap between GNU Make and CMake, ensuring compiler paths, flags (`CFLAGS`, `CXXFLAGS`, `LDFLAGS`), and architecture options match exactly.

### 2. Triple mapping & Host Discovery

When `TARGET=native` is specified, `cmkabe` queries registry values (on Windows), probes environment variables (such as Android NDK path, Zig location), and maps host system properties:

- **Windows MSVC/GNU detection**
- **WSL mount points discovery**
- **Unix OS tags mapping**

---

## Simulated Shell Commands (`shlutil.py`)

To ensure that Unix-centric `Makefiles` can run seamlessly on native Windows host shells (without requiring MSYS2/Cygwin), `cmkabe` provides a portable shell utility simulator (`shlutil.py`).

### Supported Simulated Commands

| Command | Options | Description |
|:---|:---|:---|
| `rm` | `-f`, `-r` | Recursively removes files/folders, resolving Windows read-only locks natively. |
| `mkdir` | `-p`, `-f` | Creates paths, with safety retries in case of concurrent directory creation. |
| `rmdir` | `-e` | Removes empty subdirectories and automatically prunes empty parent folders. |
| `mv` | `-f` | Moves/renames files/directories across different volumes. |
| `cp` | `-r`, `-P`, `-f` | Copies files/directories. `-P` respects/creates symbolic links correctly. |
| `mklink` | `-D`, `-f` | Creates directory or file symbolic links on Windows and POSIX. |
| `fix-symlink` | — | Fixes broken Windows directory junctions and WSL absolute symlinks. |
| `cwd` / `mydir` | — | Prints the current workspace path or `cmk` directory formatted in standard Unix slash format. |
| `relpath` | — | Prints the relative path from a start directory to a target. |
| `win2wsl-path` | — | Converts a Windows absolute path (e.g., `C:\foo`) to a WSL path (`/mnt/c/foo`). |
| `wsl2win-path` | — | Converts a WSL path back to a Windows drive path. |
| `is-wsl-win-path`| — | Checks whether a path points to a WSL Windows mount `/mnt/[a-z]/`. |
| `touch` | `-f` | Updates file timestamps or creates empty files. |
| `timestamp` | — | Prints the current epoch timestamp. |
| `cmpver` | `-f` | Compares version strings. Outputs `+` if v1 > v2, `0` if equal, `-` if v1 < v2. |
| `winreg` | — | Queries Windows registry values (reads `HKLM`, `HKCU`, etc.). |
| `ndk-root` | — | Discovers the root directory of the Android NDK. |
| `cargo-exec` | — | Sets up Cargo environment variables and executes subcommands. |
| `upload` | — | Uploads files to remote servers via SFTP or FTP dynamically. |
| `zig-patch` | — | Discovers Zig installation and injects dynamic patches for clean linking. |

---

## Rsync-Based Remote WSL2 Development Flow

If you are developing inside Windows but want the build to execute at Linux speed on a WSL2 distro, `cmkabe` supports the Rsync syncing helper (`rmake.py`).

### How it works

1. **Source Syncing**: It calls `rsync` over SSH/WSL execution to sync workspace changes incrementally to a `.rmake` shadow folder in your WSL Linux distro.
2. **Build Delegation**: It invokes the build command on the Linux side.
3. **Artifact Back-Syncing**: It syncs output libraries (`.so`, `.a`) back to Windows to keep IDE autocompletions and debuggers updated.

### Setting up Rsync build

Configure your target settings to use `rmake` in your local environment, or use `python cmk/rmake.py` to trigger remote compilation.

---

## Cross-Compilation & Toolchains (Zig & NDK)

Cross-compiling C/C++ alongside Rust cargo libraries is typically error-prone. `cmkabe` automates this using **Zig as a cross-compiler wrapper** and **Android NDK auto-detection**.

### 1. Zig CC/CXX Wrapper (`zig-wrapper.zig`)

`cmkabe` packages a custom wrapper binary that allows the Zig compiler to be used as a drop-in replacement for traditional compilers like `gcc`, `clang`, `ar`, and `ld.lld`.

- **Modularization**: The wrapper implementation is separated into modular parts (`zig-wrapper/`):
  - `allocator.zig`: High-safety buffered memory allocator.
  - `parser.zig`: Parameter option scanner.
  - `command.zig`: Compiler mode mapper (translates wrappers for `ar`, `cc`, `c++`, `ld`, etc.).
  - `logger.zig`: File logging tool for tracing parameters (`ZIG_WRAPPER_LOG`).
  - `filter.zig`: Flag rewriting rules (translates system include flags, filters unsupported options, maps `-fopenmp` to `-lomp`).
  - `main.zig`: Child process spawner with Windows shell boundary protection (checks command length and falls back to safe `@flags` files).
- **Compilation**: The compiler wrapper is automatically recompiled from `cmk/zig-wrapper.zig` using `zig build-exe` whenever changes are detected.

### 2. Android NDK Toolchain Discovery

When target OS is mapped to `android`, `TargetParser` automatically searches:

1. Environment variables (`ANDROID_NDK_ROOT`, `ANDROID_NDK_HOME`, `NDK_ROOT`).
2. Standard local paths (e.g., `%LocalAppData%/Android/Sdk/ndk/*` or `~/Android/Sdk/ndk/*`).
It then extracts compiler executable paths and includes for the specified target ABI automatically.

---

## CMake APIs Reference

`cmkabe` provides helper functions inside `cmk/cmake/env.cmake` (and standard `cmk/rules.cmake` legacy stub) to facilitate compilation in CMake.

### `cmkabe_target_link_rust_dlls`

Links target binaries against Rust dynamic library DLLs and automatically handles MSVC `.lib` wrapper file generation on Windows.

```cmake
cmkabe_target_link_rust_dlls(
    <target>
    [DLLS <dll_name1> <dll_name2> ...]
)
```

- **`<target>`**: The CMake target to apply links to.
- **`DLLS`**: List of dynamic library names compiled from Rust (without extension).

### `cmkabe_install_rust_dlls`

Configures installation tasks for compiled Rust dynamic libraries, placing them in target executable directories.

```cmake
cmkabe_install_rust_dlls(
    <target>
    [DLLS <dll_name1> <dll_name2> ...]
    [DESTINATION <install_path>]
)
```

- **`DESTINATION`**: Target directory where the binaries should be installed alongside executable files.

### `cmkabe_add_make_target`

Creates a CMake target that delegates execution to Makefile targets, allowing hybrid project setups.

```cmake
cmkabe_add_make_target(
    <target_name>
    [MAKE_TARGET <makefile_target>]
    [WORKING_DIRECTORY <dir>]
)
```
