# CMKABE Todo List

This file tracks outstanding tasks, cleanup items, and future optimization ideas for the `cmk` library.

## High Priority / Short Term

- [ ] **Modernize Root Python Scripts**:
  - Convert remaining `.format()` calls to f-strings in:
    - [shlutil.py](file:///d:/githome/sound-ocean/sound-ocean-se/cmk/shlutil.py#L27)
    - [rmake.py](file:///d:/githome/sound-ocean/sound-ocean-se/cmk/rmake.py#L27) (root script wrapper)

## Low Priority / Maintainability

- [ ] **ShellCmd Robustness**:
  - Review security and parameter escaping patterns in `ShellCmd` (defined in `cmk/pylib/commands.py`) to prevent command injection risks in parameter handling.
- [ ] **CI/CD Unit Tests**:
  - Add automated test cases for checking version comparisons under `env.mk` directly in a Makefile testing pipeline to prevent regressions.
- [ ] **WSL Path Translation**:
  - Further verify `win2wsl_path` and `wsl2win_path` functions in mixed environments (e.g. Docker, virtual drives).

## Future Goals / Feature Enhancements

- [ ] **Cross-compilation parity with `cargo-zigbuild` / `cross`**:
  - [ ] **Apple SDK Integration**: Auto-detect or retrieve minimalist Apple SDKs to support macOS/iOS cross-compilation on Linux/Windows hosts out-of-the-box.
  - [ ] **vcpkg Integration**: Integrate `vcpkg` for auto-retrieval and linking of target-architecture C/C++ library dependencies.
  - [ ] **Unified Cargo Command**: Provide a custom Cargo subcommand (e.g., `cargo-cmk` or `cargo cmk`) to compile, test, or run packages automatically in the generated target toolchain context.
