# Zig ArgFilter Configuration Guide

This document explains the dynamic argument filtering feature powered by the `ZIG_WRAPPER_FILTERS` environment variable. It describes the rule syntax, available matchers, replacers, and maps the wrapper's built-in static filters to their equivalent dynamic environment variable DSL forms.

---

## 1. Environment Variable Filter DSL Syntax

The `ZIG_WRAPPER_FILTERS` variable contains one or more rules separated by semicolons (`;`).

Each rule is defined as:

```ini
<option_key> [matchers...] -> [replacers...]
```

> [!NOTE]
> If a rule is matched, the matched option is replaced by the list of `[replacers...]`.
> If `[replacers...]` is empty, the option is **discarded** (ignored).

### Matchers Reference

Matchers restrict when a rule will match. Multiple matchers are applied sequentially (AND logic).

| Matcher | Description | Example |
| :--- | :--- | :--- |
| `partial` | Allows matching partial/combined options (e.g. `-I/usr/include` instead of just `-I`). | `partial` |
| `command:<list>` | Matches if the command is in the comma-separated list of tool enums. | `command:cc,cxx` |
| `linker:<bool>` | Matches if the wrapper is running in linker mode (`true` or `false`). | `linker:true` |
| `target:<pattern>`| Matches the target triple against a wildcard pattern. | `target:x86_64*` |
| `match:<pattern>` | Matches the value of the argument against a wildcard pattern. | `match:/usr/*` |
| `next` | Consumes and inspects the next argument in the argv stream. | `next` |

### Replacers Reference

Replacers specify what to emit in place of the matched option.

| Replacer | Description | Example |
| :--- | :--- | :--- |
| `opt_val` | Emits the value of the option (useful with `partial`). | `opt_val` |
| `replace_arg:<idx>` | Emits the argument at `<idx>` relative to the option. | `replace_arg:0` |
| `replace_sub:<idx>:<needle>:<replacement>` | Replaces `<needle>` with `<replacement>` in the argument at `<idx>`. | `replace_sub:0:++:` |
| `[literal]` | Any other token emits that literal string directly. | `-Wl,--strip-all` |

---

## 2. Built-in Filters & DSL Equivalents

The following sections document the built-in static filters coded in `filter.zig` and provide their exact dynamic equivalents for `ZIG_WRAPPER_FILTERS`.

### 2.1 Include Directory Adjustments

Redirects standard include folders to `-idirafter` to prevent pollution of system includes under Zig.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-I").allowPartialOpt()
      .match("/usr/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().eof()
      .match("/usr/local/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().done();
  ```

- **DSL Equivalent**:

  ```ini
  -I partial match:/usr/include -> -idirafter opt_val;
  -I partial match:/usr/local/include -> -idirafter opt_val
  ```

### 2.2 MSVC Linker Flags Discarding

Hides MSVC-style linker flags when building to prevent Clang errors.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-Xlinker")
      .match("/MANIFEST:EMBED").eof()
      .match("/version:0.0").eof()
      .next().match("--dependency-file=*").done();
  ```

- **DSL Equivalent**:

  ```ini
  -Xlinker match:/MANIFEST:EMBED ->;
  -Xlinker match:/version:0.0 ->;
  -Xlinker next match:--dependency-file=* ->
  ```

### 2.3 Dialect Suffix Patching for C Compiler

Rewrites C++ style `-std=c++XX` options to standard `-std=cXX` when invoked through the C compiler.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-std").command(&.{.cc}).replaceWithSubString(0, "++", "").done();
  ```

- **DSL Equivalent**:

  ```ini
  -std command:cc -> replace_sub:0:++:
  ```

### 2.4 `-Werror` and Diagnostics Handling

Appends `-Wno-error=date-time` when `-Werror` is specified to ensure Zig compiles code containing time macros.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-Werror").replaceWithArg(0).replaceWith(&.{"-Wno-error=date-time"}).done();
  ```

- **DSL Equivalent**:

  ```ini
  -Werror -> replace_arg:0 -Wno-error=date-time
  ```

### 2.5 Unsupported Platform Options

Ignores unsupported compiler target flags or verbose settings.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-m").match("*").done();
  map.initFilter("-verbose").replaceWith(&.{"-v"}).done();
  map.initFilter("-v").linker(true).done();
  ```

- **DSL Equivalent**:

  ```ini
  -m match:* ->;
  -verbose -> -v;
  -v linker:true ->
  ```

### 2.6 OpenMP Fallback

Translates compiler-specific OpenMP options to standard linker library references.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-fopenmp=libomp").linker(true).replaceWithArg(0).replaceWith(&.{"-lomp"}).done();
  ```

- **DSL Equivalent**:

  ```ini
  -fopenmp=libomp linker:true -> replace_arg:0 -lomp
  ```

### 2.7 CPU Architecture Tuning Matches

Prevents passing invalid or unsupported 32-bit x86 architecture targets when building on x86_64 host.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-march")
      .target("x86_64*").match("i386").eof()
      .target("x86_64*").match("i586").eof()
      .target("x86_64*").match("i686").done();
  ```

- **DSL Equivalent**:

  ```ini
  -march target:x86_64* match:i386 ->;
  -march target:x86_64* match:i586 ->;
  -march target:x86_64* match:i686 ->
  ```

### 2.8 Windows GNU Toolkit Fixes

Rewrites standard libraries and flags for Windows GCC/MinGW compilers when target is not MSVC.

- **Code (filter.zig)**:

  ```zig
  map.initFilter("-l").allowPartialOpt()
      .match("mingw32").eof()
      .match("stdc++").replaceWith(&.{ "-lc++", "-lc++abi" }).done();
  ```

- **DSL Equivalent**:

  ```ini
  -l partial match:mingw32 ->;
  -l partial match:stdc++ -> -lc++ -lc++abi
  ```

---

## 3. Supported Tool List (for `command:`)

Here are the canonical tool names supported in the `command:<list>` matcher, corresponding to the `ZigCommand` enum:

- **Compilers**: `cc` (also matches alias `gcc`, `clang`), `c++` (also matches alias `g++`, `cxx`, `clang++`)
- **Linkers**: `ld`, `link`
- **Utilities**: `ar`, `ranlib`, `strip`, `objcopy`, `lib`, `dlltool`, `rc`, `windres`
