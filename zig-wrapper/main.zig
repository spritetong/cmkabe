const std = @import("std");
const builtin = @import("builtin");
const utils = @import("utils.zig");
const parser_mod = @import("parser.zig");
const SimpleOptionParser = parser_mod.SimpleOptionParser;
const command_mod = @import("command.zig");
const ZigCommand = command_mod.ZigCommand;
const log_mod = @import("logger.zig");
const ZigLog = log_mod.ZigLog;
const TempFile = log_mod.TempFile;
const filter_mod = @import("filter.zig");
const ZigArgFilter = filter_mod.ZigArgFilter;
const ZigArgFilterMap = filter_mod.ZigArgFilterMap;

const StringArray = std.ArrayList([]const u8);
const StringSet = std.StringArrayHashMap(void);
const ArgIteratorGeneral = std.process.ArgIteratorGeneral(.{});

pub const ZigWrapper = struct {
    const Self = @This();
    allocator: std.mem.Allocator,
    log: ZigLog,
    sys_argv0: []const u8 = "",
    sys_argv: StringArray,
    zig_exe: []const u8 = "",

    /// The current Zig command.
    command: ZigCommand = ZigCommand.cc,

    is_quering_version: bool = false,
    /// If the Zig command is running as a linker.
    is_linker: bool = false,
    /// If the Zig compiler is running as a preprocessor.
    is_preprocessor: bool = false,
    /// If the output file is a shared library.
    is_shared_lib: bool = false,
    /// If the input file is a C source file.
    input_is_c_file: bool = false,
    /// Allow to parse the compiler flags from `<LANG>FLAGS_<TARGET>` environment variables.
    allow_target_env_flags: bool = false,
    /// Disable `__declspec(dllexport)` for Windows targets.
    disable_dllexport: bool = false,
    /// <arch>-<os>-<abi>
    zig_target: []const u8 = "",
    /// <arch>-<vendor>-<os>-<abi>
    clang_target: []const u8 = "",
    /// -march=<cpu> or -mcpu=<cpu>
    zig_cpu_opts: StringArray,
    /// -mtune=<tune>
    zig_cpu_tune_opts: StringArray,
    /// -l<lib> options not to be passed to the linker.
    skipped_libs: StringSet,
    skipped_lib_patterns: StringArray,
    /// -L<lib path> options not to be passed to the linker.
    skipped_lib_paths: StringSet,

    target_is_windows: bool = false,
    target_is_android: bool = false,
    target_is_linux: bool = false,
    target_is_apple: bool = false,
    target_is_wasm: bool = false,
    target_is_msvc: bool = false,
    target_is_musl: bool = false,
    at_file_opt: ?[]const u8 = null,

    arg_filter: ZigArgFilterMap,
    /// The arguments to run the Zig command, include the Zig executable and its arguments.
    args: StringArray,
    flags_file: ?TempFile = null,

    // windres
    windres_input: ?[]const u8 = null,
    windres_output: ?[]const u8 = null,
    windres_preprocessor_arg: ?[]const u8 = null,
    windres_depfile: ?[]const u8 = null,
    // CC linker
    cc_dll_lib: ?[]const u8 = null,
    cc_dll_a: ?[]const u8 = null,
    cc_output: ?[]const u8 = null,

    pub fn init(allocator_: std.mem.Allocator) !Self {
        var self = outer: {
            // logger
            const log = blk: {
                const log_path = utils.getEnvVar(allocator_, "ZIG_WRAPPER_LOG") catch null;
                errdefer if (log_path) |v| {
                    allocator_.free(v);
                };
                const v = try ZigLog.init(log_path);
                break :blk v;
            };

            break :outer Self{
                .allocator = allocator_,
                .log = log,
                .sys_argv = StringArray.init(allocator_),
                .zig_cpu_opts = StringArray.init(allocator_),
                .zig_cpu_tune_opts = StringArray.init(allocator_),
                .skipped_libs = StringSet.init(allocator_),
                .skipped_lib_patterns = StringArray.init(allocator_),
                .skipped_lib_paths = StringSet.init(allocator_),
                .arg_filter = ZigArgFilterMap.init(allocator_),
                .args = StringArray.init(allocator_),
            };
        };
        errdefer self.deinit();

        // Collect `argv[0..]`...
        var argv = StringArray.init(self.allocator);
        defer utils.freeStringArray(self.allocator, &argv);

        var arg_iter = try std.process.argsWithAllocator(self.allocator);
        defer arg_iter.deinit();
        if (arg_iter.next()) |argv0| {
            self.sys_argv0 = try self.allocator.dupe(u8, argv0);
        }
        while (arg_iter.next()) |arg| {
            if (utils.strStartsWith(arg, "@")) {
                // Parse the flags file.
                try self.parseFileFlags(arg[1..], &argv);
                self.at_file_opt = try self.allocator.dupe(u8, arg);
                continue;
            }

            // If the flags file is not the last argument, ignore it.
            if (self.at_file_opt) |v| {
                self.allocator.free(v);
                self.at_file_opt = null;
            }
            try argv.append(try self.allocator.dupe(u8, arg));
        }

        // Write the input command line to log.
        if (self.log.enabled()) {
            self.log.print("{s}", .{self.sys_argv0});
            for (argv.items) |arg| {
                self.log.print(" {s}", .{arg});
            }
            self.log.write("\n");
        }

        // Parse the command type from `argv[0]`.
        const stem = std.fs.path.stem(self.sys_argv0);
        self.command = ZigCommand.fromStr(
            stem[if (std.mem.lastIndexOfScalar(u8, stem, '-')) |s| s + 1 else 0..],
        ) orelse return error.InvalidZigCommand;
        if (self.command.isCompiler() or self.command == .ld) {
            self.is_linker = true;
        }

        // Parse environment variables.
        self.zig_exe = utils.getEnvVar(self.allocator, "ZIG_EXECUTABLE") catch "";
        self.zig_target = utils.getEnvVar(self.allocator, "ZIG_WRAPPER_TARGET") catch "";
        self.clang_target = utils.getEnvVar(self.allocator, "ZIG_WRAPPER_CLANG_TARGET") catch "";

        // Parse Zig flags in `argv[1..]`.
        try self.sys_argv.ensureUnusedCapacity(argv.items.len);
        try self.parseCustomArgs(argv.items, &self.sys_argv);
        utils.freeStringArray(self.allocator, &argv);
        argv = StringArray.init(self.allocator);

        // Correct `c++` to `cc`.
        if (self.input_is_c_file) {
            if (self.is_linker) {
                self.input_is_c_file = false;
            } else if (self.command == .cxx) {
                self.command = .cc;
            }
        }

        // Parse Zig flags in the environment variables.
        try self.parseEnvFlags(&argv);
        if (!utils.stringsContains(self.sys_argv.items, argv.items)) {
            for (argv.items) |arg| {
                try self.sys_argv.append(try self.allocator.dupe(u8, arg));
            }
        }
        utils.freeStringArray(self.allocator, &argv);
        argv = StringArray.init(self.allocator);

        // Set default values.
        if (self.zig_exe.len == 0) {
            self.zig_exe = try std.fmt.allocPrint(
                self.allocator,
                "zig{s}",
                .{builtin.os.tag.exeFileExt(builtin.cpu.arch)},
            );
        }
        if (self.zig_target.len == 0) {
            self.zig_target = try std.fmt.allocPrint(
                self.allocator,
                "{s}-{s}-{s}",
                .{
                    @tagName(builtin.target.cpu.arch),
                    @tagName(builtin.target.os.tag),
                    @tagName(builtin.target.abi),
                },
            );
        }
        if (self.clang_target.len == 0) {
            self.clang_target = try self.allocator.dupe(u8, self.zig_target);
        }

        self.target_is_windows = std.mem.indexOf(u8, self.clang_target, "-windows") != null;
        self.target_is_android = std.mem.indexOf(u8, self.clang_target, "-android") != null;
        self.target_is_linux = std.mem.indexOf(u8, self.clang_target, "-linux") != null;
        self.target_is_apple = std.mem.indexOf(u8, self.clang_target, "-apple") != null or
            std.mem.indexOf(u8, self.clang_target, "-macos") != null or
            std.mem.indexOf(u8, self.clang_target, "-darwin") != null;
        self.target_is_wasm = utils.strStartsWith(self.clang_target, "wasm") or
            utils.strEndsWith(self.clang_target, "-emscripten");
        self.target_is_msvc = utils.strEndsWith(self.clang_target, "-msvc");
        self.target_is_musl = utils.strEndsWith(self.clang_target, "-musl");

        ZigArgFilter.initFilterMap(&self, &self.arg_filter);
        return self;
    }

    pub fn deinit(self: *Self) void {
        if (self.flags_file) |*flags_file| {
            flags_file.deinit();
            self.flags_file = null;
        }
        if (self.sys_argv0.len > 0) self.allocator.free(self.sys_argv0);
        if (self.zig_exe.len > 0) self.allocator.free(self.zig_exe);
        if (self.zig_target.len > 0) self.allocator.free(self.zig_target);
        if (self.clang_target.len > 0) self.allocator.free(self.clang_target);
        if (self.at_file_opt) |v| self.allocator.free(v);
        if (self.windres_input) |v| self.allocator.free(v);
        if (self.windres_output) |v| self.allocator.free(v);
        if (self.windres_preprocessor_arg) |v| self.allocator.free(v);
        if (self.windres_depfile) |v| self.allocator.free(v);
        if (self.cc_dll_lib) |v| self.allocator.free(v);
        if (self.cc_dll_a) |v| self.allocator.free(v);
        if (self.cc_output) |v| self.allocator.free(v);

        utils.freeStringArray(self.allocator, &self.args);
        utils.freeStringArray(self.allocator, &self.sys_argv);
        utils.freeStringArray(self.allocator, &self.zig_cpu_opts);
        utils.freeStringArray(self.allocator, &self.zig_cpu_tune_opts);
        utils.freeStringSet(self.allocator, &self.skipped_libs);
        utils.freeStringArray(self.allocator, &self.skipped_lib_patterns);
        utils.freeStringSet(self.allocator, &self.skipped_lib_paths);

        self.arg_filter.deinit();
        self.log.deinit();
    }

    pub fn run(self: *Self) !u8 {
        // Zig executable
        try self.args.append(try self.allocator.dupe(u8, self.zig_exe));
        // Zig command
        try self.args.append(try self.allocator.dupe(u8, self.command.toName()));
        // `cc`, `c++`: -target <target> [-march=<cpu>] [-mtune=<cpu>]
        if (self.command.isCompiler()) {
            try self.args.append(try self.allocator.dupe(u8, "-target"));
            try self.args.append(try self.allocator.dupe(u8, self.zig_target));

            // Disable 'date-time' error by default.
            try self.args.append(try self.allocator.dupe(u8, "-Wno-error=date-time"));

            if (!self.is_preprocessor) {
                for (&[_]*StringArray{ &self.zig_cpu_opts, &self.zig_cpu_tune_opts }) |options| {
                    for (options.items) |opt| {
                        // Fix the Zig CC bug about CPU architecture:
                        //    '-' -> '_' for compiler;
                        //    '_' -> '-' for preprocessor.
                        const s = @constCast(opt[1..]);
                        _ = std.mem.replace(u8, s, "-", "_", s);

                        _ = try self.arg_filter.next(
                            self,
                            @constCast(&SimpleOptionParser{ .args = &.{opt} }),
                            &self.args,
                        );
                    }
                }

                // https://github.com/ziglang/zig/wiki/FAQ#why-do-i-get-illegal-instruction-when-using-with-zig-cc-to-build-c-code
                try self.args.append(try self.allocator.dupe(u8, "-fno-sanitize=undefined"));

                // Fix compilation issues of Rust native crates.
                if (self.disable_dllexport) {
                    try self.args.append(try self.allocator.dupe(u8, "-fvisibility-ms-compat"));
                    try self.args.append(try self.allocator.dupe(u8, "-Ddllexport=nodebug"));
                }
            }
            if (self.target_is_windows) {
                // Undefine `_WIN32_WINNT` for Windows targets.
                try self.args.append(try self.allocator.dupe(u8, "-U_WIN32_WINNT"));
            }
            if (self.is_linker) {
                try self.args.append(try self.allocator.dupe(u8, "-lc++"));
                try self.args.append(try self.allocator.dupe(u8, "-lc++abi"));
                try self.args.append(try self.allocator.dupe(u8, "-lomp"));
            }
        }

        var argv = try StringArray.initCapacity(self.allocator, self.sys_argv.items.len);
        defer argv.deinit();
        std.mem.swap(StringArray, &self.sys_argv, &argv);
        for (argv.items) |arg| {
            try self.fixCommandFlag(@constCast(arg), &self.sys_argv);
            self.allocator.free(arg);
        }
        argv.clearRetainingCapacity();

        // Parse arguments in `argv[1..]`.
        var argv_parer = SimpleOptionParser{ .args = self.sys_argv.items };
        while (argv_parer.hasArgument()) {
            try self.parseArgument(&argv_parer);
        }

        // Fix link libraries.
        if (self.is_linker) {
            try self.fixLinkLibs();
        }

        // Write the actual `zig` command line to log.
        if (self.log.enabled()) {
            self.log.write("    -->");
            for (self.args.items) |arg| {
                self.log.write(" ");
                self.log.write(arg);
            }
            self.log.write("\n");
        }

        // Write to `@<flags file>` if present.
        try self.writeFlagsFile();

        // Execute the command.
        var child = std.process.Child.init(self.args.items, self.allocator);
        var exit_code: u8 = 0;
        if (self.log.enabled()) {
            child.stderr_behavior = .Pipe;
            child.stdout_behavior = .Pipe;
            var stdout: std.ArrayListUnmanaged(u8) = .empty;
            defer stdout.deinit(self.allocator);
            var stderr: std.ArrayListUnmanaged(u8) = .empty;
            defer stderr.deinit(self.allocator);
            try child.spawn();
            try child.collectOutput(self.allocator, &stdout, &stderr, 10 * 1024 * 1024);
            exit_code = (try child.wait()).Exited;
            try std.io.getStdErr().writeAll(stderr.items);
            try std.io.getStdOut().writeAll(stdout.items);
            self.log.print("    --> exit code: {d}\n", .{exit_code});
            self.log.write("    --> stdout: ");
            self.log.write(stdout.items);
            self.log.write("\n");
            self.log.write("    --> stderr: ");
            self.log.write(stderr.items);
            self.log.write("\n");
        } else {
            exit_code = (try child.spawnAndWait()).Exited;
        }
        try self.postProcess(exit_code == 0);
        if (exit_code != 0) {
            self.log.print("***** error code: {d}\n", .{exit_code});
        }
        return exit_code;
    }

    pub fn parseFileFlags(self: *Self, path: []const u8, dest: *StringArray) !void {
        // Open the file for reading
        var file = try std.fs.cwd().openFile(path, .{});
        defer file.close();

        // Get the file size
        const file_size = try file.getEndPos();

        // Allocate a buffer to hold the file content
        const flags_str = try self.allocator.alloc(u8, file_size);
        defer self.allocator.free(flags_str);

        // Read the file content into the buffer
        _ = try file.readAll(flags_str);

        // Parse the flags
        var arg_iter = try ArgIteratorGeneral.initTakeOwnership(
            self.allocator,
            flags_str,
        );
        defer arg_iter.deinit();
        while (arg_iter.next()) |arg| {
            try dest.append(try self.allocator.dupe(u8, arg));
        }
    }

    fn parseEnvFlags(self: *Self, dest: *StringArray) !void {
        // Do not use environment variables if we are querying the compiler version.
        if (self.is_quering_version) {
            return;
        }

        const buf = try self.allocator.alloc(u8, 32 +
            @max(self.zig_target.len, self.clang_target.len));
        defer self.allocator.free(buf);

        var args = StringArray.init(self.allocator);
        defer utils.freeStringArray(self.allocator, &args);
        var tmp = StringArray.init(self.allocator);
        defer utils.freeStringArray(self.allocator, &tmp);

        for (0..3) |target_idx| {
            // Do not apply the same targets.
            var target: []const u8 = "";
            switch (target_idx) {
                0 => {},
                1 => {
                    if (self.zig_target.len == 0) continue;
                    target = self.zig_target;
                },
                2 => {
                    if (self.clang_target.len == 0 or
                        utils.strEql(self.clang_target, self.zig_target)) continue;
                    target = self.clang_target;
                },
                else => unreachable,
            }

            for ([_][]const u8{
                self.command.envNameOfFlags() orelse "",
            }) |flags_name| {
                if (flags_name.len == 0 or (target.len > 0 and !self.allow_target_env_flags)) {
                    continue;
                }

                // Get the compiler flags from the environment variable.
                const key = (if (target.len > 0) std.fmt.bufPrint(
                    buf,
                    "{s}_{s}",
                    .{ flags_name, target },
                ) else std.fmt.bufPrint(
                    buf,
                    "ZIG_WRAPPER_{s}",
                    .{flags_name},
                )) catch unreachable;

                // Try <target> and <target> with underscore.
                for (0..2) |loop| {
                    if (loop == 1) {
                        if (std.mem.indexOf(u8, key, "-") == null) break;
                        _ = std.mem.replace(u8, key, "-", "_", key);
                    }

                    // Parse flags.
                    const flags_str = utils.getEnvVar(self.allocator, key) catch continue;
                    defer self.allocator.free(flags_str);
                    var arg_iter = try ArgIteratorGeneral.initTakeOwnership(
                        self.allocator,
                        flags_str,
                    );
                    defer arg_iter.deinit();

                    while (arg_iter.next()) |arg| {
                        try tmp.append(try self.allocator.dupe(u8, arg));
                    }

                    // Do not append the same flags.
                    if (!utils.stringsContains(args.items, tmp.items)) {
                        try args.appendSlice(tmp.items);
                        tmp.clearRetainingCapacity();
                    } else {
                        for (tmp.items) |item| {
                            self.allocator.free(item);
                        }
                        tmp.clearRetainingCapacity();
                    }
                }
            }
        }

        if (!utils.stringsContains(dest.items, args.items)) {
            try dest.appendSlice(args.items);
            args.clearRetainingCapacity();
        } else {
            for (args.items) |item| {
                self.allocator.free(item);
            }
            args.clearRetainingCapacity();
        }
    }

    fn parseCustomArgs(self: *Self, args: []const []const u8, dest: *StringArray) !void {
        var parser = SimpleOptionParser{ .args = args };
        while (parser.hasArgument()) {
            if (parser.parsePositional(true)) |opt| {
                // Check if `opt` is C source file or not.
                if (self.command.isCompiler() and !self.is_linker) {
                    if (utils.strEndsWith(opt, ".c")) {
                        if (std.fs.cwd().access(opt, .{})) |_| {
                            self.input_is_c_file = true;
                        } else |_| {}
                    }
                }
                // Skip positional arguments.
                for (parser.consumed) |arg| {
                    try dest.append(try self.allocator.dupe(u8, arg));
                }
            } else if (parser.parseNamed(ZigArgFilter.query_version_opts, false)) {
                self.is_quering_version = true;
                self.is_linker = false;
                // Do no consume the argument.
                for (parser.consumed) |arg| {
                    try dest.append(try self.allocator.dupe(u8, arg));
                }
            } else if (parser.parseNamed(ZigArgFilter.compile_only_opts, false)) {
                if (self.command.isCompiler()) {
                    self.is_linker = false;
                    if (!self.is_preprocessor and utils.strEql(parser.consumed[0], "-E")) {
                        self.is_preprocessor = true;
                    }
                }
                // Do no consume the argument.
                for (parser.consumed) |arg| {
                    try dest.append(try self.allocator.dupe(u8, arg));
                }
            } else if (parser.parseNamed(&.{ "-shared", "-dll" }, false)) {
                if (self.command.isCompiler()) {
                    self.is_linker = true;
                    self.is_shared_lib = true;
                }
                // Do no consume the argument.
                for (parser.consumed) |arg| {
                    try dest.append(try self.allocator.dupe(u8, arg));
                }
            } else if (parser.parseNamed(&.{ "-target", "--target" }, true)) {
                if (self.zig_target.len == 0) {
                    self.zig_target = try self.allocator.dupe(u8, parser.value);
                }
            } else if (parser.parseNamed(&.{ "-march", "-mcpu" }, true)) {
                if (self.command.isCompiler()) {
                    for (parser.consumed) |arg| {
                        try self.zig_cpu_opts.append(try self.allocator.dupe(u8, arg));
                    }
                } else {
                    // Do no consume the argument.
                    for (parser.consumed) |arg| {
                        try dest.append(try self.allocator.dupe(u8, arg));
                    }
                }
            } else if (parser.parseNamed(&.{"-mtune"}, true)) {
                if (self.command.isCompiler()) {
                    for (parser.consumed) |arg| {
                        try self.zig_cpu_tune_opts.append(try self.allocator.dupe(u8, arg));
                    }
                } else {
                    // Do no consume the argument.
                    for (parser.consumed) |arg| {
                        try dest.append(try self.allocator.dupe(u8, arg));
                    }
                }
            } else if (parser.parseNamed(&.{"--zig"}, true)) {
                if (self.zig_exe.len == 0) {
                    self.zig_exe = try self.allocator.dupe(u8, parser.value);
                }
            } else if (parser.parseNamed(&.{"--clang-target"}, true)) {
                if (self.clang_target.len == 0) {
                    self.clang_target = try self.allocator.dupe(u8, parser.value);
                }
            } else if (parser.parseNamed(&.{"--skip-lib"}, true)) {
                var parts = std.mem.splitAny(u8, parser.value, ",;");
                while (parts.next()) |part| {
                    const v = utils.strTrimRight(part);
                    if (v.len > 0) {
                        const res = try self.skipped_libs.getOrPut(v);
                        if (!res.found_existing) {
                            res.key_ptr.* = try self.allocator.dupe(u8, v);
                            if (std.mem.indexOfAny(u8, v, "?*") != null) {
                                try self.skipped_lib_patterns.append(try self.allocator.dupe(u8, v));
                            }
                        }
                    }
                }
            } else if (parser.parseNamed(&.{"--skip-lib-path"}, true)) {
                var parts = std.mem.splitAny(u8, parser.value, ";");
                while (parts.next()) |part| {
                    const v = utils.strTrimRight(part);
                    if (v.len > 0) {
                        const res = try self.skipped_lib_paths.getOrPut(v);
                        if (!res.found_existing) {
                            res.key_ptr.* = try self.allocator.dupe(u8, v);
                        }
                    }
                }
            } else if (parser.parseNamed(&.{"--allow-target-env-flags"}, false)) {
                self.allow_target_env_flags = true;
            } else if (parser.parseNamed(&.{"--disallow-target-env-flags"}, false)) {
                self.allow_target_env_flags = false;
            } else if (parser.parseNamed(&.{"--enable-dllexport"}, false)) {
                self.disable_dllexport = false;
            } else if (parser.parseNamed(&.{"--disable-dllexport"}, false)) {
                self.disable_dllexport = true;
            } else if (parser.parseNamed(&.{"-o"}, true)) {
                // Save the output file path for post-processing.
                if (parser.consumed.len == 2) {
                    self.cc_output = try self.allocator.dupe(u8, parser.value);
                }
                // Autoconfig uses `zig-cc` to compile DLL, wrongly builds out `.dll.a` instead of `.dll`.
                // We fix it to output the `.dll` file.
                if (parser.consumed.len == 2 and self.command.isCompiler() and
                    utils.strEndsWith(parser.value, ".dll.a"))
                {
                    const dll_a = parser.value;
                    const dll = dll_a[0 .. dll_a.len - 2];
                    const lib_name = dll_a[0 .. dll_a.len - 6];

                    const lib_opt = try std.fmt.allocPrint(
                        self.allocator,
                        "-Wl,--out-implib={s}.lib",
                        .{lib_name},
                    );
                    const dll_lib = lib_opt[17..];

                    try dest.append(try self.allocator.dupe(u8, "-shared"));
                    try dest.append(try self.allocator.dupe(u8, "-o"));
                    try dest.append(try self.allocator.dupe(u8, dll));
                    try dest.append(lib_opt);
                    self.cc_dll_a = try self.allocator.dupe(u8, dll_a);
                    self.cc_dll_lib = try self.allocator.dupe(u8, dll_lib);
                } else {
                    // Do no consume the argument.
                    for (parser.consumed) |arg| {
                        try dest.append(try self.allocator.dupe(u8, arg));
                    }
                }
            } else {
                // Do no consume the argument.
                try dest.append(try self.allocator.dupe(u8, parser.next().?));
            }
        }
    }

    fn fixLibFlag(self: *Self, arg: []const u8) ![]const u8 {
        // `-l<lib>`
        if (self.is_linker and utils.strStartsWith(arg, "-l")) {
            const lib = arg[2..];

            // Trim prefix `winapi_` if the target is Windows.
            if (self.target_is_windows and utils.strStartsWith(lib, "winapi_")) {
                return try std.fmt.allocPrint(self.allocator, "-l{s}", .{lib[7..]});
            }
        }
        return try self.allocator.dupe(u8, arg);
    }

    fn fixCommandFlag(self: *Self, arg: []u8, dest: *StringArray) !void {
        // `-Wl,<linker flags>`
        if (self.is_linker and utils.strStartsWith(arg, "-Wl,")) {
            const buf = arg[4..];
            var buf_used: usize = 0;

            var parts = std.mem.splitAny(u8, buf, ",");
            while (parts.next()) |flag| {
                if (utils.strEndsWith(flag, ".def")) {
                    // `/DEF:<lib>.def`
                    var def_file = flag;
                    if (utils.strStartsWith(def_file, "/DEF:")) {
                        def_file = def_file[5..];
                    }
                    const s = try self.allocator.dupe(u8, def_file);
                    try dest.append(s);
                } else if (utils.strStartsWith(flag, "-l")) {
                    // `-l<lib>`
                    const s = try self.fixLibFlag(flag);
                    try dest.append(s);
                } else if (flag.len > 0) {
                    if (buf_used > 0) {
                        buf[buf_used] = ',';
                        buf_used += 1;
                    }
                    std.mem.copyForwards(u8, buf[buf_used..], flag);
                    buf_used += flag.len;
                }
            }

            if (buf_used > 0) {
                try dest.append(try self.allocator.dupe(u8, arg[0 .. 4 + buf_used]));
            }
            return;
        }

        try dest.append(try self.fixLibFlag(arg));
    }

    fn getlibExts(self: Self, kind: LinkerLibKind) []const []const u8 {
        const windows_exts = [_][]const u8{ ".dll", ".dll.lib", ".dll.a", ".lib", ".a" };
        const linux_exts = [_][]const u8{ ".so", ".a" };
        const apple_exts = [_][]const u8{ ".dylib", ".a" };

        var exts: []const []const u8 = undefined;
        if (self.target_is_windows) {
            exts = &windows_exts;
        } else if (self.target_is_apple) {
            exts = &apple_exts;
        } else {
            exts = &linux_exts;
        }

        return switch (kind) {
            .none => exts,
            .dynamic => exts[0..1],
            .static => exts[1..],
        };
    }

    fn libFromFileName(self: Self, file_name: []const u8) LinkerLib {
        var kind = LinkerLibKind.none;
        var name = std.fs.path.basename(file_name);
        if (utils.strStartsWith(name, ":")) {
            name = name[1..];
            kind = .static;
        }
        if (utils.strStartsWith(name, "lib")) {
            name = name[3..];
        }

        for ([_]LinkerLibKind{ .dynamic, .static }) |k| {
            const exts = self.getlibExts(k);
            for (exts) |ext| {
                if (utils.strEndsWith(name, ext)) {
                    return LinkerLib{
                        .kind = k,
                        .name = name[0 .. name.len - ext.len],
                    };
                }
            }
        }
        return LinkerLib{ .kind = kind, .name = name };
    }

    fn fixLinkLibs(self: *Self) !void {
        const INVALID_PTR: [*]const u8 = @ptrFromInt(std.math.maxInt(usize));
        var args = try StringArray.initCapacity(
            self.allocator,
            self.args.items.len,
        );
        var lib_map = std.StringArrayHashMap(std.ArrayList(LinkerLib)).init(
            self.allocator,
        );
        var path_set = std.StringArrayHashMap(void).init(self.allocator);
        defer {
            args.deinit();
            for (lib_map.values()) |array| {
                array.deinit();
            }
            lib_map.deinit();
            for (path_set.keys()) |path| {
                self.allocator.free(path);
            }
            path_set.deinit();
        }

        var parser = SimpleOptionParser{ .args = self.args.items };
        outer: while (parser.hasArgument()) {
            if (parser.parseNamed(&.{"-l"}, false)) {
                self.allocator.free(parser.consumed[0]);
            } else if (parser.parseNamed(&.{"-l"}, true)) {
                var lib = self.libFromFileName(parser.value);
                lib.index = args.items.len;

                if (self.skipped_libs.contains(lib.name)) {
                    for (parser.consumed) |arg| self.allocator.free(arg);
                    continue;
                }
                for (self.skipped_lib_patterns.items) |pattern| {
                    if (utils.strMatch(pattern, lib.name)) {
                        for (parser.consumed) |arg| self.allocator.free(arg);
                        continue :outer;
                    }
                }

                var lib_ver = utils.libVersionSplit(lib.name);
                if (lib_map.getPtr(lib_ver[0])) |libs| {
                    for (libs.items) |*entry| {
                        const entry_ver = utils.libVersionSplit(entry.name);
                        if (utils.strEql(entry.name, lib.name)) {
                            // Drop the duplicate link library.
                            if (entry.kind == .none and lib.kind != .none) {
                                entry.kind = lib.kind;
                            }
                            for (parser.consumed) |arg| self.allocator.free(arg);
                            continue :outer;
                        }
                        if (utils.versionCompare(entry_ver[1], lib_ver[1]) < 0) {
                            // Sort libraries with the same name in order of their versions.
                            // Swap `entry` and `lib`.
                            const tmp = entry.*;
                            entry.name = lib.name;
                            entry.kind = lib.kind;
                            lib.name = tmp.name;
                            lib.kind = tmp.kind;
                            lib_ver = entry_ver;
                        }
                    }
                    try libs.append(lib);
                } else {
                    var libs = try std.ArrayList(LinkerLib).initCapacity(self.allocator, 4);
                    errdefer libs.deinit();
                    try libs.append(lib);
                    try lib_map.put(lib_ver[0], libs);
                }
            } else if (parser.parseNamed(&.{"-L"}, true)) {
                // normalize path
                if (std.fs.path.relative(
                    self.allocator,
                    ".",
                    parser.value,
                )) |path| {
                    var ok = false;
                    defer if (!ok) self.allocator.free(path);

                    _ = std.mem.replace(u8, path, "\\", "/", path);
                    if (path_set.contains(path)) {
                        for (parser.consumed) |arg| self.allocator.free(arg);
                        continue;
                    }
                    for (self.skipped_lib_paths.keys()) |pattern| {
                        if (utils.strMatch(pattern, path)) {
                            for (parser.consumed) |arg| self.allocator.free(arg);
                            continue :outer;
                        }
                    }

                    try path_set.put(path, {});
                    ok = true;
                } else |_| {}
            } else {
                parser.advance(1);
            }
            try args.appendSlice(parser.consumed);
        }

        // Add "." to the library paths.
        if (!path_set.contains(".")) {
            const cwd = try self.allocator.dupe(u8, ".");
            errdefer self.allocator.free(cwd);
            try path_set.put(cwd, {});
        }

        // Find the library paths and fix link options.
        var buf = std.ArrayList(u8).init(self.allocator);
        defer buf.deinit();
        const lib_exts = self.getlibExts(.none);
        for (lib_map.values()) |libs| {
            next_lib: for (libs.items) |lib| {
                for (path_set.keys()) |path| {
                    for ([_][]const u8{ "lib", "" }) |prefix| {
                        for (lib_exts) |file_ext| {
                            buf.clearRetainingCapacity();
                            try buf.appendSlice(path);
                            try buf.append('/');
                            try buf.appendSlice(prefix);
                            try buf.appendSlice(lib.name);
                            try buf.appendSlice(file_ext);
                            if (std.fs.cwd().access(buf.items, .{})) |_| {
                                const file_lib = self.libFromFileName(buf.items);
                                if (lib.kind == .none or lib.kind == file_lib.kind) {
                                    const lib_opt = if (file_lib.kind == .dynamic)
                                        try std.fmt.allocPrint(self.allocator, "-l{s}", .{file_lib.name})
                                    else
                                        try self.allocator.dupe(u8, buf.items);
                                    self.allocator.free(args.items[lib.index]);
                                    args.items[lib.index] = lib_opt;
                                    continue :next_lib;
                                }
                            } else |_| {}
                        }
                    }
                }

                if (ZigArgFilter.isWeakLib(self, lib.name)) {
                    self.allocator.free(args.items[lib.index]);
                    args.items[lib.index].ptr = INVALID_PTR;
                    continue;
                }

                // Try to fix `-l:<file>` options.
                buf.clearRetainingCapacity();
                try buf.appendSlice("-l");
                try buf.appendSlice(lib.name);
                if (!utils.strEql(buf.items, args.items[lib.index])) {
                    const opt = try self.allocator.dupe(u8, buf.items);
                    self.allocator.free(args.items[lib.index]);
                    args.items[lib.index] = opt;
                }
            }
        }

        // Apply the fixed arguments.
        var arg_num: usize = 0;
        for (args.items) |arg| {
            if (arg.ptr != INVALID_PTR) {
                self.args.items.ptr[arg_num] = arg;
                arg_num += 1;
            }
        }
        self.args.items.len = arg_num;
    }

    fn parseArgument(self: *Self, parser: *SimpleOptionParser) !void {
        switch (self.command) {
            .windres => {
                if (parser.parsePositional(false)) |arg| {
                    if (self.windres_input == null) {
                        self.windres_input = try self.allocator.dupe(u8, arg);
                    } else if (self.windres_output == null) {
                        self.windres_output = try self.allocator.dupe(u8, arg);
                    }
                } else if (parser.parseNamed(&.{ "-i", "--input" }, true)) {
                    self.windres_input = try self.allocator.dupe(u8, parser.value);
                } else if (parser.parseNamed(&.{ "-o", "--output" }, true)) {
                    self.windres_output = try self.allocator.dupe(u8, parser.value);
                } else if (parser.parseNamed(&.{ "-J", "--input-format" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-O", "--output-format" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-F", "--target" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-I", "--include-dir" }, true)) {
                    try self.args.append(try self.allocator.dupe(u8, "/i"));
                    try self.args.append(try self.allocator.dupe(u8, parser.value));
                } else if (parser.parseNamed(&.{"--preprocessor"}, true)) {
                    // skip
                } else if (parser.parseNamed(&.{"--preprocessor-arg"}, true)) {
                    if (self.windres_preprocessor_arg) |pre_arg| {
                        self.allocator.free(pre_arg);
                        self.windres_preprocessor_arg = null;
                        if (utils.strEql(pre_arg, "-MF")) {
                            self.windres_depfile = try self.allocator.dupe(u8, parser.value);
                        }
                    } else if (utils.strEql(parser.value, "-MD")) {
                        if (self.windres_depfile == null) {
                            self.windres_depfile = try self.allocator.dupe(u8, "");
                        }
                    } else if (utils.strEql(parser.value, "-MF")) {
                        self.windres_preprocessor_arg = try self.allocator.dupe(u8, parser.value);
                    } else {
                        // Skip other processor arguments.
                    }
                } else if (parser.parseNamed(&.{ "-D", "--define" }, true)) {
                    try self.args.append(try self.allocator.dupe(u8, "/d"));
                    try self.args.append(try self.allocator.dupe(u8, parser.value));
                } else if (parser.parseNamed(&.{ "-U", "--undefine" }, true)) {
                    try self.args.append(try self.allocator.dupe(u8, "/u"));
                    try self.args.append(try self.allocator.dupe(u8, parser.value));
                } else if (parser.parseNamed(&.{ "-v", "--verbose" }, false)) {
                    try self.args.append(try self.allocator.dupe(u8, "/v"));
                } else if (parser.parseNamed(&.{ "-c", "--codepage" }, true)) {
                    try self.args.append(try self.allocator.dupe(u8, "/c"));
                    try self.args.append(try self.allocator.dupe(u8, parser.value));
                } else if (parser.parseNamed(&.{ "-l", "--language" }, true)) {
                    try self.args.append(try self.allocator.dupe(u8, "/ln"));
                    try self.args.append(try self.allocator.dupe(u8, parser.value));
                } else if (parser.parseNamed(&.{"--use-temp-file"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{"--no-use-temp-file"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{"-r"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-h", "--help" }, false)) {
                    try self.args.append(try self.allocator.dupe(u8, "/h"));
                } else {
                    _ = parser.next();
                }

                if (!parser.hasArgument()) {
                    try self.args.append(try self.allocator.dupe(u8, "--"));
                    if (self.windres_input) |v| try self.args.append(try self.allocator.dupe(u8, v));
                    if (self.windres_output) |v| try self.args.append(try self.allocator.dupe(u8, v));
                }
            },
            else => {
                _ = try self.arg_filter.next(self, parser, &self.args);
            },
        }
    }

    fn writeFlagsFile(self: *Self) !void {
        // Do not write flags file if the command is not `cc`, `c++` or `ld`.
        if (!self.command.isCompiler() and !self.is_linker) return;

        // Do not write `@<flags file>` if the size of arguments does not exceed the system limits.
        var argv_size: usize = 8;
        for (self.args.items) |arg| {
            argv_size += arg.len + 1;
            var s = arg;
            while (std.mem.indexOfAny(u8, s, "\\\"'")) |i| {
                // two quotes
                if (s.len == arg.len) argv_size += 2;
                // escape character
                argv_size += 1;
                s = s[i + 1 ..];
            }
        }
        if (argv_size <= utils.sysArgMax()) return;

        // Write flags to buffer.
        var buffer = try std.ArrayList(u8).initCapacity(
            self.allocator,
            argv_size,
        );
        defer buffer.deinit();
        for (self.args.items[2..], 0..) |arg, i| {
            if (i > 0) try buffer.append(' ');
            try utils.strEscapeAppend(&buffer, arg);
        }

        var at_file_opt: []u8 = undefined;
        if (self.at_file_opt) |v| {
            at_file_opt = try self.allocator.dupe(u8, v);
            // Write to file.
            var file = try std.fs.cwd().createFile(
                at_file_opt[1..],
                .{ .truncate = true },
            );
            defer file.close();
            try file.seekTo(0);
            try file.writeAll(buffer.items);
            try file.setEndPos(try file.getPos());
        } else {
            var flags_file = try TempFile.init(self.allocator);
            errdefer flags_file.deinit();
            try flags_file.write(buffer.items);
            flags_file.close();

            at_file_opt = try std.fmt.allocPrint(self.allocator, "@{s}", .{flags_file.getPath()});
            self.flags_file = flags_file;
        }

        // Free the items that are being discarded
        for (self.args.items[2..]) |arg| {
            self.allocator.free(arg);
        }
        self.args.items.len = 2;
        // Set the @<file_path> flag.
        try self.args.append(at_file_opt);
    }

    fn postProcess(self: *Self, success: bool) !void {
        switch (self.command) {
            .cc, .cxx => {
                if (success) {
                    // Copy `.lib` file to `.dll.a` file.
                    if (self.cc_dll_lib) |dll_lib| {
                        if (self.cc_dll_a) |dll_a| {
                            const cwd = std.fs.cwd();
                            try cwd.copyFile(dll_lib, cwd, dll_a, .{});
                        }
                    }
                }
            },
            .windres => {
                if (self.windres_depfile) |depfile| {
                    var path = try self.allocator.dupe(u8, depfile);
                    defer self.allocator.free(path);
                    if (depfile.len == 0) {
                        const output = self.windres_output orelse return;
                        self.allocator.free(path);
                        path = try std.fmt.allocPrint(self.allocator, "{s}.d", .{output});
                    }
                    if (success) {
                        // Create a pseudo dependency file.
                        (try std.fs.cwd().createFile(path, .{
                            .truncate = true,
                        })).close();
                    } else {
                        std.fs.cwd().deleteFile(path) catch {};
                    }
                }
            },
            else => {},
        }

        // Work around:
        //    https://github.com/ziglang/zig/issues/22847
        //    zig build: Incorrect path prefix added to Linux shared library paths in ELF dynamic section
        if (self.cc_output) |output| {
            if (self.is_linker and !self.target_is_windows) {
                // Get the real path of `elf_path_fixer.py`
                const script_dir = std.fs.path.dirname(self.sys_argv0) orelse ".";
                const script = try std.fs.path.join(self.allocator, &.{
                    script_dir,
                    "elf_path_fixer.py",
                });
                defer self.allocator.free(script);
                if ((std.fs.accessAbsolute(script, .{}) catch null) == null) {
                    return;
                }

                // Arguments passed to `elf_path_fixer.py`.
                var args = StringArray.init(self.allocator);
                defer utils.freeStringArray(self.allocator, &args);

                if (builtin.os.tag == .windows) {
                    try args.append(try self.allocator.dupe(u8, "python.exe"));
                } else {
                    try args.append(try self.allocator.dupe(u8, "python3"));
                }

                try args.append(try self.allocator.dupe(u8, script));
                try args.append(try self.allocator.dupe(u8, output));
                try args.append(try self.allocator.dupe(u8, "--no-backup"));
                try args.append(try self.allocator.dupe(u8, "--quiet"));

                // Remove paths containing backslash on Windows.
                try args.append(try self.allocator.dupe(u8, "-t"));
                try args.append(try self.allocator.dupe(u8, "[:\\\\]"));
                try args.append(try self.allocator.dupe(u8, "-t"));
                try args.append(try self.allocator.dupe(u8, "^/mnt/[a-z]/"));
                try args.append(try self.allocator.dupe(u8, "-t"));
                try args.append(try self.allocator.dupe(u8, "/.rmake/"));

                if (utils.getEnvVar(self.allocator, "CARGO_WORKSPACE_DIR")) |ws| {
                    defer self.allocator.free(ws);
                    const ws_esc = try std.mem.replaceOwned(u8, self.allocator, ws, "\\", "\\\\");
                    try args.append(try self.allocator.dupe(u8, "-t"));
                    try args.append(ws_esc);
                } else |_| {}

                for (&[_][]const u8{ "CMKABE_TARGET", "CMKABE_CARGO_TARGET" }) |env| {
                    if (utils.getEnvVar(self.allocator, env)) |target| {
                        defer self.allocator.free(target);
                        try args.append(try self.allocator.dupe(u8, "-t"));
                        try args.append(try std.fmt.allocPrint(self.allocator, "{s}/", .{target}));
                    } else |_| {}
                }

                var child = std.process.Child.init(args.items, self.allocator);
                const exit_code = (try child.spawnAndWait()).Exited;
                if (exit_code != 0) {
                    self.log.print("***** elf_path_fixer.py error code: {d}\n", .{exit_code});
                }
            }
        }
    }
};

pub const LinkerLibKind = enum { none, static, dynamic };

pub const LinkerLib = struct {
    kind: LinkerLibKind = .none,
    name: []const u8 = "",
    index: usize = 0,
};

pub fn main() noreturn {
    var status: u8 = 0;
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    defer {
        _ = gpa.detectLeaks();
        _ = gpa.deinit();
        std.process.exit(status);
    }
    errdefer |err| {
        _ = gpa.detectLeaks();
        _ = std.io.getStdErr().writer().print("error: {}\n", .{err}) catch {};
        std.process.exit(1);
    }
    var zig = try ZigWrapper.init(gpa.allocator());
    defer zig.deinit();
    status = try zig.run();
}
