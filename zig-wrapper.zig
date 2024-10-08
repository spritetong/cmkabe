const std = @import("std");
const builtin = @import("builtin");
const ArgIteratorGeneral = std.process.ArgIteratorGeneral(.{});
const StringArray = std.ArrayList([]const u8);
const StringSet = std.StringArrayHashMap(void);

pub const ZigCommand = enum {
    const Self = @This();
    ar,
    cc,
    cxx,
    dlltool,
    ld,
    lib,
    link,
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
            .{ "link", .link },
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
            .link => "lld-link",
            .windres => "rc",
            else => @tagName(self),
        };
    }

    fn envNameOfFlags(self: Self) ?[]const u8 {
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

pub const ZigArgFilter = struct {
    const Self = @This();
    matchers: std.ArrayList(Matcher),
    replacers: std.ArrayList(Replacer),

    pub const Matcher = union(enum) {
        allow_partial_opt: void,
        command: []const u8,
        linker: bool,
        target: []const u8,
        match: []const u8,
        next: void,
    };

    pub const Replacer = union(enum) {
        opt_value: void,
        arg_index: usize,
        string: []const u8,
    };

    /// Options to query the compiler version only.
    pub const query_version_opts: []const []const u8 = &.{ "--help", "--version", "-version", "-qversion", "-V" };

    /// Options to compile source files only and not to run the linker.
    pub const compile_only_opts: []const []const u8 = &.{ "-c", "-E", "-S" };

    /// Define libraries that should be skipped only if they are not in library paths.
    pub const generic_weak_libs = std.StaticStringMap(void).initComptime(.{
        .{"omp"},
    });
    pub const windows_gnu_weak_libs = std.StaticStringMap(void).initComptime(.{
        .{"gcc"},
        .{"gcc_eh"},
        .{"msvcrt"},
        .{"msvcrtd"},
        .{"pthread"},
        .{"synchronization"},
    });

    pub fn initFilterMap(ctx: *ZigWrapper, map: *ZigArgFilterMap) void {
        if (ctx.command == .cc or ctx.command == .cxx) {
            // Linux system include paths
            map.initFilters("-I", 2).allowPartialOpt()
                .match("/usr/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().eof()
                .match("/usr/local/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().done();
            // MSVC
            map.initFilters("-Xlinker", 2)
                .match("/MANIFEST:EMBED").eof()
                .match("/version:0.0").done();
            // -m <target>, unknown Clang option: '-m'
            map.initFilter("-m").match("*").done();
            // -verbose
            map.initFilter("-verbose").replaceWith(&.{"-v"}).done();
            // -Wl,[...]
            map.initFilters("-Wl,", 2)
                .match("-v").eof()
                .match("-x").replaceWith(&.{"-Wl,--strip-all"}).done();
            // OpenMP
            map.initFilter("-v").linker(true).done();
            map.initFilter("-fopenmp=libomp").linker(true).replaceWithArg(0).replaceWith(&.{"-lomp"}).done();
            // Autoconfig
            map.initFilter("-link").done();
            map.initFilter("-dll").replaceWith(&.{"-shared"}).done();
            // Invalid CPU types
            map.initFilters("-march", 3)
                .target("x86_64*").match("i386").eof()
                .target("x86_64*").match("i586").eof()
                .target("x86_64*").match("i686").done();

            // Windows GNU
            if (ctx.target_is_windows and !ctx.target_is_msvc) {
                // -Wl,[...]
                map.initFilters("-Wl,", 3)
                    .match("--disable-auto-image-base").eof()
                    .match("--enable-auto-image-base").eof()
                    .match("--add-stdcall-alias").done();
                map.initFilters("-l", 4).allowPartialOpt()
                    .match("mingw32").eof()
                    .match("mingw64").eof()
                    .match("mingwex").eof()
                    .match("stdc++").replaceWith(&.{ "-lc++", "-lc++abi" }).done();
            }
        } else if (ctx.command == .link) {
            map.initFilter("--help").replaceWith(&.{"-help"}).done();
            map.initFilter("-v").replaceWith(&.{"--version"}).done();
        }
    }

    pub fn isWeakLib(ctx: *ZigWrapper, lib: []const u8) bool {
        if (generic_weak_libs.getIndex(lib) != null) {
            return true;
        }
        if (ctx.target_is_windows and !ctx.target_is_msvc and
            windows_gnu_weak_libs.getIndex(lib) != null)
        {
            return true;
        }
        return false;
    }

    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .matchers = std.ArrayList(Matcher).init(allocator),
            .replacers = std.ArrayList(Replacer).init(allocator),
        };
    }

    pub fn deinit(self: Self) void {
        self.matchers.deinit();
        self.replacers.deinit();
    }

    pub inline fn done(self: *Self) void {
        _ = self;
    }

    /// Set the end of the current filter, and return the next one.
    pub inline fn eof(self: *Self) *Self {
        const p: [*]Self = @ptrCast(self);
        return &p[1];
    }

    pub fn allowPartialOpt(self: *Self) *Self {
        self.matchers.append(.{ .allow_partial_opt = {} }) catch unreachable;
        return self;
    }

    pub fn target(self: *Self, pattern: []const u8) *Self {
        self.matchers.append(.{ .target = pattern }) catch unreachable;
        return self;
    }

    pub fn command(self: *Self, pattern: []const u8) *Self {
        self.matchers.append(.{ .command = pattern }) catch unreachable;
        return self;
    }

    pub fn linker(self: *Self, is_linker: bool) *Self {
        self.matchers.append(.{ .linker = is_linker }) catch unreachable;
        return self;
    }

    /// Match the current argument with the given pattern.
    pub fn match(self: *Self, pattern: []const u8) *Self {
        self.matchers.append(.{ .match = pattern }) catch unreachable;
        return self;
    }

    /// Move to the next argument.
    pub fn next(self: *Self) *Self {
        self.matchers.append(.{ .next = {} }) catch unreachable;
        return self;
    }

    pub fn replaceWith(self: *Self, replacement: []const []const u8) *Self {
        self.replacers.ensureUnusedCapacity(replacement.len) catch unreachable;
        for (replacement) |s| {
            self.replacers.appendAssumeCapacity(.{ .string = s });
        }
        return self;
    }

    pub fn replaceWithOptValue(self: *Self) *Self {
        self.replacers.append(.{ .opt_value = {} }) catch unreachable;
        return self;
    }

    pub fn replaceWithArg(self: *Self, arg_index: usize) *Self {
        self.replacers.append(.{ .arg_index = arg_index }) catch unreachable;
        return self;
    }
};

pub const ZigArgFilterMap = struct {
    const Self = @This();
    map: std.StringArrayHashMap(std.ArrayList(ZigArgFilter)),

    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .map = std.StringArrayHashMap(std.ArrayList(ZigArgFilter)).init(allocator),
        };
    }

    pub fn deinit(self: *Self) void {
        for (self.map.values()) |filters| {
            for (filters.items) |filter| {
                filter.deinit();
            }
            filters.deinit();
        }
        self.map.deinit();
    }

    pub inline fn initFilter(self: *Self, option: []const u8) *ZigArgFilter {
        return self.initFilters(option, 1);
    }

    pub fn initFilters(self: *Self, option: []const u8, count: usize) *ZigArgFilter {
        const entry = self.map.getPtr(option) orelse blk: {
            self.map.put(
                option,
                std.ArrayList(ZigArgFilter).init(self.map.allocator),
            ) catch unreachable;
            break :blk self.map.getPtr(option).?;
        };

        const start = entry.items.len;
        entry.ensureUnusedCapacity(count) catch unreachable;
        for (0..count) |_| {
            entry.appendAssumeCapacity(ZigArgFilter.init(self.map.allocator));
        }
        return &entry.items.ptr[start];
    }

    pub fn next(self: *Self, ctx: *ZigWrapper, input: *SimpleOptionParser, output: *StringArray) !?void {
        const opt = input.next() orelse return null;

        if (strStartsWith(opt, "-")) {
            for (0..4) |loop| {
                var opt_value: []const u8 = undefined;
                var opt_value_valid = false;
                var opt_partial = false;
                var allow_partial_opt = false;

                const filters: []const ZigArgFilter = blk: {
                    switch (loop) {
                        0 => if (self.map.getPtr(opt)) |v| {
                            // match [-|--]<key>
                            break :blk v.items;
                        },
                        1 => if (std.mem.indexOf(u8, opt, "=")) |i| {
                            // match [-|--]<key>=<value>
                            if (self.map.getPtr(opt[0..i])) |v| {
                                opt_value = opt[i + 1 ..];
                                opt_value_valid = true;
                                break :blk v.items;
                            }
                        },
                        2 => if (std.mem.indexOf(u8, opt, ",")) |i| {
                            // match [-|--]<key>,<value>
                            if (self.map.getPtr(opt[0 .. i + 1])) |v| {
                                opt_value = opt[i + 1 ..];
                                opt_value_valid = true;
                                break :blk v.items;
                            }
                        },
                        3 => if (opt.len > 2 and opt[1] != '-') {
                            // match -<letter><value>
                            if (self.map.getPtr(opt[0..2])) |v| {
                                opt_value = opt[2..];
                                opt_value_valid = true;
                                opt_partial = true;
                                break :blk v.items;
                            }
                        },
                        else => unreachable,
                    }
                    continue;
                };

                filter: for (filters) |filter| {
                    var consumed: usize = 0;

                    const Matcher = struct {
                        fn call(pattern: []const u8, string: []const u8) bool {
                            if (strStartsWith(pattern, "!")) {
                                return !strMatch(pattern[1..], string);
                            } else {
                                return strMatch(pattern, string);
                            }
                        }
                    };
                    for (filter.matchers.items) |matcher| {
                        switch (matcher) {
                            .allow_partial_opt => {
                                allow_partial_opt = true;
                            },
                            .command => |pattern| {
                                if (!Matcher.call(pattern, @tagName(ctx.command))) {
                                    continue :filter;
                                }
                            },
                            .linker => |is_linker| {
                                if (ctx.is_linker != is_linker) {
                                    continue :filter;
                                }
                            },
                            .target => |pattern| {
                                if (!Matcher.call(pattern, ctx.zig_target)) {
                                    continue :filter;
                                }
                            },
                            .match => |pattern| {
                                const arg = if (opt_value_valid and consumed == 0)
                                    opt_value
                                else blk: {
                                    if (consumed == 0) consumed += 1;
                                    if (consumed - 1 >= input.args.len) {
                                        continue :filter;
                                    }
                                    const s = input.args[consumed - 1];
                                    if (!opt_value_valid and consumed == 1) {
                                        opt_value = input.args[0];
                                        opt_value_valid = true;
                                    }
                                    break :blk s;
                                };
                                if (!Matcher.call(pattern, arg)) {
                                    continue :filter;
                                }
                            },
                            .next => {
                                if (consumed >= input.args.len) {
                                    continue :filter;
                                }
                                consumed += 1;
                            },
                        }
                    }

                    if (opt_partial and !allow_partial_opt) {
                        continue :filter;
                    }

                    for (filter.replacers.items) |replacer| {
                        switch (replacer) {
                            .opt_value => {
                                if (opt_value_valid) {
                                    try output.append(opt_value);
                                }
                            },
                            .arg_index => |arg_index| {
                                if (arg_index == 0) {
                                    try output.append(opt);
                                } else if (arg_index <= consumed) {
                                    try output.append(input.args[arg_index - 1]);
                                }
                            },
                            .string => |str| {
                                try output.append(str);
                            },
                        }
                    }
                    // consume the input arguments
                    input.advance(consumed);
                    return;
                }
            }
        }

        try output.append(opt);
        return;
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

    pub fn dupeString(self: *Self, source: []const u8) std.mem.Allocator.Error![]u8 {
        const value = try self.allocator().dupe(u8, source);
        self.addString(value);
        return value;
    }

    pub fn allocPrint(self: *Self, comptime fmt: []const u8, args: anytype) std.fmt.AllocPrintError![]u8 {
        const value = try std.fmt.allocPrint(self.allocator(), fmt, args);
        self.addString(value);
        return value;
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

const SimpleOptionParser = struct {
    const Self = @This();
    args: []const []const u8,
    always_positional: bool = false,
    consumed: []const []const u8 = &[_][]const u8{},
    option: []const u8 = "",
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
            self.advance(1);
            return self.consumed.ptr[0];
        }
        return null;
    }

    /// Skip the next `count` arguments.
    pub fn advance(self: *Self, count: usize) void {
        self.consumed = self.args[0..count];
        self.args = self.args[count..];
    }

    /// Do not consume any argument if failed.
    pub fn parsePositional(self: *Self, accept_double_dash: bool) ?[]const u8 {
        while (self.first()) |arg| {
            if (self.always_positional or !strStartsWith(arg, "-")) {
                self.advance(1);
                return arg;
            }
            if (strEql(arg, "--")) {
                self.always_positional = true;
                self.advance(1);
                if (accept_double_dash) return arg;
            } else {
                break;
            }
        }
        return null;
    }

    /// Do not consume any argument if failed.
    pub fn parseNamed(self: *Self, options: []const []const u8, require_value: bool) bool {
        if (self.first()) |arg| {
            for (options) |opt| {
                if (strEql(arg, opt)) {
                    if (!require_value) {
                        self.option = arg;
                        self.advance(1);
                        return true;
                    } else if (self.args.len > 1) {
                        self.option = arg;
                        self.value = self.args[1];
                        self.advance(2);
                        return true;
                    } else {
                        return false;
                    }
                }

                if (!require_value) continue;

                if (strStartsWith(arg, opt)) {
                    if (opt.len == 2 and opt[0] == '-') {
                        self.option = arg[0..opt.len];
                        self.value = arg[opt.len..];
                        self.advance(1);
                        return true;
                    } else if (arg[opt.len] == '=') {
                        self.option = arg[0..opt.len];
                        self.value = arg[opt.len + 1 ..];
                        self.advance(1);
                        return true;
                    }
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
    sys_argv0: []const u8 = "",
    sys_argv: StringArray,
    zig_exe: []const u8 = "",

    /// The current Zig command.
    command: ZigCommand = ZigCommand.cc,

    is_quering_version: bool = false,
    /// If the Zig command is running as a linker.
    is_linker: bool = false,
    /// If the Zig compiler is running as a proprocessor.
    is_preprocessor: bool = false,
    /// If the output file is a shared library.
    is_shared_lib: bool = false,
    /// Disallow to parse the compiler flags from `<LANG>FLAGS_<TARGET>` environment variables.
    allow_target_env_flags: bool = false,
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
                .sys_argv = StringArray.init(alloc.allocator()),
                .zig_cpu_opts = StringArray.init(alloc.allocator()),
                .zig_cpu_tune_opts = StringArray.init(alloc.allocator()),
                .skipped_libs = StringSet.init(alloc.allocator()),
                .skipped_lib_patterns = StringArray.init(alloc.allocator()),
                .skipped_lib_paths = StringSet.init(alloc.allocator()),
                .arg_filter = ZigArgFilterMap.init(alloc.allocator()),
                .args = StringArray.init(alloc.allocator()),
            };
        };
        errdefer self.deinit();

        // Collect `argv[0..]`...
        var argv = StringArray.init(self.allocator());
        defer argv.deinit();

        var arg_iter = try self.alloc.sysArgvIterator();
        if (arg_iter.next()) |argv0| {
            self.sys_argv0 = argv0;
        }
        while (arg_iter.next()) |arg| {
            if (strStartsWith(arg, "@")) {
                // Parse the flags file.
                try self.parseFileFlags(arg[1..], &argv);
                self.at_file_opt = arg;
                continue;
            }

            // If the flags file is not the last argument, ignore it.
            if (self.at_file_opt != null) {
                self.at_file_opt = null;
            }
            try argv.append(arg);
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
        self.zig_exe = self.alloc.getEnvVar("ZIG_EXECUTABLE") catch "";
        self.zig_target = self.alloc.getEnvVar("ZIG_WRAPPER_TARGET") catch "";
        self.clang_target = self.alloc.getEnvVar("ZIG_WRAPPER_CLANG_TARGET") catch "";

        // Parse Zig flags in `argv[1..]`.
        try self.sys_argv.ensureUnusedCapacity(argv.items.len);
        try self.parseCustomArgs(argv.items, &self.sys_argv);
        argv.clearRetainingCapacity();

        // Parse Zig flags in the environment variables.
        try self.parseEnvFlags(&argv);
        if (!stringsContains(self.sys_argv.items, argv.items)) {
            try self.sys_argv.appendSlice(argv.items);
        }
        argv.clearRetainingCapacity();

        // Set default values.
        if (self.zig_exe.len == 0) {
            self.zig_exe = try self.alloc.allocPrint(
                "zig{s}",
                .{builtin.os.tag.exeFileExt(builtin.cpu.arch)},
            );
        }
        if (self.zig_target.len == 0) {
            self.zig_target = try self.alloc.allocPrint(
                "{s}-{s}-{s}",
                .{
                    @tagName(builtin.target.cpu.arch),
                    @tagName(builtin.target.os.tag),
                    @tagName(builtin.target.abi),
                },
            );
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

        ZigArgFilter.initFilterMap(&self, &self.arg_filter);
        return self;
    }

    pub fn deinit(self: *Self) void {
        if (self.flags_file) |*flags_file| {
            flags_file.deinit();
            self.flags_file = null;
        }
        self.args.deinit();
        self.arg_filter.deinit();
        self.skipped_lib_paths.deinit();
        self.skipped_lib_patterns.deinit();
        self.skipped_libs.deinit();
        self.zig_cpu_tune_opts.deinit();
        self.zig_cpu_opts.deinit();
        self.log.deinit();
        self.sys_argv.deinit();
        self.alloc.deinit();
    }

    pub inline fn allocator(self: *Self) std.mem.Allocator {
        return self.alloc.allocator();
    }

    pub fn run(self: *Self) !u8 {
        // Zig executable
        try self.args.append(self.zig_exe);
        // Zig command
        try self.args.append(self.command.toName());
        // `cc`, `c++`: -target <target> [-march=<cpu>] [-mtune=<cpu>]
        if (self.command.isCompiler()) {
            try self.args.appendSlice(&[_][]const u8{ "-target", self.zig_target });
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
                            @constCast(&.{ .args = &.{opt} }),
                            &self.args,
                        );
                    }
                }
            }
            if (self.target_is_windows) {
                // Undefine `_WIN32_WINNT` for Windows targets.
                try self.args.appendSlice(&[_][]const u8{"-U_WIN32_WINNT"});
            }
            if (self.is_linker) {
                try self.args.appendSlice(&.{ "-lc++", "-lc++abi", "-lomp" });
            }
        }

        var argv = try StringArray.initCapacity(self.alloc.allocator(), self.sys_argv.items.len);
        defer argv.deinit();
        std.mem.swap(StringArray, &self.sys_argv, &argv);
        for (argv.items) |arg| {
            try self.fixCommandFlag(@constCast(arg), &self.sys_argv);
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
        var child = std.process.Child.init(self.args.items, self.allocator());
        var exit_code: u8 = 0;
        if (self.log.enabled()) {
            child.stderr_behavior = .Pipe;
            child.stdout_behavior = .Pipe;
            var stdout = std.ArrayList(u8).init(self.allocator());
            var stderr = std.ArrayList(u8).init(self.allocator());
            defer {
                stdout.deinit();
                stderr.deinit();
            }
            try child.spawn();
            try child.collectOutput(&stdout, &stderr, 10 * 1024 * 1024);
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
        const flags_str = try self.alloc.allocString(file_size);
        errdefer self.alloc.freeString(flags_str);

        // Read the file content into the buffer
        _ = try file.readAll(flags_str);

        // Parse the flags
        var arg_iter = try self.alloc.argIteratorTakeOwnership(flags_str);
        self.alloc.forgetString(flags_str);
        while (arg_iter.next()) |arg| {
            try dest.append(arg);
        }
    }

    fn parseEnvFlags(self: *Self, dest: *StringArray) !void {
        // Do not use environment variables if we are querying the compiler version.
        if (self.is_quering_version) {
            return;
        }

        const buf = try self.allocator().alloc(u8, 32 +
            @max(self.zig_target.len, self.clang_target.len));
        defer self.allocator().free(buf);

        var args = StringArray.init(self.allocator());
        defer args.deinit();
        var tmp = StringArray.init(self.allocator());
        defer tmp.deinit();

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
                    const flags_str = self.alloc.getEnvVar(key) catch continue;
                    var arg_iter = try self.alloc.argIteratorTakeOwnership(flags_str);
                    self.alloc.forgetString(flags_str);

                    while (arg_iter.next()) |arg| {
                        try tmp.append(arg);
                    }

                    // Do not append the same flags.
                    if (!stringsContains(args.items, tmp.items)) {
                        try args.appendSlice(tmp.items);
                    }
                    tmp.clearRetainingCapacity();
                }
            }
        }

        try self.parseCustomArgs(args.items, dest);
    }

    fn parseCustomArgs(self: *Self, args: []const []const u8, dest: *StringArray) !void {
        var parser = SimpleOptionParser{ .args = args };
        while (parser.hasArgument()) {
            if (parser.parsePositional(true)) |_| {
                // Skip positional arguments.
                try dest.appendSlice(parser.consumed);
            } else if (parser.parseNamed(ZigArgFilter.query_version_opts, false)) {
                self.is_quering_version = true;
                self.is_linker = false;
                // Do no consume the argument.
                try dest.appendSlice(parser.consumed);
            } else if (parser.parseNamed(ZigArgFilter.compile_only_opts, false)) {
                if (self.command.isCompiler()) {
                    self.is_linker = false;
                    if (!self.is_preprocessor and strEql(parser.consumed[0], "-E")) {
                        self.is_preprocessor = true;
                    }
                }
                // Do no consume the argument.
                try dest.appendSlice(parser.consumed);
            } else if (parser.parseNamed(&.{ "-shared", "-dll" }, false)) {
                if (self.command.isCompiler()) {
                    self.is_linker = true;
                    self.is_shared_lib = true;
                }
                // Do no consume the argument.
                try dest.appendSlice(parser.consumed);
            } else if (parser.parseNamed(&.{ "-target", "--target" }, true)) {
                if (self.zig_target.len == 0) {
                    self.zig_target = parser.value;
                }
            } else if (parser.parseNamed(&.{ "-march", "-mcpu" }, true)) {
                if (self.command.isCompiler()) {
                    if (parser.consumed.len == 1) {
                        try self.zig_cpu_opts.append(parser.consumed[0]);
                    }
                } else {
                    // Do no consume the argument.
                    try dest.appendSlice(parser.consumed);
                }
            } else if (parser.parseNamed(&.{"-mtune"}, true)) {
                if (self.command.isCompiler()) {
                    if (parser.consumed.len == 1) {
                        try self.zig_cpu_tune_opts.append(parser.consumed[0]);
                    }
                } else {
                    // Do no consume the argument.
                    try dest.appendSlice(parser.consumed);
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
                    if (v.len > 0) {
                        const res = try self.skipped_libs.getOrPut(v);
                        if (!res.found_existing and
                            std.mem.indexOfAny(u8, v, "?*") != null)
                        {
                            try self.skipped_lib_patterns.append(v);
                        }
                    }
                }
            } else if (parser.parseNamed(&.{"--skip-lib-path"}, true)) {
                var parts = std.mem.splitAny(u8, parser.value, ";");
                while (parts.next()) |part| {
                    const v = strTrimRight(part);
                    if (v.len > 0) {
                        _ = try self.skipped_lib_paths.getOrPut(v);
                    }
                }
            } else if (parser.parseNamed(&.{"--allow-target-env-flags"}, false)) {
                self.allow_target_env_flags = true;
            } else if (parser.parseNamed(&.{"-o"}, true)) {
                // Autoconfig uses `zig-cc` to compile DLL, wrongly builds out `.dll.a` instead of `.dll`.
                // We fix it to output the `.dll` file.
                if (parser.consumed.len == 2 and self.command.isCompiler() and
                    strEndsWith(parser.value, ".dll.a"))
                {
                    const dll_a = parser.value;
                    const dll = dll_a[0 .. dll_a.len - 2];
                    const lib_name = dll_a[0 .. dll_a.len - 6];

                    const lib_opt = try self.alloc.allocPrint(
                        "-Wl,--out-implib={s}.lib",
                        .{lib_name},
                    );
                    const dll_lib = lib_opt[17..];

                    try dest.appendSlice(&.{ "-shared", "-o", dll, lib_opt });
                    self.cc_dll_a = dll_a;
                    self.cc_dll_lib = dll_lib;
                } else {
                    // Do no consume the argument.
                    try dest.appendSlice(parser.consumed);
                }
            } else {
                // Do no consume the argument.
                try dest.append(parser.next().?);
            }
        }
    }

    fn fixLibFlag(self: *Self, arg: []u8) []u8 {
        // `-l<lib>`
        if (self.is_linker and strStartsWith(arg, "-l")) {
            const lib = arg[2..];

            // Trim prefix `winapi_` if the target is Windows.
            if (self.target_is_windows and strStartsWith(lib, "winapi_")) {
                return std.fmt.bufPrint(arg, "-l{s}", .{lib[7..]}) catch unreachable;
            }
        }
        return arg;
    }

    fn fixCommandFlag(self: *Self, arg: []u8, dest: *StringArray) !void {
        // `-Wl,<linker flags>`
        if (self.is_linker and strStartsWith(arg, "-Wl,")) {
            const buf = arg[4..];
            var buf_used: usize = 0;

            var parts = std.mem.splitAny(u8, buf, ",");
            while (parts.next()) |flag| {
                if (strEndsWith(flag, ".def")) {
                    // `/DEF:<lib>.def`
                    var def_file = flag;
                    if (strStartsWith(def_file, "/DEF:")) {
                        def_file = def_file[5..];
                    }
                    const s = try self.alloc.dupeString(def_file);
                    try dest.append(s);
                } else if (strStartsWith(flag, "-l")) {
                    // `-l<lib>`
                    const s = try self.alloc.dupeString(flag);
                    try dest.append(self.fixLibFlag(s));
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
                try dest.append(arg[0 .. 4 + buf_used]);
            }
            return;
        }

        return try dest.append(self.fixLibFlag(arg));
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
        const INVALID_PTR: [*]const u8 = @ptrFromInt(std.math.maxInt(usize));
        var args = try StringArray.initCapacity(
            self.allocator(),
            self.args.items.len,
        );
        var lib_map = std.StringArrayHashMap(std.ArrayList(LinkerLib)).init(
            self.allocator(),
        );
        var path_set = std.StringArrayHashMap(void).init(self.allocator());
        defer {
            args.deinit();
            for (lib_map.values()) |array| {
                array.deinit();
            }
            lib_map.deinit();
            for (path_set.keys()) |path| {
                self.allocator().free(path);
            }
            path_set.deinit();
        }

        var parser = SimpleOptionParser{ .args = self.args.items };
        outer: while (parser.hasArgument()) {
            if (parser.parseNamed(&.{"-l"}, false)) {
                // This option is invalid, skip.
            } else if (parser.parseNamed(&.{"-l"}, true)) {
                var lib = self.libFromFileName(parser.value);
                lib.index = args.items.len;

                if (self.skipped_libs.contains(lib.name)) continue;
                for (self.skipped_lib_patterns.items) |pattern| {
                    if (strMatch(pattern, lib.name)) {
                        continue :outer;
                    }
                }

                var lib_ver = libVersionSplit(lib.name);
                if (lib_map.getPtr(lib_ver[0])) |libs| {
                    for (libs.items) |*entry| {
                        const entry_ver = libVersionSplit(entry.name);
                        if (strEql(entry.name, lib.name)) {
                            // Drop the duplicate link library.
                            if (entry.kind == .none and lib.kind != .none) {
                                entry.kind = lib.kind;
                            }
                            continue :outer;
                        }
                        if (versionCompare(entry_ver[1], lib_ver[1]) < 0) {
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
                    var libs = try std.ArrayList(LinkerLib).initCapacity(self.allocator(), 4);
                    errdefer libs.deinit();
                    try libs.append(lib);
                    try lib_map.put(lib_ver[0], libs);
                }
            } else if (parser.parseNamed(&.{"-L"}, true)) {
                // normalize path
                if (std.fs.path.relative(
                    self.allocator(),
                    ".",
                    parser.value,
                )) |path| {
                    var ok = false;
                    defer if (!ok) self.allocator().free(path);

                    _ = std.mem.replace(u8, path, "\\", "/", path);
                    if (path_set.contains(path)) continue;
                    for (self.skipped_lib_paths.keys()) |pattern| {
                        if (strMatch(pattern, path)) {
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
            const cwd = try self.allocator().dupe(u8, ".");
            errdefer self.allocator().free(cwd);
            try path_set.put(cwd, {});
        }

        // Find the library paths and fix link options.
        var buf = std.ArrayList(u8).init(self.allocator());
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
                                        try self.alloc.allocPrint("-l{s}", .{file_lib.name})
                                    else
                                        try self.alloc.dupeString(buf.items);
                                    args.items[lib.index] = lib_opt;
                                    continue :next_lib;
                                }
                            } else |_| {}
                        }
                    }
                }

                if (ZigArgFilter.isWeakLib(self, lib.name)) {
                    args.items[lib.index].ptr = INVALID_PTR;
                    continue;
                }

                // Try to fix `-l:<file>` options.
                buf.clearRetainingCapacity();
                try buf.appendSlice("-l");
                try buf.appendSlice(lib.name);
                if (!strEql(buf.items, args.items[lib.index])) {
                    const opt = try self.alloc.dupeString(buf.items);
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
                        self.windres_input = arg;
                    } else if (self.windres_output == null) {
                        self.windres_output = arg;
                    }
                } else if (parser.parseNamed(&.{ "-i", "--input" }, true)) {
                    self.windres_input = parser.value;
                } else if (parser.parseNamed(&.{ "-o", "--output" }, true)) {
                    self.windres_output = parser.value;
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
                    if (self.windres_preprocessor_arg) |pre_arg| {
                        self.windres_preprocessor_arg = null;
                        if (strEql(pre_arg, "-MF")) {
                            self.windres_depfile = parser.value;
                        }
                    } else if (strEql(parser.value, "-MD")) {
                        if (self.windres_depfile == null) {
                            self.windres_depfile = "";
                        }
                    } else if (strEql(parser.value, "-MF")) {
                        self.windres_preprocessor_arg = parser.value;
                    } else {
                        // Skip other processor arguments.
                    }
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
                    if (self.windres_input) |v| try self.args.append(v);
                    if (self.windres_output) |v| try self.args.append(v);
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

            at_file_opt = try self.alloc.allocPrint("@{s}", .{flags_file.getPath()});
            self.flags_file = flags_file;
        }

        // Only keep the executable path and the command type.
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
                    var path = depfile;
                    if (depfile.len == 0) {
                        const output = self.windres_output orelse return;
                        path = try self.alloc.allocPrint("{s}.d", .{output});
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
