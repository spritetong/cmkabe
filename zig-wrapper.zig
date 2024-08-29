const std = @import("std");
const builtin = @import("builtin");
const ArgIteratorGeneral = std.process.ArgIteratorGeneral(.{});

pub const ZigCommand = enum {
    const Self = @This();
    ar,
    cc,
    cxx,
    dlltool,
    ld,
    lib,
    objcopy,
    ranlib,
    rc,
    strip,
    windres,

    fn fromStr(str: []const u8) ?Self {
        const map = std.StaticStringMap(ZigCommand).initComptime(.{
            .{ "ar", .ar },
            .{ "cc", .cc },
            .{ "c++", .cxx },
            .{ "dlltool", .dlltool },
            .{ "ld", .ld },
            .{ "lib", .lib },
            .{ "objcopy", .objcopy },
            .{ "ranlib", .ranlib },
            .{ "rc", .rc },
            .{ "strip", .strip },
            .{ "windres", .windres },
            .{ "clang", .cc },
            .{ "clang++", .cxx },
            .{ "gcc", .cc },
            .{ "g++", .cxx },
        });
        return map.get(str);
    }

    fn toName(self: Self) []const u8 {
        return switch (self) {
            .cxx => "c++",
            .ld => "ld.lld",
            .windres => "rc",
            else => @tagName(self),
        };
    }

    fn toFlagsName(self: Self) ?[]const u8 {
        return switch (self) {
            .ar => "ARFLAGS",
            .cc => "CFLAGS",
            .cxx => "CXXFLAGS",
            .ld => "LDFLAGS",
            .ranlib => "RANLIBFLAGS",
            else => null,
        };
    }

    fn isCompiler(self: Self) bool {
        return switch (self) {
            .cc, .cxx => true,
            else => false,
        };
    }
};

pub const ZigArgFilter = union(enum) {
    const Self = @This();
    replace: []const []const u8,
    match_next_and_replace: struct { []const u8, []const []const u8 },

    // Options to compile source files only and not to run the linker.
    pub const compile_only_opts: []const []const u8 = &.{ "-c", "-E", "-S" };

    pub const FilterTable = std.StaticStringMap([]const Self);
    pub const cc_filters = FilterTable.initComptime(.{
        // Linux system include paths
        .{ "-I/usr/include", &.{Self.replace_with(&.{ "-idirafter", "/usr/include" })} },
        .{ "-I/usr/local/include", &.{Self.replace_with(&.{ "-idirafter", "/usr/local/include" })} },
        // MSVC
        .{ "-Xlinker", &.{
            Self.skip_next("/MANIFEST:EMBED"),
            Self.skip_next("/version:0.0"),
        } },
        // --target <target>
        .{ "--target", &.{Self.skip_two} },
        // -m <target>, unknown Clang option: '-m'
        .{ "-m", &.{Self.skip_two} },
        // strip local symbols
        .{ "-Wl,-x", &.{Self.replace_with(&.{"-Wl,--strip-all"})} },
        .{ "-Wl,-v", &.{Self.skip} },
        // x265
        .{ "-march=i586", &.{Self.skip} },
        .{ "-march=i686", &.{Self.skip} },
    });

    pub const windows_gnu_cc_filters = FilterTable.initComptime(.{
        .{ "-Wl,--disable-auto-image-base", &.{Self.skip} },
        .{ "-Wl,--enable-auto-image-base", &.{Self.skip} },
        .{ "-lmingw32", &.{Self.skip} },
        .{ "-lmingw64", &.{Self.skip} },
        .{ "-lmingwex", &.{Self.skip} },
        .{ "-lstdc++", &.{Self.replace_with(&.{"-lc++"})} },
    });
    pub const windows_gnu_skipped_libs = std.StaticStringMap(void).initComptime(.{
        .{"gcc"},
        .{"gcc_eh"},
        .{"msvcrt"},
        .{"msvcrtd"},
        .{"pthread"},
        .{"synchronization"},
    });

    const skip: Self = .{ .replace = &.{} };
    const skip_two: Self = .{ .match_next_and_replace = .{ "", &.{} } };

    fn replace_with(comptime args: []const []const u8) Self {
        return .{ .replace = args };
    }

    fn skip_next(comptime next_arg: []const u8) Self {
        return .{ .match_next_and_replace = .{ next_arg, &.{} } };
    }

    fn replace_next(comptime next_arg: []const u8, comptime replacement: []const []const u8) Self {
        return .{ .match_next_and_replace = .{ next_arg, replacement } };
    }
};

pub const LinkerLibKind = enum { none, static, dynamic };

pub const LinkerLib = struct {
    kind: LinkerLibKind = .none,
    name: []const u8 = "",
    index: usize = 0,
};

pub const Deallcator = union(enum) {
    const Self = @This();
    arg_iter: std.process.ArgIterator,
    arg_iter_gen: ArgIteratorGeneral,
    string: struct { std.mem.Allocator, []u8 },

    pub fn deinit(self: Self) void {
        switch (self) {
            .arg_iter => |v| @constCast(&v).deinit(),
            .arg_iter_gen => |v| @constCast(&v).deinit(),
            .string => |v| v[0].free(v[1]),
        }
    }
};

pub const BufferedAllocator = struct {
    const Self = @This();
    const ArgIteratorInitError = std.process.ArgIterator.InitError;

    items: std.ArrayList(Deallcator),

    pub fn init(allocator_: std.mem.Allocator) Self {
        return .{ .items = std.ArrayList(Deallcator).init(allocator_) };
    }

    pub fn deinit(self: Self) void {
        @constCast(&self).clear();
        self.items.deinit();
    }

    pub inline fn allocator(self: *Self) std.mem.Allocator {
        return self.items.allocator;
    }

    pub fn clear(self: *Self) void {
        while (self.items.popOrNull()) |*de| {
            @constCast(de).deinit();
        }
        self.items.clearRetainingCapacity();
    }

    /// Add a string to the registry and it will be freed on `deinit()` automatically.
    pub fn addString(self: *Self, string: []u8) void {
        self.items.append(.{
            .string = .{ self.allocator(), string },
        }) catch unreachable;
    }

    pub fn allocString(self: *Self, n: usize) std.mem.Allocator.Error![]u8 {
        const value = try self.allocator().alloc(u8, n);
        self.addString(value);
        return value;
    }

    /// Remove a string from the registry and free it.
    pub fn freeString(self: *Self, string: []const u8) void {
        if (self._removeString(string)) |v| {
            v.deinit();
        }
    }

    /// Remove a string from the registry but do not free it.
    ///
    /// Do not forget to free the string manually.
    pub fn forgetString(self: *Self, string: []const u8) void {
        _ = self._removeString(string);
    }

    /// Remove a string from the registry and free it.
    fn _removeString(self: *Self, string: []const u8) ?Deallcator {
        var i = self.items.items.len;
        while (i > 0) : (i -= 1) {
            const de = &self.items.items[i - 1];
            if (de.* == .string and de.string[1].ptr == string.ptr) {
                return self.items.swapRemove(i - 1);
            }
        }
        return null;
    }

    /// Get the value of the environment variable `key`, abandon empty value.
    pub fn getEnvVar(self: *Self, key: []const u8) std.process.GetEnvVarOwnedError![]u8 {
        const val = try std.process.getEnvVarOwned(self.allocator(), key);
        const s = strTrimRight(val);
        if (s.len > 0) {
            self.addString(val);
            return val[0..s.len];
        }
        self.allocator().free(val);
        return std.process.GetEnvVarOwnedError.EnvironmentVariableNotFound;
    }

    pub fn sysArgvIterator(self: *Self) ArgIteratorInitError!std.process.ArgIterator {
        const value = try std.process.argsWithAllocator(self.allocator());
        self.items.append(.{
            .arg_iter = value,
        }) catch unreachable;
        return value;
    }

    pub fn argIteratorTakeOwnership(self: *Self, cmd_line: []const u8) !ArgIteratorGeneral {
        const value = try ArgIteratorGeneral.initTakeOwnership(
            self.allocator(),
            cmd_line,
        );
        self.items.append(.{
            .arg_iter_gen = value,
        }) catch unreachable;
        return value;
    }
};

pub const ZigLog = struct {
    const Self = @This();
    file: ?std.fs.File,

    pub fn init(path_: ?[]const u8) !Self {
        if (path_) |path| {
            if (std.fs.cwd().createFile(path, .{
                .read = true,
                .truncate = false,
            })) |file| {
                errdefer file.close();

                // Lock file.
                try file.lock(.exclusive);

                // Seek to the end.
                try file.seekFromEnd(0);

                return .{ .file = file };
            } else |_| {}
        }
        return .{ .file = null };
    }

    pub fn deinit(self: *Self) void {
        if (self.file) |file| {
            file.sync() catch {};
            file.unlock();
            file.close();
            self.file = null;
        }
    }

    pub fn enabled(self: *Self) bool {
        return self.file != null;
    }

    pub fn write(self: *Self, bytes: []const u8) void {
        if (self.file) |file| {
            _ = file.writeAll(bytes) catch {};
        }
    }

    pub fn print(self: *Self, comptime fmt: []const u8, args: anytype) void {
        if (self.file) |file| {
            file.writer().print(fmt, args) catch {};
        }
    }
};

pub const TempFile = struct {
    const Self = @This();
    file: ?std.fs.File,
    _path: std.ArrayList(u8),

    pub fn init(a: std.mem.Allocator) !Self {
        const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

        const tmp_dir = try Self.getSysTmpDir(a);
        defer a.free(tmp_dir);

        var path = try std.ArrayList(u8).initCapacity(a, tmp_dir.len + 32);
        errdefer path.deinit();
        path.appendSlice(tmp_dir) catch unreachable;
        path.append(std.fs.path.sep) catch unreachable;
        path.appendSlice("zig-wrapper") catch unreachable;

        // Create the `zig-wrapper` directory in the `tmp` dir.
        try std.fs.cwd().makePath(path.items);
        path.append(std.fs.path.sep) catch unreachable;
        const dir_len = path.items.len;

        while (true) {
            path.resize(dir_len) catch unreachable;
            for (0..10) |_| {
                const index = std.crypto.random.uintLessThan(usize, chars.len);
                path.append(chars[index]) catch unreachable;
            }
            path.appendSlice(".tmp") catch unreachable;

            // Check file existence.
            const file = std.fs.cwd().createFile(
                path.items,
                .{ .exclusive = true },
            ) catch |err| switch (err) {
                error.PathAlreadyExists => continue,
                else => |e| return e,
            };
            return .{ .file = file, ._path = path };
        }
    }

    pub fn deinit(self: *Self) void {
        self.close();
        std.fs.cwd().deleteFile(self.getPath()) catch {};
        self._path.deinit();
    }

    pub fn close(self: *Self) void {
        if (self.file) |file| {
            file.close();
            self.file = null;
        }
    }

    pub inline fn getPath(self: *Self) []const u8 {
        return self._path.items;
    }

    pub fn write(self: *Self, bytes: []const u8) !void {
        if (self.file) |file| {
            _ = try file.writeAll(bytes);
        }
    }

    fn getSysTmpDir(a: std.mem.Allocator) ![]const u8 {
        return std.process.getEnvVarOwned(a, "TMPDIR") catch {
            return std.process.getEnvVarOwned(a, "TMP") catch {
                return std.process.getEnvVarOwned(a, "TEMP") catch {
                    return std.process.getEnvVarOwned(a, "TEMPDIR") catch {
                        return a.dupe(u8, if (builtin.os.tag == .windows) "." else "/tmp");
                    };
                };
            };
        };
    }
};

const SimpleArgParser = struct {
    const Self = @This();
    args: []const []const u8,
    always_positional: bool = false,
    value: []const u8 = "",

    pub inline fn hasArgument(self: Self) bool {
        return self.args.len > 0;
    }

    /// Get the first argument and retain it.
    pub fn first(self: Self) ?[]const u8 {
        if (self.hasArgument()) {
            return self.args[0];
        }
        return null;
    }

    /// Pick the next argument.
    pub fn next(self: *Self) ?[]const u8 {
        if (self.hasArgument()) {
            const arg = self.args[0];
            self.args = self.args[1..];
            return arg;
        }
        return null;
    }

    /// Do not consume any argument if failed.
    pub fn parsePositional(self: *Self) ?[]const u8 {
        while (self.hasArgument()) {
            const arg = self.args[0];

            if (self.always_positional or !strStartsWith(arg, "-")) {
                self.args = self.args[1..];
                return arg;
            }
            if (strEql(arg, "--")) {
                self.always_positional = true;
                self.args = self.args[1..];
                continue;
            }
            break;
        }
        return null;
    }

    /// Do not consume any argument if failed.
    pub fn parseNamed(self: *Self, options: []const []const u8, require_value: bool) bool {
        const arg = self.first() orelse return false;

        for (options) |opt| {
            if (strEql(arg, opt)) {
                if (!require_value) {
                    self.args = self.args[1..];
                    return true;
                } else if (self.args.len > 1) {
                    self.value = self.args[1];
                    self.args = self.args[2..];
                    return true;
                } else {
                    return false;
                }
            }

            if (!require_value) continue;

            if (strStartsWith(arg, opt)) {
                if (opt.len == 2 and opt[0] == '-') {
                    self.args = self.args[1..];
                    self.value = arg[opt.len..];
                    return true;
                } else if (arg[opt.len] == '=') {
                    self.args = self.args[1..];
                    self.value = arg[opt.len + 1 ..];
                    return true;
                }
            }
        }
        return false;
    }
};

pub const ZigWrapper = struct {
    const Self = @This();
    alloc: BufferedAllocator,
    log: ZigLog,
    sys_argv: std.ArrayList([]const u8),
    zig_exe: []const u8 = "",

    /// The current Zig command.
    command: ZigCommand = ZigCommand.cc,

    /// If the Zig command is running as a linker.
    is_linker: bool = false,
    /// <arch>-<os>-<abi>
    zig_target: []const u8 = "",
    /// <arch>-<vendor>-<os>-<abi>
    clang_target: []const u8 = "",
    /// -l<lib> options not to be passed to the linker.
    skipped_libs: std.ArrayList([]const u8),
    /// -L<lib path> options not to be passed to the linker.
    skipped_lib_paths: std.ArrayList([]const u8),

    target_is_windows: bool = false,
    target_is_android: bool = false,
    target_is_linux: bool = false,
    target_is_apple: bool = false,
    target_is_wasm: bool = false,
    target_is_msvc: bool = false,
    target_is_musl: bool = false,
    at_file_opt: ?[]const u8 = null,

    /// The arguments to run the Zig command, include the Zig executable and its arguments.
    args: std.ArrayList([]const u8),
    /// Used for `windres` ...
    named_args: std.StringHashMap([]const u8),
    flags_file: ?TempFile = null,

    const _REMOVED: []const u8 = "-???";

    pub fn init(allocator_: std.mem.Allocator) !Self {
        var self = outer: {
            // allocator
            var alloc = BufferedAllocator.init(allocator_);
            // logger
            const log = blk: {
                const log_path = alloc.getEnvVar("ZIG_WRAPPER_LOG") catch null;
                errdefer if (log_path) |v| {
                    alloc.freeString(v);
                    alloc.deinit();
                };
                const v = try ZigLog.init(log_path);
                break :blk v;
            };

            break :outer Self{
                .alloc = alloc,
                .log = log,
                .sys_argv = std.ArrayList([]const u8).init(alloc.allocator()),
                .skipped_libs = std.ArrayList([]const u8).init(alloc.allocator()),
                .skipped_lib_paths = std.ArrayList([]const u8).init(alloc.allocator()),
                .args = std.ArrayList([]const u8).init(alloc.allocator()),
                .named_args = std.StringHashMap([]const u8).init(alloc.allocator()),
            };
        };
        errdefer self.deinit();

        // Collect `argv[0..]`...
        var arg_iter = try self.alloc.sysArgvIterator();
        while (arg_iter.next()) |arg| {
            if (self.sys_argv.items.len > 0) {
                if (strStartsWith(arg, "@")) {
                    // Parse the flags file.
                    const flags = try self.parseFileFlags(arg[1..]);
                    defer flags.deinit();
                    self.at_file_opt = arg;
                    try self.sys_argv.appendSlice(flags.items);
                    continue;
                }

                // If the flags file is not the last argument, ignore it.
                if (self.at_file_opt != null) {
                    self.at_file_opt = null;
                }
            }
            try self.sys_argv.append(arg);
        }

        // Parse the command type from `argv[0]`.
        const stem = std.fs.path.stem(self.sys_argv.items[0]);
        self.command = ZigCommand.fromStr(
            stem[if (std.mem.lastIndexOfScalar(u8, stem, '-')) |s| s + 1 else 0..],
        ) orelse return error.InvalidZigCommand;
        if (self.command.isCompiler() or self.command == .ld) {
            self.is_linker = true;
        }

        // Parse environment variables.
        self.zig_exe = self.alloc.getEnvVar("ZIG_EXECUTABLE") catch "";
        self.zig_target = self.alloc.getEnvVar("ZIG_WRAPPER_TARGET") catch "";
        self.clang_target = self.alloc.getEnvVar("ZIG_WRAPPER_CLANG_TARGET") catch "";

        // Parse Zig flags in `argv[1..]`.
        try self.parseArgv(self.sys_argv.items[1..]);

        // Parse Zig flags in the environment variables.
        var env_flags = try self.parseEnvFlags();
        defer env_flags.deinit();
        try self.sys_argv.appendSlice(env_flags.items);

        // Set default values.
        if (self.zig_exe.len == 0) {
            const str = try std.fmt.allocPrint(
                self.alloc.allocator(),
                "zig{s}",
                .{builtin.os.tag.exeFileExt(builtin.cpu.arch)},
            );
            self.alloc.addString(str);
            self.zig_exe = str;
        }
        if (self.clang_target.len == 0) {
            self.clang_target = self.zig_target;
        }

        self.target_is_windows = std.mem.indexOf(u8, self.clang_target, "-windows") != null;
        self.target_is_android = std.mem.indexOf(u8, self.clang_target, "-android") != null;
        self.target_is_linux = std.mem.indexOf(u8, self.clang_target, "-linux") != null;
        self.target_is_apple = std.mem.indexOf(u8, self.clang_target, "-apple") != null or
            std.mem.indexOf(u8, self.clang_target, "-macos") != null or
            std.mem.indexOf(u8, self.clang_target, "-darwin") != null;
        self.target_is_wasm = strStartsWith(self.clang_target, "wasm") or
            strEndsWith(self.clang_target, "-emscripten");
        self.target_is_msvc = strEndsWith(self.clang_target, "-msvc");
        self.target_is_musl = strEndsWith(self.clang_target, "-musl");

        return self;
    }

    pub inline fn allocator(self: *Self) std.mem.Allocator {
        return self.alloc.allocator();
    }

    pub fn run(self: *Self) !u8 {
        // Zig executable
        try self.args.append(self.zig_exe);
        // Zig command
        try self.args.append(self.command.toName());
        // `cc`, `c++`: -target <target>
        try self.targetInit(self.zig_target);

        // Write the input command line to log.
        if (self.log.enabled()) {
            for (self.sys_argv.items) |arg| {
                self.log.print("{s} ", .{arg});
            }
            self.log.write("\n");
        }
        // Parse arguments in `argv[1..]`.
        var argv_parer = SimpleArgParser{ .args = self.sys_argv.items[1..] };
        while (argv_parer.hasArgument()) {
            try self.appendArgument(&argv_parer);
        }

        // Fix link libraries.
        if (self.is_linker) {
            try self.fixLinkLibs();
        }

        // Remove all skipped args.
        var arg_num: usize = 0;
        for (self.args.items, 0..) |arg, i| {
            if (arg.ptr != _REMOVED.ptr) {
                if (arg_num != i) {
                    self.args.items[arg_num] = arg;
                }
                arg_num += 1;
            }
        }
        self.args.resize(arg_num) catch unreachable;

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
        var proc = std.process.Child.init(self.args.items, self.allocator());
        const term = try proc.spawnAndWait();
        if (term.Exited != 0) {
            self.log.print("***** error code: {d}\n", .{term.Exited});
        }
        return term.Exited;
    }

    pub fn deinit(self: *Self) void {
        if (self.flags_file) |*flags_file| {
            flags_file.deinit();
            self.flags_file = null;
        }
        self.named_args.deinit();
        self.args.deinit();
        self.skipped_lib_paths.deinit();
        self.skipped_libs.deinit();
        self.log.deinit();
        self.sys_argv.deinit();
        self.alloc.deinit();
    }

    pub fn parseFileFlags(self: *Self, path: []const u8) !std.ArrayList([]const u8) {
        // Open the file for reading
        var file = try std.fs.cwd().openFile(path, .{});
        defer file.close();

        // Get the file size
        const file_size = try file.getEndPos();

        // Allocate a buffer to hold the file content
        const flags_str = try self.alloc.allocString(file_size);
        errdefer self.alloc.freeString(flags_str);

        // Read the file content into the buffer
        _ = try file.readAll(flags_str);

        var args = std.ArrayList([]const u8).init(self.alloc.allocator());
        errdefer args.deinit();

        // Parse the flags
        var arg_iter = try self.alloc.argIteratorTakeOwnership(flags_str);
        self.alloc.forgetString(flags_str);
        while (arg_iter.next()) |arg| {
            try args.append(arg);
        }
        return args;
    }

    fn parseEnvFlags(self: *Self) !std.ArrayList([]const u8) {
        var res = std.ArrayList([]const u8).init(self.allocator());
        errdefer res.deinit();

        const buf = try self.allocator().alloc(u8, 32 +
            @max(self.zig_target.len, self.clang_target.len));
        defer self.allocator().free(buf);

        var args = std.ArrayList([]const u8).init(self.allocator());
        defer args.deinit();

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
                        strEql(self.clang_target, self.zig_target)) continue;
                    target = self.clang_target;
                },
                else => unreachable,
            }

            for ([_][]const u8{
                self.command.toFlagsName() orelse "",
                if (self.command == .cxx) ZigCommand.cc.toFlagsName().? else "",
            }) |flags_name| {
                if (flags_name.len == 0) continue;

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
                    const flags_str = self.alloc.getEnvVar(key) catch continue;
                    var arg_iter = try self.alloc.argIteratorTakeOwnership(flags_str);
                    self.alloc.forgetString(flags_str);

                    while (arg_iter.next()) |arg| {
                        try args.append(arg);
                    }

                    // Do not append the same flags.
                    if (!stringsContains(res.items, args.items) and
                        !stringsContains(self.sys_argv.items, args.items))
                    {
                        try res.appendSlice(args.items);
                        try self.parseArgv(args.items);
                    }
                    args.clearRetainingCapacity();
                }
            }
        }

        return res;
    }

    fn parseArgv(self: *Self, argv: [][]const u8) !void {
        var parser = SimpleArgParser{ .args = argv };
        while (parser.hasArgument()) {
            const begin = argv.len - parser.args.len;

            if (parser.parsePositional()) |_| {
                // Skip positional arguments.
                continue;
            } else if (parser.parseNamed(ZigArgFilter.compile_only_opts, false)) {
                if (self.is_linker and self.command != .ld) {
                    self.is_linker = false;
                }
                // Do no consume the argument.
                continue;
            } else if (parser.parseNamed(&.{ "-target", "--zig-target" }, true)) {
                if (self.zig_target.len == 0) {
                    self.zig_target = parser.value;
                }
            } else if (parser.parseNamed(&.{"--zig"}, true)) {
                if (self.zig_exe.len == 0) {
                    self.zig_exe = parser.value;
                }
            } else if (parser.parseNamed(&.{"--clang-target"}, true)) {
                if (self.clang_target.len == 0) {
                    self.clang_target = parser.value;
                }
            } else if (parser.parseNamed(&.{"--skip-lib"}, true)) {
                var parts = std.mem.splitAny(u8, parser.value, ",;");
                while (parts.next()) |part| {
                    const v = strTrimRight(part);
                    if (v.len > 0) try self.skipped_libs.append(v);
                }
            } else if (parser.parseNamed(&.{"--skip-lib-path"}, true)) {
                var parts = std.mem.splitAny(u8, parser.value, ";");
                while (parts.next()) |part| {
                    const v = strTrimRight(part);
                    if (v.len > 0) try self.skipped_lib_paths.append(v);
                }
            } else {
                // Do no consume the argument.
                _ = parser.next();
                continue;
            }

            for (begin..argv.len - parser.args.len) |i| {
                argv[i] = _REMOVED;
            }
        }
    }

    fn targetInit(self: *Self, target: []const u8) !void {
        if (self.command.isCompiler()) {
            if (target.len > 0) {
                try self.args.appendSlice(&[_][]const u8{ "-target", target });
            }

            // https://github.com/ziglang/zig/wiki/FAQ#why-do-i-get-illegal-instruction-when-using-with-zig-cc-to-build-c-code
            try self.args.append("-fno-sanitize=undefined");
            try self.args.append("-Wno-unused-command-line-argument");

            if (self.is_linker) {
                try self.args.append("-lc++");
                try self.args.append("-lc++abi");
            }

            // For libmount
            // try self.args.appendSlice(&[_][]const u8{
            //     "-DHAVE_CLOSE_RANGE=1",
            //     "-DHAVE_STATX=1",
            //     "-DHAVE_OPEN_TREE=1",
            //     "-DHAVE_MOVE_MOUNT=1",
            //     "-DHAVE_MOUNT_SETATTR=1",
            //     "-DHAVE_FSCONFIG=1",
            //     "-DHAVE_FSOPEN=1",
            //     "-DHAVE_FSMOUNT=1",
            //     "-DHAVE_FSPICK=1",
            // });
        }
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
        if (strStartsWith(name, ":")) {
            name = name[1..];
            kind = .static;
        }
        if (strStartsWith(name, "lib")) {
            name = name[3..];
        }

        for ([_]LinkerLibKind{ .dynamic, .static }) |k| {
            const exts = self.getlibExts(k);
            for (exts) |ext| {
                if (strEndsWith(name, ext)) {
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
        var libs = std.ArrayList(LinkerLib).init(self.allocator());
        defer libs.deinit();

        var paths = std.ArrayList([]const u8).init(self.allocator());
        defer {
            for (paths.items) |path| {
                self.allocator().free(path);
            }
            paths.deinit();
        }

        var i: usize = 0;
        outer: while (i < self.args.items.len) : (i += 1) {
            // Collect link libraries.
            const arg = self.args.items[i];
            if (strStartsWith(arg, "-l")) {
                var lib = self.libFromFileName(arg[2..]);
                lib.index = i;

                for (self.skipped_libs.items) |pattern| {
                    if (strMatch(pattern, lib.name)) {
                        // Remove the skipped link library from `args`.
                        self.args.items[i] = _REMOVED;
                        continue :outer;
                    }
                }

                var lib_ver = libVersionSplit(lib.name);
                for (libs.items) |*entry| {
                    if (strStartsWith(entry.name, lib_ver[0])) {
                        const entry_ver = libVersionSplit(entry.name);
                        if (strEql(entry_ver[0], lib_ver[0])) {
                            if (strEql(entry.name, lib.name)) {
                                // Remove the duplicate link library from `args`.
                                if (entry.kind == .none and lib.kind != .none) {
                                    self.args.items[entry.index] = _REMOVED;
                                    entry.* = lib;
                                } else {
                                    self.args.items[i] = _REMOVED;
                                }
                                continue :outer;
                            } else if (versionCompare(entry_ver[1], lib_ver[1]) < 0) {
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
                    }
                }
                try libs.append(lib);
                continue;
            }

            // Collect link paths.
            if (strStartsWith(arg, "-L")) {
                var single_opt = true;
                const lib_path = if (arg.len == 2 and i + 1 < self.args.items.len) blk: {
                    single_opt = false;
                    i += 1;
                    break :blk self.args.items[i];
                } else arg[2..];

                // normalize path
                if (std.fs.path.relative(self.allocator(), ".", lib_path)) |v| {
                    var path = v;
                    defer if (path.len > 0) self.allocator().free(path);
                    _ = std.mem.replace(u8, path, "\\", "/", path);

                    var skipped = false;
                    for (self.skipped_lib_paths.items) |pattern| {
                        if (strMatch(pattern, path)) {
                            skipped = true;
                            break;
                        }
                    }

                    if (!skipped and !stringsContains(paths.items, &.{path})) {
                        try paths.append(path);
                        path.len = 0;
                        continue;
                    }
                } else |_| {}

                // Remove the skipped link path from `args`.
                self.args.items[i] = _REMOVED;
                if (!single_opt) self.args.items[i - 1] = _REMOVED;
                continue;
            }
        }

        // for (paths.items) |path| {
        //     std.io.getStdErr().writer().print("link-path: {s}\n", .{path}) catch {};
        // }
        // for (libs.items) |lib| {
        //     std.io.getStdErr().writer().print("link-lib: {s} -> {s}\n", .{ lib.name, self.args.items[lib.index] }) catch {};
        // }

        // Find the library paths and fix link options.
        {
            var buf = std.ArrayList(u8).init(self.allocator());
            defer buf.deinit();
            const lib_exts = self.getlibExts(.none);
            outer: for (libs.items) |*lib| {
                for (paths.items) |path| {
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
                                        try std.fmt.allocPrint(
                                            self.allocator(),
                                            "-l{s}",
                                            .{file_lib.name},
                                        )
                                    else
                                        try self.allocator().dupe(u8, buf.items);
                                    self.alloc.addString(lib_opt);
                                    self.args.items[lib.index] = lib_opt;

                                    // The library is already fixed, so we mark it as removed.
                                    lib.name.len = 0;
                                    continue :outer;
                                }
                            } else |_| {}
                        }
                    }
                }
            }
        }

        for (libs.items) |lib| {
            // Skip libaries marked as removed.
            if (lib.name.len == 0) continue;

            if (self.target_is_windows and !self.target_is_msvc and
                ZigArgFilter.windows_gnu_skipped_libs.getIndex(lib.name) != null)
            {
                self.args.items[lib.index] = _REMOVED;
                continue;
            }

            const opt = try std.fmt.allocPrint(
                self.allocator(),
                "-l{s}",
                .{lib.name},
            );
            self.alloc.addString(opt);
            self.args.items[lib.index] = opt;
        }
    }

    fn appendArgument(self: *Self, parser: *SimpleArgParser) !void {
        switch (self.command) {
            .cc, .cxx => {
                var arg = @constCast(parser.next().?);
                var opt = arg;
                var filters = &ZigArgFilter.cc_filters;

                for (0..3) |loop_for_opt| {
                    for (0..2) |split_kv| {
                        // Get this option
                        const this_opt = if (split_kv == 0) opt else blk: {
                            var opt_kv = std.mem.splitAny(
                                u8,
                                opt,
                                if (self.target_is_msvc and
                                    opt.len > 0 and opt[0] == '/') ":" else "=",
                            );
                            const s = opt_kv.next().?;
                            // Do not continue if the delimiter is not found.
                            if (s.len == opt.len) continue;
                            break :blk s;
                        };

                        if (filters.get(this_opt)) |arg_ops| {
                            for (arg_ops) |arg_op| switch (arg_op) {
                                .replace => |replacement| {
                                    try self.args.appendSlice(replacement);
                                    return;
                                },
                                .match_next_and_replace => |item| {
                                    // Get the next option.
                                    const next_opt = if (split_kv == 0)
                                        (parser.first() orelse "")
                                    else
                                        opt[this_opt.len + 1 ..];
                                    // Match successfully if the pattern is empty.
                                    if (item[0].len == 0 or strEql(item[0], next_opt)) {
                                        try self.args.appendSlice(item[1]);
                                        if (split_kv == 0) {
                                            _ = parser.next();
                                        }
                                        return;
                                    }
                                },
                            };
                        }
                    }

                    // Continue for `<arch>-windows-gnu`, break for other targets.
                    if (self.target_is_windows and !self.target_is_msvc) {
                        filters = &ZigArgFilter.windows_gnu_cc_filters;
                        if (loop_for_opt == 1) {
                            const new_opt = Self.windowsGnuArgFilter(opt);
                            if (std.mem.eql(u8, opt, new_opt)) break;
                            opt = new_opt;
                            arg = new_opt;
                        }
                    } else {
                        break;
                    }
                }

                try self.args.append(arg);
            },
            .windres => {
                if (parser.parsePositional()) |arg| {
                    if (!self.named_args.contains("input")) {
                        try self.named_args.put("input", arg);
                    } else if (!self.named_args.contains("output")) {
                        try self.named_args.put("output", arg);
                    }
                } else if (parser.parseNamed(&.{ "-i", "--input" }, true)) {
                    try self.named_args.put("input", parser.value);
                } else if (parser.parseNamed(&.{ "-o", "--output" }, true)) {
                    try self.named_args.put("output", parser.value);
                } else if (parser.parseNamed(&.{ "-J", "--input-format" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-O", "--output-format" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-F", "--target" }, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-I", "--include-dir" }, true)) {
                    try self.args.append("/i");
                    try self.args.append(parser.value);
                } else if (parser.parseNamed(&.{"--preprocessor"}, true)) {
                    // skip
                } else if (parser.parseNamed(&.{"--preprocessor-arg"}, true)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-D", "--define" }, true)) {
                    try self.args.append("/d");
                    try self.args.append(parser.value);
                } else if (parser.parseNamed(&.{ "-U", "--undefine" }, true)) {
                    try self.args.append("/u");
                    try self.args.append(parser.value);
                } else if (parser.parseNamed(&.{ "-v", "--verbose" }, false)) {
                    try self.args.append("/v");
                } else if (parser.parseNamed(&.{ "-c", "--codepage" }, true)) {
                    try self.args.append("/c");
                    try self.args.append(parser.value);
                } else if (parser.parseNamed(&.{ "-l", "--language" }, true)) {
                    try self.args.append("/ln");
                    try self.args.append(parser.value);
                } else if (parser.parseNamed(&.{"--use-temp-file"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{"--no-use-temp-file"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{"-r"}, false)) {
                    // skip
                } else if (parser.parseNamed(&.{ "-h", "--help" }, false)) {
                    try self.args.append("/h");
                } else {
                    _ = parser.next();
                }

                if (!parser.hasArgument()) {
                    try self.args.append("--");
                    for ([_][]const u8{ "input", "output" }) |name| {
                        if (self.named_args.get(name)) |v| {
                            try self.args.append(v);
                        }
                    }
                }
            },
            else => try self.args.append(parser.next().?),
        }
    }

    fn windowsGnuArgFilter(arg: []u8) []u8 {
        // `-Wl,/DEF:<lib>.def`
        if (strStartsWith(arg, "-Wl,") and
            strEndsWith(arg, ".def"))
        {
            var opt = arg[4..];
            if (strStartsWith(opt, "/DEF:")) {
                opt = opt[5..];
            }
            std.mem.copyForwards(u8, arg, opt);
            return arg[0..opt.len];
        }

        // `-l<lib>`
        if (strStartsWith(arg, "-l")) {
            var lib = arg[2..];

            // Trim prefix `winapi_`.
            if (strStartsWith(lib, "winapi_")) {
                lib = lib[7..];
            }

            return std.fmt.bufPrint(arg, "-l{s}", .{lib}) catch unreachable;
        }
        return arg;
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
        if (argv_size <= sysArgMax()) return;

        // Write flags to buffer.
        var buffer = try std.ArrayList(u8).initCapacity(
            self.allocator(),
            argv_size,
        );
        defer buffer.deinit();
        for (self.args.items[2..], 0..) |arg, i| {
            if (i > 0) try buffer.append(' ');
            try strEscapeAppend(&buffer, arg);
        }

        var at_file_opt: []u8 = undefined;
        if (self.at_file_opt) |v| {
            at_file_opt = @constCast(v);
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
            var flags_file = try TempFile.init(self.allocator());
            errdefer flags_file.deinit();
            try flags_file.write(buffer.items);
            flags_file.close();

            at_file_opt = try std.fmt.allocPrint(self.allocator(), "@{s}", .{flags_file.getPath()});
            self.alloc.addString(at_file_opt);
            self.flags_file = flags_file;
        }

        // Only keep the executable path and the command type.
        self.args.items.len = 2;
        // Set the @<file_path> flag.
        try self.args.append(at_file_opt);
    }
};

/// Check if `a` and `b` are equal.
pub inline fn strEql(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

/// Remove trailing whitespace from `s`.
pub inline fn strTrimRight(s: []const u8) []const u8 {
    return std.mem.trimRight(u8, s, " \t\r\n");
}

/// Check if `haystack` starts with `needle`.
pub fn strStartsWith(haystack: []const u8, needle: []const u8) bool {
    if (needle.len > haystack.len) {
        return false;
    }
    return strEql(haystack[0..needle.len], needle);
}

/// Check if `haystack` ends with `needle`.
pub fn strEndsWith(haystack: []const u8, needle: []const u8) bool {
    if (needle.len > haystack.len) {
        return false;
    }
    return strEql(haystack[haystack.len - needle.len ..], needle);
}

/// Check if `slice` contains `sub_slice`.
pub fn stringsContains(slice: []const []const u8, sub_slice: []const []const u8) bool {
    if (sub_slice.len == 0) return true;
    if (sub_slice.len > slice.len) return false;

    outer: for (0..slice.len - sub_slice.len + 1) |i| {
        for (sub_slice, 0..) |s, j| {
            if (!strEql(slice[i + j], s)) {
                continue :outer;
            }
        }
        return true;
    }
    return false;
}

pub fn strUnescape(string: []u8, require_quotes: bool) []u8 {
    var buffer = string;

    if (require_quotes) {
        if (buffer.len < 2 or !strStartsWith(buffer, "\"") or
            !strEndsWith(buffer, "\""))
        {
            return string;
        }
        buffer = buffer[1 .. buffer.len - 1];
    }

    var len: usize = 0;
    var i: usize = 0;
    while (i < buffer.len) : (i += 1) {
        if (buffer[i] == '\\' and i + 1 < buffer.len) {
            const next = buffer[i + 1];
            if (next == '\\' or next == '"' or next == '\'') {
                buffer[len] = next;
                i += 1; // Skip the next character
            } else {
                buffer[len] = buffer[i];
            }
        } else {
            buffer[len] = buffer[i];
        }
        len += 1;
    }

    return buffer[0..len];
}

pub fn strEscapeAppend(buffer: *std.ArrayList(u8), string: []const u8) !void {
    var quoted = false;
    var left = string;

    while (left.len > 0) {
        const i = std.mem.indexOfAny(u8, left, "\\\"' \t\r\n") orelse break;

        // Initial buffer and append the left quote.
        if (!quoted) {
            quoted = true;
            try buffer.append('"');
        }

        try buffer.appendSlice(left[0..i]);
        if (!std.ascii.isWhitespace(left[i])) try buffer.append('\\');
        try buffer.append(left[i]);
        left = left[i + 1 ..];
    }

    try buffer.appendSlice(left);
    if (quoted) {
        // Append the right quote.
        try buffer.append('"');
    }
}

fn strMatch(pattern: []const u8, string: []const u8) bool {
    const INVALID = std.math.maxInt(usize);
    var pat: usize = 0;
    var src: usize = 0;
    var pat_res: usize = INVALID;
    var src_res: usize = INVALID;
    var result = false;

    while (true) {
        // without previous "*"
        while (true) {
            if (pat == pattern.len) {
                result = src == string.len;
                if (result or src_res == INVALID or pat_res == INVALID) {
                    return result;
                }
                src = src_res;
                pat = pat_res;
                break;
            }
            const ch_pat = pattern.ptr[pat];
            if (ch_pat == '*') {
                pat += 1;
                pat_res = pat;
                break;
            } else if (ch_pat == '?') {
                if (src == string.len) {
                    return result;
                }
                src += 1;
                pat += 1;
            } else {
                if (src == string.len) {
                    return result;
                }
                if (ch_pat != string.ptr[src]) {
                    if (src_res == INVALID or pat_res == INVALID) {
                        return result;
                    }
                    src = src_res;
                    pat = pat_res;
                    break;
                }
                src += 1;
                pat += 1;
            }
        }

        // with previous "*"
        while (true) {
            if (pat == pattern.len) {
                return true;
            }
            const ch_pat = pattern.ptr[pat];
            if (ch_pat == '*') {
                pat += 1;
                pat_res = pat;
            } else if (ch_pat == '?') {
                if (src == string.len) {
                    return result;
                }
                src += 1;
                pat += 1;
            } else {
                while (true) {
                    if (src == string.len) {
                        return result;
                    }
                    if (ch_pat == string.ptr[src]) {
                        break;
                    }
                    src += 1;
                }

                src += 1;
                src_res = src;
                pat += 1;
                break;
            }
        }
    }
}

pub fn versionParse(version: []const u8) [4]u32 {
    var ver = [4]u32{ 0, 0, 0, 0 };
    var parts = std.mem.splitAny(u8, version, ".");
    var i: usize = 0;
    while (parts.next()) |part| {
        if (i >= 4) break;
        ver[i] = std.fmt.parseInt(u32, part, 10) catch 0;
        i += 1;
    }
    return ver;
}

pub fn versionCompare(a: []const u8, b: []const u8) i32 {
    const v1 = versionParse(a);
    const v2 = versionParse(b);
    for (0..4) |i| {
        if (v1[i] > v2[i]) return 1;
        if (v1[i] < v2[i]) return -1;
    }
    return 0;
}

pub fn libVersionSplit(lib: []const u8) [2][]const u8 {
    var s = lib;
    while (std.mem.indexOf(u8, s, ".")) |i| {
        if (i + 1 < s.len and std.ascii.isDigit(s[i + 1])) {
            return .{ lib[0 .. lib.len - (s.len - i - 1) - 1], s[i + 1 ..] };
        }
        s = s[i + 1 ..];
    }
    return .{ lib, "" };
}

fn sysArgMax() usize {
    if (builtin.os.tag == .windows) {
        return 32767;
    } else {
        const unistd = @cImport({
            @cInclude("unistd.h");
        });
        return @intCast(unistd.sysconf(@intCast(unistd._SC_ARG_MAX)));
    }
}

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
