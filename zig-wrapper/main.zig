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
const elf_mod = @import("elf.zig");

const StringArray = std.array_list.Managed([]const u8);
const StringSet = std.array_hash_map.String(void);
const ArgIteratorGeneral = std.process.Args.IteratorGeneral(.{});

pub const ZigWrapper = struct {
    const Self = @This();
    io: std.Io,
    allocator: std.mem.Allocator,
    environ_map: *std.process.Environ.Map,
    log: ZigLog,
    sys_argv0: ?[]const u8 = null,
    sys_argv: StringArray,
    zig_exe: ?[]const u8 = null,

    /// The current Zig command.
    command: ZigCommand = ZigCommand.cc,

    is_quering_version: bool = false,
    is_searching_dirs: bool = false,
    queried_program_name: ?ZigCommand = null,

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
    zig_target: ?[]const u8 = null,
    /// <arch>-<vendor>-<os>-<abi>
    clang_target: ?[]const u8 = null,
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
    target_is_gnu: bool = false,
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

    pub fn is_quering_zig_info(self: *Self) bool {
        return self.is_quering_version or self.is_searching_dirs or self.queried_program_name != null;
    }

    pub fn init(proc_init: std.process.Init) !Self {
        const io_ = proc_init.io;
        const allocator_ = proc_init.gpa;
        const environ_map_ = proc_init.environ_map;

        // logger
        const log_path = utils.getEnvVar(environ_map_, "ZIG_WRAPPER_LOG");
        const log = try ZigLog.init(io_, log_path);

        var self = Self{
            .io = io_,
            .allocator = allocator_,
            .environ_map = environ_map_,
            .log = log,
            .sys_argv = StringArray.init(allocator_),
            .zig_cpu_opts = StringArray.init(allocator_),
            .zig_cpu_tune_opts = StringArray.init(allocator_),
            .skipped_libs = .{},
            .skipped_lib_patterns = StringArray.init(allocator_),
            .skipped_lib_paths = .{},
            .arg_filter = ZigArgFilterMap.init(allocator_),
            .args = StringArray.init(allocator_),
        };
        errdefer self.deinit();

        // Collect `argv[0..]`...
        var argv = StringArray.init(self.allocator);
        defer utils.freeStringArray(self.allocator, &argv);

        var arg_iter = try proc_init.minimal.args.iterateAllocator(self.allocator);
        defer arg_iter.deinit();
        if (arg_iter.next()) |argv0| {
            self.sys_argv0 = try self.allocator.dupe(u8, argv0);
        }
        while (arg_iter.next()) |arg| {
            if (utils.strStartsWith(arg, "@")) {
                // Parse the flags file.
                if (self.parseFileFlags(arg[1..], &argv, 0)) |_| {
                    if (utils.strTake(&self.at_file_opt)) |v| self.allocator.free(v);
                    self.at_file_opt = try self.allocator.dupe(u8, arg);
                    continue;
                } else |_| {
                    // Fallback: treat as a literal argument
                }
            }

            // If the flags file is not the last argument, ignore it.
            if (self.at_file_opt) |v| {
                self.allocator.free(v);
                self.at_file_opt = null;
            }
            try utils.dupeAndAppend(u8, &argv, self.allocator, arg);
        }

        // Write the input command line to log.
        if (self.log.enabled()) {
            self.log.print("{s}", .{self.sys_argv0 orelse ""});
            for (argv.items) |arg| {
                self.log.print(" {s}", .{arg});
            }
            self.log.write("\n");
        }

        // Parse the command type from `argv[0]`.
        const stem = std.fs.path.stem(self.sys_argv0 orelse "");
        self.command = ZigCommand.fromStr(
            stem[if (std.mem.lastIndexOfScalar(u8, stem, '-')) |s| s + 1 else 0..],
        ) orelse return error.InvalidZigCommand;
        if (self.command.isCompiler() or self.command == .ld) {
            self.is_linker = true;
        }

        // Parse environment variables.
        self.zig_exe = utils.dupeEnvVar(self.environ_map, self.allocator, "ZIG_EXECUTABLE");
        self.zig_target = utils.dupeEnvVar(self.environ_map, self.allocator, "ZIG_WRAPPER_TARGET");
        self.clang_target = utils.dupeEnvVar(self.environ_map, self.allocator, "ZIG_WRAPPER_CLANG_TARGET");

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
        for (argv.items) |arg| {
            try utils.dupeAndAppend(u8, &self.sys_argv, self.allocator, arg);
        }
        utils.freeStringArray(self.allocator, &argv);
        argv = StringArray.init(self.allocator);

        // Set default values.
        if (self.zig_exe == null) {
            self.zig_exe = try std.fmt.allocPrint(
                self.allocator,
                "zig{s}",
                .{builtin.os.tag.exeFileExt(builtin.cpu.arch)},
            );
        }
        if (self.zig_target == null) {
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
        if (self.clang_target == null) {
            self.clang_target = try self.allocator.dupe(u8, utils.extractPureTriple(self.zig_target.?));
        }

        self.target_is_windows = std.mem.indexOf(u8, self.clang_target.?, "-windows") != null;
        self.target_is_android = std.mem.indexOf(u8, self.clang_target.?, "-android") != null;
        self.target_is_linux = std.mem.indexOf(u8, self.clang_target.?, "-linux") != null;
        self.target_is_apple = std.mem.indexOf(u8, self.clang_target.?, "-apple") != null or
            std.mem.indexOf(u8, self.clang_target.?, "-macos") != null or
            std.mem.indexOf(u8, self.clang_target.?, "-darwin") != null;
        self.target_is_wasm = utils.strStartsWith(self.clang_target.?, "wasm") or
            utils.strEndsWith(self.clang_target.?, "-emscripten");
        self.target_is_msvc = utils.reFindString("-msvc$", self.clang_target.?) != null or
            utils.reFindString("-msvc[-.]", self.clang_target.?) != null;
        self.target_is_musl = utils.reFindString("-musl$", self.clang_target.?) != null or
            utils.reFindString("-musl[-.]", self.clang_target.?) != null;
        self.target_is_gnu = utils.reFindString("-gnu$", self.clang_target.?) != null or
            utils.reFindString("-gnu[-.]", self.clang_target.?) != null;

        ZigArgFilter.initFilterMap(&self, &self.arg_filter);
        return self;
    }

    pub fn deinit(self: *Self) void {
        if (self.flags_file) |*flags_file| {
            flags_file.deinit();
            self.flags_file = null;
        }
        if (self.sys_argv0) |v| self.allocator.free(v);
        if (self.zig_exe) |v| self.allocator.free(v);
        if (self.zig_target) |v| self.allocator.free(v);
        if (self.clang_target) |v| self.allocator.free(v);
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
        try utils.dupeAndAppend(u8, &self.args, self.allocator, self.zig_exe.?);

        // Zig command
        try utils.dupeAndAppend(u8, &self.args, self.allocator, self.command.toName());

        // `cc`, `c++`: -target <target> [-march=<cpu>] [-mtune=<cpu>]
        if (self.command.isCompiler()) blk: {
            // `-target`
            try utils.dupeAndAppend(u8, &self.args, self.allocator, "-target");
            {
                var zig_target = self.zig_target.?;
                if (self.is_quering_zig_info()) {
                    zig_target = utils.extractPureTriple(zig_target);
                }
                try utils.dupeAndAppend(u8, &self.args, self.allocator, zig_target);
                if (self.is_quering_zig_info()) break :blk;
            }

            // Disable 'date-time' error by default.
            try utils.dupeAndAppend(u8, &self.args, self.allocator, "-Wno-error=date-time");

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
                try utils.dupeAndAppend(u8, &self.args, self.allocator, "-fno-sanitize=undefined");

                // Fix compilation issues of Rust native crates.
                if (self.disable_dllexport) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "-fvisibility-ms-compat");
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "-Ddllexport=nodebug");
                }
            }
            if (self.target_is_windows) {
                // Undefine `_WIN32_WINNT` for Windows targets.
                try utils.dupeAndAppend(u8, &self.args, self.allocator, "-U_WIN32_WINNT");
            }
            if (self.is_linker) {
                try utils.dupeAndAppend(u8, &self.args, self.allocator, "-lc++");
                try utils.dupeAndAppend(u8, &self.args, self.allocator, "-lc++abi");
                try utils.dupeAndAppend(u8, &self.args, self.allocator, "-lomp");
            }
        }

        {
            var argv = try StringArray.initCapacity(self.allocator, self.sys_argv.items.len);
            defer utils.freeStringArray(self.allocator, &argv);
            std.mem.swap(StringArray, &self.sys_argv, &argv);
            for (argv.items) |arg| {
                try self.fixCommandFlag(arg, &self.sys_argv);
            }
        }

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
        var exit_code: u8 = 0;
        if (try query_zig_info(self)) |res| {
            defer self.allocator.free(res);
            const stdout_file = std.Io.File.stdout();
            try stdout_file.writeStreamingAll(self.io, res);
            self.log.printExecResult(exit_code, res, "");
        } else if (self.log.enabled()) {
            const run_res = try std.process.run(self.allocator, self.io, .{
                .argv = self.args.items,
                .stderr_limit = std.Io.Limit.limited(1 * 1024 * 1024),
                .stdout_limit = std.Io.Limit.limited(1 * 1024 * 1024),
            });
            defer self.allocator.free(run_res.stdout);
            defer self.allocator.free(run_res.stderr);

            exit_code = switch (run_res.term) {
                .exited => |code| code,
                else => 1,
            };
            const stdout_file = std.Io.File.stdout();
            const stderr_file = std.Io.File.stderr();
            try stderr_file.writeStreamingAll(self.io, run_res.stderr);
            try stdout_file.writeStreamingAll(self.io, run_res.stdout);
            self.log.printExecResult(exit_code, run_res.stdout, run_res.stderr);
        } else {
            var child = try std.process.spawn(self.io, .{
                .argv = self.args.items,
                .stdin = .inherit,
                .stdout = .inherit,
                .stderr = .inherit,
            });
            const term = try child.wait(self.io);
            exit_code = switch (term) {
                .exited => |code| code,
                else => 1,
            };
        }
        try self.postProcess(exit_code == 0);
        if (exit_code != 0) {
            self.log.print("***** error code: {d}\n", .{exit_code});
        }
        return exit_code;
    }

    fn query_zig_info(self: *Self) std.mem.Allocator.Error!?[]u8 {
        if (self.queried_program_name) |name| {
            // replace the tailing "-<command>" argv[0] with "-<name>"
            var exe_name = self.sys_argv0.?;
            var ext: []const u8 = "";
            if (utils.strEndsWith(exe_name, ".exe")) {
                exe_name = exe_name[0 .. exe_name.len - 4];
                ext = ".exe";
            }
            const prefix = if (std.mem.lastIndexOfScalar(u8, exe_name, '-')) |idx|
                exe_name[0 .. idx + 1]
            else
                "";

            var prog_name = @tagName(name);
            if (utils.strEndsWith(exe_name, "gcc") or utils.strEndsWith(exe_name, "g++")) {
                switch (name) {
                    .cc => prog_name = "gcc",
                    .cxx => prog_name = "g++",
                    else => {},
                }
            }
            return try std.fmt.allocPrint(self.allocator, "{s}{s}{s}\n", .{ prefix, prog_name, ext });
        }
        return null;
    }

    pub fn parseFileFlags(self: *Self, path: []const u8, dest: *StringArray, depth: usize) anyerror!void {
        if (depth > 10) return error.FlagsFileTooDeep;

        // Open the file for reading
        const cwd = std.Io.Dir.cwd();
        var file = try cwd.openFile(self.io, path, .{});
        defer file.close(self.io);

        // Get the file size
        const file_size = try file.length(self.io);

        // Allocate a buffer to hold the file content
        const flags_str = try self.allocator.alloc(u8, file_size);
        defer self.allocator.free(flags_str);

        // Read the file content into the buffer
        _ = try file.readPositionalAll(self.io, flags_str, 0);

        // Parse the flags
        var arg_iter = try ArgIteratorGeneral.init(
            self.allocator,
            flags_str,
        );
        defer arg_iter.deinit();
        while (arg_iter.next()) |arg| {
            if (utils.strStartsWith(arg, "@")) {
                // Recursively parse the nested flags file.
                if (self.parseFileFlags(arg[1..], dest, depth + 1)) |_| {
                    continue;
                } else |_| {
                    // Fallback: treat as a literal argument
                }
            }
            try utils.dupeAndAppend(u8, dest, self.allocator, arg);
        }
    }

    fn parseEnvFlags(self: *Self, dest: *StringArray) !void {
        // Do not use environment variables if we are querying Zig info
        if (self.is_quering_zig_info()) {
            return;
        }

        const buf = try self.allocator.alloc(u8, 32 + @max(
            if (self.zig_target) |t| t.len else 0,
            if (self.clang_target) |t| t.len else 0,
        ));
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
                    if (self.zig_target == null) continue;
                    target = self.zig_target.?;
                },
                2 => {
                    if (self.clang_target == null or self.zig_target == null or
                        utils.strEql(self.clang_target.?, self.zig_target.?)) continue;
                    target = self.clang_target.?;
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
                    if (utils.getEnvVar(self.environ_map, key)) |flags_str| {
                        var arg_iter = try ArgIteratorGeneral.init(
                            self.allocator,
                            flags_str,
                        );
                        defer arg_iter.deinit();

                        while (arg_iter.next()) |arg| {
                            try utils.dupeAndAppend(u8, &tmp, self.allocator, arg);
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
                        if (std.Io.Dir.cwd().access(self.io, opt, .{})) |_| {
                            self.input_is_c_file = true;
                        } else |_| {}
                    }
                }
                // Skip positional arguments.
                for (parser.consumed) |arg| {
                    try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                }
            } else if (parser.parseNamed(ZigArgFilter.query_version_opts, false) or
                (parser.parseNamed(ZigArgFilter.compiler_query_version_opts, false) and
                    args.len == 1))
            {
                self.is_quering_version = true;
                self.is_linker = false;
                // Do no consume the argument.
                for (parser.consumed) |arg| {
                    try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                }
            } else if (parser.parseNamed(ZigArgFilter.search_dir_opts, false)) {
                self.is_searching_dirs = true;
                self.is_linker = false;
                // Do no consume the argument.
                for (parser.consumed) |arg| {
                    try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                }
            } else if (parser.parseNamed(&.{"-print-prog-name"}, true)) {
                self.queried_program_name = ZigCommand.fromStr(parser.value);
                self.is_linker = false;
            } else if (parser.parseNamed(ZigArgFilter.compile_only_opts, false)) {
                if (self.command.isCompiler()) {
                    self.is_linker = false;
                    if (!self.is_preprocessor and utils.strEql(parser.consumed[0], "-E")) {
                        self.is_preprocessor = true;
                    }
                }
                // Do no consume the argument.
                for (parser.consumed) |arg| {
                    try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                }
            } else if (parser.parseNamed(&.{ "-shared", "-dll" }, false)) {
                if (self.command.isCompiler()) {
                    self.is_linker = true;
                    self.is_shared_lib = true;
                }
                // Do no consume the argument.
                for (parser.consumed) |arg| {
                    try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                }
            } else if (parser.parseNamed(&.{ "-target", "--target" }, true)) {
                if (self.zig_target == null) {
                    self.zig_target = try self.allocator.dupe(u8, parser.value);
                }
            } else if (parser.parseNamed(&.{ "-march", "-mcpu" }, true)) {
                if (self.command.isCompiler()) {
                    for (parser.consumed) |arg| {
                        try utils.dupeAndAppend(u8, &self.zig_cpu_opts, self.allocator, arg);
                    }
                } else {
                    // Do no consume the argument.
                    for (parser.consumed) |arg| {
                        try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                    }
                }
            } else if (parser.parseNamed(&.{"-mtune"}, true)) {
                if (self.command.isCompiler()) {
                    for (parser.consumed) |arg| {
                        try utils.dupeAndAppend(u8, &self.zig_cpu_tune_opts, self.allocator, arg);
                    }
                } else {
                    // Do no consume the argument.
                    for (parser.consumed) |arg| {
                        try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                    }
                }
            } else if (parser.parseNamed(&.{"--zig"}, true)) {
                if (utils.strTake(&self.zig_exe)) |v| self.allocator.free(v);
                self.zig_exe = try self.allocator.dupe(u8, parser.value);
            } else if (parser.parseNamed(&.{"--clang-target"}, true)) {
                if (utils.strTake(&self.clang_target)) |v| self.allocator.free(v);
                self.clang_target = try self.allocator.dupe(u8, parser.value);
            } else if (parser.parseNamed(&.{"--skip-lib"}, true)) {
                var parts = std.mem.splitAny(u8, parser.value, ",;");
                while (parts.next()) |part| {
                    const v = utils.strTrimEnd(part);
                    if (v.len > 0) {
                        const res = try self.skipped_libs.getOrPut(self.allocator, v);
                        if (!res.found_existing) {
                            res.key_ptr.* = try self.allocator.dupe(u8, v);
                            if (std.mem.indexOfAny(u8, v, "?*") != null) {
                                try utils.dupeAndAppend(u8, &self.skipped_lib_patterns, self.allocator, v);
                            }
                        }
                    }
                }
            } else if (parser.parseNamed(&.{"--skip-lib-path"}, true)) {
                var parts = std.mem.splitAny(u8, parser.value, ";");
                while (parts.next()) |part| {
                    const v = utils.strTrimEnd(part);
                    if (v.len > 0) {
                        const res = try self.skipped_lib_paths.getOrPut(self.allocator, v);
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
                    if (utils.strTake(&self.cc_output)) |v| self.allocator.free(v);
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
                    errdefer self.allocator.free(lib_opt);
                    const dll_lib = lib_opt[17..];

                    try utils.dupeAndAppend(u8, dest, self.allocator, "-shared");
                    try utils.dupeAndAppend(u8, dest, self.allocator, "-o");
                    try utils.dupeAndAppend(u8, dest, self.allocator, dll);
                    try dest.append(lib_opt);
                    if (utils.strTake(&self.cc_dll_a)) |v| self.allocator.free(v);
                    self.cc_dll_a = try self.allocator.dupe(u8, dll_a);
                    if (utils.strTake(&self.cc_dll_lib)) |v| self.allocator.free(v);
                    self.cc_dll_lib = try self.allocator.dupe(u8, dll_lib);
                } else {
                    // Do no consume the argument.
                    for (parser.consumed) |arg| {
                        try utils.dupeAndAppend(u8, dest, self.allocator, arg);
                    }
                }
            } else {
                // Do no consume the argument.
                try utils.dupeAndAppend(u8, dest, self.allocator, parser.next().?);
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

    fn fixCommandFlag(self: *Self, arg: []const u8, dest: *StringArray) !void {
        // Fix "error: libc of the specified target requires dynamic linking"
        if (self.is_linker and utils.strEql(arg, "-static")) {
            if (!(self.target_is_linux and self.target_is_gnu)) {
                try utils.dupeAndAppend(u8, dest, self.allocator, arg);
            }
            return;
        }

        // `-Wl,<linker flags>`
        if (self.is_linker and utils.strStartsWith(arg, "-Wl,")) {
            const buf = arg[4..];

            var parts = std.mem.splitAny(u8, buf, ",");
            while (parts.next()) |flag| {
                if (flag.len == 0) continue;
                if (utils.strEndsWith(flag, ".def")) {
                    // `/DEF:<lib>.def`
                    var def_file = flag;
                    if (utils.strStartsWith(def_file, "/DEF:")) {
                        def_file = def_file[5..];
                    }
                    try utils.dupeAndAppend(u8, dest, self.allocator, def_file);
                } else if (utils.strStartsWith(flag, "-l")) {
                    // `-l<lib>`
                    const s = try self.fixLibFlag(flag);
                    errdefer self.allocator.free(s);
                    try dest.append(s);
                } else {
                    // Pass other flags as -Wl,<flag>
                    try utils.allocPrintAndAppend(dest, self.allocator, "-Wl,{s}", .{flag});
                }
            }
            return;
        }

        const fixed = try self.fixLibFlag(arg);
        errdefer self.allocator.free(fixed);
        try dest.append(fixed);
    }

    fn getlibExts(self: Self, kind: LinkerLibKind) []const []const u8 {
        const windows_exts = [_][]const u8{ ".dll", ".dll.lib", ".dll.a", ".lib", ".a" };
        const linux_exts = [_][]const u8{ ".so", ".a" };
        const apple_exts = [_][]const u8{ ".dylib", ".a" };

        if (self.target_is_windows) {
            return switch (kind) {
                .none => &windows_exts,
                .dynamic => windows_exts[0..3],
                .static => windows_exts[3..],
            };
        } else if (self.target_is_apple) {
            return switch (kind) {
                .none => &apple_exts,
                .dynamic => apple_exts[0..1],
                .static => apple_exts[1..],
            };
        } else {
            return switch (kind) {
                .none => &linux_exts,
                .dynamic => linux_exts[0..1],
                .static => linux_exts[1..],
            };
        }
    }

    fn getlibExtsForMode(self: Self, mode: LinkMode) []const []const u8 {
        return switch (mode) {
            .dynamic => self.getlibExts(.none),
            .static => self.getlibExts(.static),
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

    /// Fixes library linkage parameters by resolving library references (`-l<name>`)
    /// into absolute paths (for static libraries) or normalized library flags (for dynamic libraries).
    ///
    /// ### Strategy and Implementation Details:
    ///
    /// 1. **Active Link Mode Tracking**:
    ///    The method maintains a state variable (`active_mode`) representing the active linker mode
    ///    (`.dynamic` or `.static`), which is toggled when switches like `-static`, `-Bstatic`,
    ///    `-Bdynamic`, `-Wl,-Bstatic`, or `-Wl,-Bdynamic` are encountered.
    ///
    /// 2. **Library and Path Parsing**:
    ///    - Library references (`-l<name>`) are parsed and bound to the active link mode.
    ///    - Library search paths (`-L<path>` and `-Wl,-L<path>`) are normalized and registered to `path_set`.
    ///
    /// 3. **Library Deduplication & Version Sorting**:
    ///    The method deduplicates referenced libraries. If the same library is requested multiple times,
    ///    it retains only the latest/highest version found (using a semantic version comparison).
    ///
    /// 4. **Flexible Two-Pass Search and Fallback**:
    ///    For each resolved library:
    ///    - **Pass 1 (Preferred Mode)**: The wrapper first searches the path set using the active link mode's
    ///      extensions (e.g. static `.lib`/`.a` under `-Bstatic`, or dynamic `.dll`/`.dll.a`/`.dll.lib` under `-Bdynamic`).
    ///    - **Pass 2 (Alternative Mode Fallback)**: If the library is not found in the preferred mode, it falls
    ///      back to searching with the alternative link mode's extensions. This prevents link failures when build
    ///      tools mix dynamic and static dependencies without adhering strictly to linkage flags.
    ///    - **Pass-through**: If the library cannot be resolved in either mode (e.g., standard runtime libraries
    ///      like `compiler-rt` or `libc`), the wrapper preserves the original linker flag as-is to let the backend compiler/linker handle it.
    fn fixLinkLibs(self: *Self) !void {
        const INVALID_PTR: [*]const u8 = "~~INVALIDPTR~~";

        var args = try StringArray.initCapacity(
            self.allocator,
            self.args.items.len,
        );
        errdefer {
            for (args.items) |arg| {
                if (arg.ptr != INVALID_PTR) self.allocator.free(arg);
            }
            args.deinit();
        }

        // lib_map: key - string reference, value - owned list<LinkerLib>
        var lib_map = std.array_hash_map.String(std.array_list.Managed(LinkerLib)){};
        // path_set: key - owned string
        var path_set = std.array_hash_map.String(void){};
        defer {
            for (lib_map.values()) |array| {
                array.deinit();
            }
            lib_map.deinit(self.allocator);
            for (path_set.keys()) |path| {
                self.allocator.free(path);
            }
            path_set.deinit(self.allocator);
        }

        var active_mode = LinkMode.dynamic;
        for (self.args.items) |arg| {
            if (utils.strEql(arg, "-static")) {
                active_mode = .static;
                break;
            }
        }

        const cwd = try std.process.currentPathAlloc(self.io, self.allocator);
        defer self.allocator.free(cwd);

        var parser = SimpleOptionParser{ .args = self.args.items };
        outer: while (parser.hasArgument()) {
            if (parser.parseNamed(&.{"-l"}, true)) {
                var lib = self.libFromFileName(parser.value);
                lib.index = args.items.len;
                lib.mode = active_mode;

                if (self.skipped_libs.contains(lib.name)) {
                    continue;
                }
                for (self.skipped_lib_patterns.items) |pattern| {
                    if (utils.strMatch(pattern, lib.name)) {
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
                            continue :outer;
                        }
                        if (utils.versionCompare(entry_ver[1], lib_ver[1]) < 0) {
                            // Sort libraries with the same name in order of their versions.
                            // Swap `entry` and `lib`.
                            const tmp = entry.*;
                            entry.name = lib.name;
                            entry.kind = lib.kind;
                            entry.mode = lib.mode;
                            lib.name = tmp.name;
                            lib.kind = tmp.kind;
                            lib.mode = tmp.mode;
                            lib_ver = entry_ver;
                        }
                    }
                    try libs.append(lib);
                } else {
                    var libs = try std.array_list.Managed(LinkerLib).initCapacity(self.allocator, 4);
                    errdefer libs.deinit();
                    try libs.append(lib);
                    try lib_map.put(self.allocator, lib_ver[0], libs);
                }
                for (parser.consumed) |arg| {
                    try utils.dupeAndAppend(u8, &args, self.allocator, arg);
                }
                continue;
            }

            var is_path = false;
            var path_val: []const u8 = undefined;
            if (parser.parseNamed(&.{"-L"}, true)) {
                is_path = true;
                path_val = parser.value;
            } else if (parser.first()) |arg| {
                if (utils.strStartsWith(arg, "-Wl,-L")) {
                    is_path = true;
                    path_val = arg[6..];
                    parser.advance(1);
                }
            }

            if (is_path) {
                if (std.fs.path.relative(
                    self.allocator,
                    cwd,
                    self.environ_map,
                    ".",
                    path_val,
                )) |path| {
                    var ok = false;
                    defer if (!ok) self.allocator.free(path);

                    _ = std.mem.replace(u8, path, "\\", "/", path);
                    if (path_set.contains(path)) {
                        continue;
                    }
                    for (self.skipped_lib_paths.keys()) |pattern| {
                        if (utils.strMatch(pattern, path)) {
                            continue :outer;
                        }
                    }

                    try path_set.put(self.allocator, path, {});
                    ok = true;
                } else |err| {
                    if (err == error.OutOfMemory) return err;
                }
                for (parser.consumed) |arg| {
                    try utils.dupeAndAppend(u8, &args, self.allocator, arg);
                }
                continue;
            }

            if (parser.first()) |arg| {
                if (utils.strEql(arg, "-static") or
                    utils.strEql(arg, "-Bstatic") or
                    utils.strEql(arg, "-Wl,-Bstatic") or
                    utils.strEql(arg, "-Wl,-dn") or
                    utils.strEql(arg, "-Wl,-non_shared") or
                    utils.strEql(arg, "-Wl,-static"))
                {
                    active_mode = .static;
                } else if (utils.strEql(arg, "-Bdynamic") or
                    utils.strEql(arg, "-Wl,-Bdynamic") or
                    utils.strEql(arg, "-Wl,-dy") or
                    utils.strEql(arg, "-Wl,-call_shared"))
                {
                    active_mode = .dynamic;
                }
            }
            parser.advance(1);
            for (parser.consumed) |arg| {
                try utils.dupeAndAppend(u8, &args, self.allocator, arg);
            }
        }

        // Add "." to the library paths.
        if (!path_set.contains(".")) {
            const dot = try self.allocator.dupe(u8, ".");
            errdefer self.allocator.free(dot);
            try path_set.put(self.allocator, dot, {});
        }

        // Find the library paths and fix link options.
        var buf = std.array_list.Managed(u8).init(self.allocator);
        defer buf.deinit();
        for (lib_map.values()) |libs| {
            next_lib: for (libs.items) |lib| {
                const modes = [_]LinkMode{ lib.mode, if (lib.mode == .dynamic) .static else .dynamic };
                for (modes) |search_mode| {
                    const lib_exts = self.getlibExtsForMode(search_mode);
                    for (path_set.keys()) |path| {
                        for ([_][]const u8{ "lib", "" }) |prefix| {
                            for (lib_exts) |file_ext| {
                                buf.clearRetainingCapacity();
                                try buf.appendSlice(path);
                                try buf.append('/');
                                try buf.appendSlice(prefix);
                                try buf.appendSlice(lib.name);
                                try buf.appendSlice(file_ext);
                                if (std.Io.Dir.cwd().access(self.io, buf.items, .{})) |_| {
                                    const file_lib = self.libFromFileName(buf.items);
                                    if (lib.kind == .none or lib.kind == file_lib.kind) {
                                        const lib_opt = if (file_lib.kind == .dynamic and !self.target_is_windows)
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
                args.items[arg_num] = arg;
                arg_num += 1;
            }
        }
        args.items.len = arg_num;

        // Clean up self.args and take ownership
        utils.freeStringArray(self.allocator, &self.args);
        self.args = args;
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
                    if (utils.strTake(&self.windres_input)) |v| self.allocator.free(v);
                    self.windres_input = try self.allocator.dupe(u8, parser.value);
                } else if (parser.parseNamed(&.{ "-o", "--output" }, true)) {
                    if (self.windres_output) |v| self.allocator.free(v);
                    self.windres_output = try self.allocator.dupe(u8, parser.value);
                } else if (parser.parseNamed(&.{ "-J", "--input-format" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-O", "--output-format" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-F", "--target" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-I", "--include-dir" }, true)) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "/i");
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, parser.value);
                } else if (parser.parseNamed(&.{"--preprocessor"}, true)) {
                    // skip
                } else if (parser.parseNamed(&.{"--preprocessor-arg"}, true)) {
                    if (utils.strTake(&self.windres_preprocessor_arg)) |pre_arg| {
                        defer self.allocator.free(pre_arg);
                        if (utils.strEql(pre_arg, "-MF")) {
                            if (utils.strTake(&self.windres_depfile)) |v| self.allocator.free(v);
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
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "/d");
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, parser.value);
                } else if (parser.parseNamed(&.{ "-U", "--undefine" }, true)) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "/u");
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, parser.value);
                } else if (parser.parseNamed(&.{ "-v", "--verbose" }, false)) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "/v");
                } else if (parser.parseNamed(&.{ "-c", "--codepage" }, true)) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "/c");
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, parser.value);
                } else if (parser.parseNamed(&.{ "-l", "--language" }, true)) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "/ln");
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, parser.value);
                } else if (parser.parseNamed(&.{"--use-temp-file"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{"--no-use-temp-file"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{"-r"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-h", "--help" }, false)) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "/h");
                } else {
                    _ = parser.next();
                }

                if (!parser.hasArgument()) {
                    try utils.dupeAndAppend(u8, &self.args, self.allocator, "--");
                    if (self.windres_input) |v| try utils.dupeAndAppend(u8, &self.args, self.allocator, v);
                    if (self.windres_output) |v| try utils.dupeAndAppend(u8, &self.args, self.allocator, v);
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
        var buffer = try std.array_list.Managed(u8).initCapacity(
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
            try std.Io.Dir.cwd().writeFile(self.io, .{
                .sub_path = at_file_opt[1..],
                .data = buffer.items,
                .flags = .{ .truncate = true },
            });
        } else {
            var flags_file = try TempFile.init(self.io, self.allocator, self.environ_map);
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
                            const cwd = std.Io.Dir.cwd();
                            try cwd.copyFile(dll_lib, cwd, dll_a, self.io, .{});
                        }
                    }
                }
            },
            .windres => {
                if (self.windres_depfile) |depfile| {
                    const path = if (depfile.len == 0) blk: {
                        const output = self.windres_output orelse return;
                        break :blk try std.fmt.allocPrint(self.allocator, "{s}.d", .{output});
                    } else depfile;
                    defer if (depfile.len == 0) {
                        self.allocator.free(path);
                    };

                    if (success) {
                        // Create a pseudo dependency file.
                        (try std.Io.Dir.cwd().createFile(self.io, path, .{
                            .truncate = true,
                        })).close(self.io);
                    } else {
                        std.Io.Dir.cwd().deleteFile(self.io, path) catch {};
                    }
                }
            },
            else => {},
        }

        // Work around:
        //    https://github.com/ziglang/zig/issues/22847
        //    zig build: Incorrect path prefix added to Linux shared library paths in ELF dynamic section
        if (self.cc_output) |output| {
            if (success and self.is_linker and !self.target_is_windows) {
                var patterns = StringArray.init(self.allocator);
                defer {
                    for (patterns.items) |pat| {
                        self.allocator.free(pat);
                    }
                    patterns.deinit();
                }

                try utils.dupeAndAppend(u8, &patterns, self.allocator, "[:\\\\]");
                try utils.dupeAndAppend(u8, &patterns, self.allocator, "^/mnt/[a-z]/");
                try utils.dupeAndAppend(u8, &patterns, self.allocator, "/.rmake/");
                if (utils.getEnvVar(self.environ_map, "CARGO_WORKSPACE_DIR")) |v| {
                    try utils.dupeAndAppend(u8, &patterns, self.allocator, v);
                }

                for (&[_][]const u8{ "CMKABE_TARGET", "CMKABE_CARGO_TARGET" }) |env| {
                    if (utils.getEnvVar(self.environ_map, env)) |target| {
                        try utils.allocPrintAndAppend(&patterns, self.allocator, "{s}/", .{target});
                    }
                }

                const elf_success = try elf_mod.modifyElfFile(
                    self.allocator,
                    self.io,
                    output,
                    patterns.items,
                    false, // fix_rpath
                    false, // create_backup
                    false, // verbose
                    true, // quiet
                );

                if (!elf_success) {
                    self.log.print("***** elf_path_fixer error\n", .{});
                }
            }
        }
    }
};

pub const LinkMode = enum { dynamic, static };

pub const LinkerLibKind = enum { none, static, dynamic };

pub const LinkerLib = struct {
    kind: LinkerLibKind = .none,
    name: []const u8 = "",
    index: usize = 0,
    mode: LinkMode = .dynamic,
};

pub fn main(proc_init: std.process.Init) u8 {
    return run(proc_init) catch |err| {
        const stderr_file = std.Io.File.stderr();
        var buf: [256]u8 = undefined;
        const msg = std.fmt.bufPrint(&buf, "error: {}\n", .{err}) catch "error: print error\n";
        stderr_file.writeStreamingAll(proc_init.io, msg) catch {};
        return 1;
    };
}

fn run(init: std.process.Init) !u8 {
    var zig = try ZigWrapper.init(init);
    defer zig.deinit();
    return try zig.run();
}
