# User Manual

<https://github.com/spritetong/cmkabe>

## Usage

`make <make_target> [BIN=<binary>] [DEBUG=<debug>] [TARGET=<target_triple>]`

### *make_target*

- ***build***

   Build a cargo binary. The option BIN=*binary* is required.

   e.g. `make build BIN=app`

- ***binary*** in ${CARGO_EXECUTABLES}

    Build the cargo binary named *binary*.

    It's equivalent to `make build BIN=<binary>`.

    e.g. `make app`

- ***clean***
    Clean all targets, including cargo and CMake.

    e.g. `make clean`

- ***clean-cmake*** | ***cmake-clean-root***

    Delete the CMake build directory, including all caches and artifacts.

    e.g. `make clean-make` (The directory `target/.cmake/` has been erased)

- ***cmake*** | ***cmake-build***

    Build all CMake projects.

    e.g. `make cmake`

- ***cmake-clean***

    Run CMake clean.

    e.g. `make cmake-clean` (The directory `target/.cmake/<TARGET_TRIPLE>/<Configuration>/` is existent)

- ***cmake-distclean***

    Run CMake clean and delete caches and artifacts of the current configuration.

    e.g. `make cmake-distclean` (The directory `target/.cmake/<TARGET_TRIPLE>/<Configuration>/` has been erased)

- ***cmake-rebuild***

    Rebuild all CMake projects, is equivalent to *cmake-clean* + *cmake-build*.

    e.g. `make cmake-build`

- ***cmake-init***

    Re-generate CMake build files in the directory `target/.cmake/<TARGET_TRIPLE>/<Configuration>/`.

    e.g. `make cmake-init`

- ***lib*** | ***cargo-lib***

    Build cargo libraries.

    e.g. `make lib`

- ***run***

    Run a cargo binary. The option BIN=*binary* is required.

    e.g. `make run BIN=app`

- **run**-***binary*** in ${CARGO_EXECUTABLES}

    Run the cargo binary named *binary*. It's equivalent to `make run BIN=<binary>`.

    e.g. `make run-app`

- ***upgrade*** | ***cargo-upgrade***

    Upgrade cargo dependency crates.

    e.g. `make cargo-upgrade`

## *binary*

Specify the cargo binary name to be built or run.

e.g. `make build BIN=app`

`make run BIN=app`

## *debug*

`ON|OFF` or `1|0`

Build for debug configuration if ON, and for release configuration if OFF.

Default is OFF.

e.g. `make build BIN=app DEBUG=0` (Build the cargo crate "app" for release)

## *target_triple*

This option is used for cross compilation.

Specify a full Clang triple like  
`x86_64-pc-windows-msvc`, `aarch64-unknown-linux-gnu`...,  
or `native` for the host OS triple,  
or other simple vendor/architecture string(s) defined by the project's Makefile.

Default is `native`.

e.g.
`make build BIN=app TARGET=native`  
`make build BIN=app TARGET=aarch64-rockchip-linux-gnu`
