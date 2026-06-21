# CMKABE Todo List

This file tracks outstanding tasks, cleanup items, and future optimization ideas for the `cmk` library.

## High Priority / Short Term

- [ ] **Fix Typo Variable**: `CMKABE_COMPLETED_PORJECTS` -> `CMKABE_COMPLETED_PROJECTS`
  - Need to update:
    - [env.mk](file:///d:/githome/sound-ocean/sound-ocean-se/cmk/env.mk#L205-L210)
    - [cmake/env.cmake](file:///d:/githome/sound-ocean/sound-ocean-se/cmk/cmake/env.cmake#L375)
- [ ] **Modernize Root Python Scripts**:
  - Convert remaining `.format()` calls to f-strings in:
    - [shlutil.py](file:///d:/githome/sound-ocean/sound-ocean-se/cmk/shlutil.py#L27)
    - [rmake.py](file:///d:/githome/sound-ocean/sound-ocean-se/cmk/rmake.py#L27) (root script wrapper)
    - [elf_path_fixer.py](file:///d:/githome/sound-ocean/sound-ocean-se/cmk/elf_path_fixer.py#L408)

## Low Priority / Maintainability

- [ ] **ShellCmd Robustness**:
  - Review security and parameter escaping patterns in `ShellCmd` (defined in `cmk/pylib/commands.py`) to prevent command injection risks in parameter handling.
- [ ] **CI/CD Unit Tests**:
  - Add automated test cases for checking version comparisons under `env.mk` directly in a Makefile testing pipeline to prevent regressions.
- [ ] **WSL Path Translation**:
  - Further verify `win2wsl_path` and `wsl2win_path` functions in mixed environments (e.g. Docker, virtual drives).
