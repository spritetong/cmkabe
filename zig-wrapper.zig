const std = @import("std");
const builtin = @import("builtin");

const ZigCommand = enum {
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
            .{ "strip", .strip },
            .{ "rc", .rc },
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
};

const ZigArgOp = union(enum) {
    const Self = @This();
    replace: []const []const u8,
    match_next_and_replace: struct { []const u8, []const []const u8 },

    const cc_table = std.StaticStringMap([]const Self).initComptime(.{
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
        .{ "-Wl,-x", &.{Self.replace_with(&.{"-Wl,--strip-debug"})} },
        .{ "-Wl,-v", &.{Self.skip} },
        // x265
        .{ "-march=i586", &.{Self.skip} },
        .{ "-march=i686", &.{Self.skip} },
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

const Deallcator = union(enum) {
    const Self = @This();
    arg_iter: std.process.ArgIterator,
    arg_iter_gen: std.process.ArgIteratorGeneral(.{}),
    string: struct { std.mem.Allocator, []u8 },

    fn deinit(self: *Self) void {
        switch (self.*) {
            .arg_iter => |*v| v.deinit(),
            .arg_iter_gen => |*v| v.deinit(),
            .string => |*v| v.@"0".free(v.@"1"),
        }
    }
};

const ResourceCollection = struct {
    const Self = @This();
    items: std.ArrayList(Deallcator),

    fn init(allocator_: std.mem.Allocator) Self {
        return .{ .items = std.ArrayList(Deallcator).init(allocator_) };
    }

    fn deinit(self: *Self) void {
        self.clear();
        self.items.deinit();
    }

    inline fn allocator(self: *Self) std.mem.Allocator {
        return self.items.allocator;
    }

    fn clear(self: *Self) void {
        while (self.items.popOrNull()) |*de| {
            @constCast(de).deinit();
        }
        self.items.clearRetainingCapacity();
    }

    fn add_arg_iterator(self: *Self, arg_iter: std.process.ArgIterator) void {
        self.items.append(.{
            .arg_iter = arg_iter,
        }) catch unreachable;
    }

    fn add_arg_iter_general(self: *Self, arg_iter: std.process.ArgIteratorGeneral(.{})) void {
        self.items.append(.{
            .arg_iter_gen = arg_iter,
        }) catch unreachable;
    }

    fn add_string(self: *Self, string: []u8) void {
        self.items.append(.{
            .string = .{ self.items.allocator, string },
        }) catch unreachable;
    }

    fn getEnvVar(self: *Self, key: []const u8) std.process.GetEnvVarOwnedError![]u8 {
        const value = try getEnvVarOwned(self.allocator(), key);
        self.add_string(value);
        return value;
    }
};

const ZigLog = struct {
    const Self = @This();
    file: ?std.fs.File,

    fn init(allocator: std.mem.Allocator) !Self {
        if (getEnvVarOwned(allocator, "ZIG_WRAPPER_LOG_PATH")) |path| {
            defer allocator.free(path);

            var file = try std.fs.cwd().createFile(path, .{
                .read = true,
                .truncate = false,
            });
            errdefer file.close();

            // Lock file.
            try file.lock(.exclusive);

            // Seek to the end.
            const stat = try file.stat();
            try file.seekTo(stat.size);

            return .{ .file = file };
        } else |_| {
            return .{ .file = null };
        }
    }

    fn deinit(self: *Self) void {
        if (self.file) |file| {
            file.sync() catch {};
            file.unlock();
            file.close();
            self.file = null;
        }
    }

    fn write(self: *Self, bytes: []const u8) void {
        if (self.file) |file| {
            _ = file.write(bytes) catch {};
        }
    }

    fn print(self: *Self, comptime fmt: []const u8, args: anytype) void {
        if (self.file) |file| {
            file.writer().print(fmt, args) catch {};
        }
    }
};

const ZigWrapper = struct {
    const Self = @This();
    allocator: std.mem.Allocator,
    gc: ResourceCollection,
    sys_argv: std.ArrayList([]const u8),
    log: ZigLog,
    command: ZigCommand,
    /// <arch>-<vendor>-<os>-<abi>
    clang_target: []const u8,
    /// <arch>-<os>-<abi>
    zig_target: []const u8,
    args: std.ArrayList([]const u8),

    fn init(allocator: std.mem.Allocator) !Self {
        var arg_iter = try std.process.argsWithAllocator(allocator);
        errdefer arg_iter.deinit();
        var sys_argv = std.ArrayList([]const u8).init(allocator);
        errdefer sys_argv.deinit();

        const argv0 = arg_iter.next().?;
        const stem = std.fs.path.stem(argv0);

        const command = ZigCommand.fromStr(
            stem[if (std.mem.lastIndexOfScalar(u8, stem, '-')) |s| s + 1 else 0..],
        ) orelse return error.InvalidZigCommand;

        // Collect `argv[1]`...
        while (arg_iter.next()) |arg| {
            try sys_argv.append(arg);
        }

        // log the `argv[0]`
        var log = try ZigLog.init(allocator);
        errdefer log.deinit();
        log.print("{s}", .{argv0});

        var gc = ResourceCollection.init(allocator);
        gc.add_arg_iterator(arg_iter);

        return .{
            .allocator = allocator,
            .gc = gc,
            .sys_argv = sys_argv,
            .log = log,
            .command = command,
            .zig_target = "",
            .clang_target = "",
            .args = std.ArrayList([]const u8).init(allocator),
        };
    }

    fn run(self: *Self) !u8 {
        // zig[.exe]
        const zig_exe = self.gc.getEnvVar("ZIG_EXECUTABLE") catch
            try std.fmt.allocPrint(
            self.allocator,
            "zig{s}",
            .{builtin.os.tag.exeFileExt(builtin.cpu.arch)},
        );
        try self.args.append(zig_exe);

        // command
        try self.args.append(self.command.toName());

        // cc, c++: -target <target>
        if (self.gc.getEnvVar("ZIG_WRAPPER_CLANG_TARGET")) |target| {
            self.clang_target = target;
        } else |_| {}
        try self.targetInit(blk: {
            if (self.gc.getEnvVar("ZIG_WRAPPER_TARGET")) |target| {
                self.zig_target = target;
                if (self.clang_target.len == 0) {
                    self.clang_target = target;
                }
                break :blk target;
            } else |_| {
                break :blk "";
            }
        });

        // Parse Zig flags in the environment variables.
        self.parseEnvFlags() catch {};

        var skip: usize = 0;
        for (self.sys_argv.items, 0..) |arg, i| {
            self.log.write(" ");
            self.log.write(arg);
            if (skip > 0) {
                skip -= 1;
            } else {
                skip = try self.appendArgument(arg, self.sys_argv.items[i + 1 ..]);
            }
        }
        self.log.write("\n");
        self.log.write("    -->");
        for (self.args.items) |arg| {
            self.log.write(" ");
            self.log.write(arg);
        }
        self.log.write("\n");

        // Execute the command.
        var proc = std.process.Child.init(self.args.items, self.allocator);
        const term = try proc.spawnAndWait();
        if (term.Exited != 0) {
            self.log.print("***** error code: {d}\n", .{term.Exited});
        }
        return term.Exited;
    }

    fn deinit(self: *Self) void {
        self.args.clearAndFree();
        self.log.deinit();
        self.sys_argv.clearAndFree();
        self.gc.deinit();
    }

    fn parseEnvFlags(self: *Self) !void {
        const buf = try self.allocator.alloc(u8, 20 + @max(
            self.zig_target.len,
            self.clang_target.len,
        ));
        defer self.allocator.free(buf);
        var args = std.ArrayList([]const u8).init(self.allocator);
        defer args.deinit();

        const name = self.command.toFlagsName() orelse return;
        // Do not apply the same targets.
        const array = [_][]const u8{ "", self.zig_target, self.clang_target };
        const targets = //
            if (strEql(self.zig_target, self.clang_target)) array[0..2] else array[0..];

        for (targets) |target| {
            // Get the compiler flags from the environment variable.
            const key = (if (target.len > 0) std.fmt.bufPrint(
                buf,
                "{s}_{s}",
                .{ name, target },
            ) else std.fmt.bufPrint(
                buf,
                "ZIG_WRAPPER_{s}",
                .{name},
            )) catch unreachable;

            // Try <target> and <target> with underscore.
            for (0..2) |loop| {
                if (loop == 1) {
                    if (std.mem.indexOf(u8, key, "-") == null) break;
                    _ = std.mem.replace(u8, key, "-", "_", key);
                }

                // Parse flags.
                const flags_str = self.gc.getEnvVar(key) catch continue;
                var arg_iter = std.process.ArgIteratorGeneral(.{}).init(
                    self.allocator,
                    flags_str,
                ) catch unreachable;
                self.gc.add_arg_iter_general(arg_iter);

                args.clearRetainingCapacity();
                while (arg_iter.next()) |arg| {
                    try args.append(arg);
                }

                // Do not append the same flags.
                if (!stringsContains(self.args.items[1..], args.items) and
                    !stringsContains(self.sys_argv.items, args.items))
                {
                    var skip: usize = 0;
                    for (args.items, 0..) |arg, i| {
                        if (skip > 0) {
                            skip -= 1;
                        } else {
                            skip = try self.appendArgument(arg, self.sys_argv.items[i + 1 ..]);
                        }
                    }
                }
            }
        }
    }

    fn targetInit(self: *Self, target: []const u8) !void {
        switch (self.command) {
            .cc, .cxx => {
                if (target.len > 0) {
                    try self.args.appendSlice(&[_][]const u8{ "-target", target });
                }

                // https://github.com/ziglang/zig/wiki/FAQ#why-do-i-get-illegal-instruction-when-using-with-zig-cc-to-build-c-code
                try self.args.append("-fno-sanitize=undefined");

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
            },
            else => {},
        }
    }

    fn appendArgument(self: *Self, arg: []const u8, remaining: []const []const u8) !usize {
        var opt = arg;
        switch (self.command) {
            .cc, .cxx => {
                // Strip quotes
                opt = std.mem.trim(u8, opt, "\"");

                if (ZigArgOp.cc_table.get(opt)) |arg_ops| {
                    for (arg_ops) |arg_op| switch (arg_op) {
                        .replace => |v| {
                            try self.args.appendSlice(v);
                            return 0;
                        },
                        .match_next_and_replace => |v| {
                            if (v.@"0".len == 0 or
                                (remaining.len > 0 or strEql(v.@"0", remaining[0])))
                            {
                                try self.args.appendSlice(v.@"1");
                                return 1;
                            }
                        },
                    };
                }

                var opt_kv = std.mem.splitAny(u8, opt, "=:");
                const opt_k = opt_kv.next().?;
                const opt_v = opt[opt_k.len + 1 ..];
                if (opt.len > opt_k.len) {
                    if (ZigArgOp.cc_table.get(opt_k)) |arg_ops| {
                        for (arg_ops) |arg_op| switch (arg_op) {
                            .replace => return 0,
                            .match_next_and_replace => |v| {
                                if (v.@"0".len == 0 or strEql(v.@"0", opt_v)) {
                                    try self.args.appendSlice(v.@"1");
                                    return 0;
                                }
                            },
                        };
                    }
                }
            },
            else => {},
        }

        try self.args.append(arg);
        return 0;
    }
};

/// Check if `a` and `b` are equal.
inline fn strEql(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

/// Remove trailing whitespace from `s`.
inline fn strTrimRight(s: []const u8) []const u8 {
    return std.mem.trimRight(u8, s, " \t\r\n");
}

/// Check if `haystack` starts with `needle`.
fn strStartsWith(haystack: []const u8, needle: []const u8) bool {
    if (needle.len > haystack.len) {
        return false;
    }
    return strEql(haystack[0..needle.len], needle);
}

/// Check if `haystack` ends with `needle`.
fn strEndsWith(haystack: []const u8, needle: []const u8) bool {
    if (needle.len > haystack.len) {
        return false;
    }
    return strEql(haystack[haystack.len - needle.len ..], needle);
}

/// Get the value of the environment variable `key`, do not accept empty value.
fn getEnvVarOwned(allocator: std.mem.Allocator, key: []const u8) std.process.GetEnvVarOwnedError![]u8 {
    const val = try std.process.getEnvVarOwned(allocator, key);
    const s = strTrimRight(val);
    if (s.len > 0) {
        return val[0..s.len];
    }
    allocator.free(val);
    return std.process.GetEnvVarOwnedError.EnvironmentVariableNotFound;
}

/// Check if `slice` contains `sub_slice`.
fn stringsContains(slice: []const []const u8, sub_slice: []const []const u8) bool {
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

pub fn main() noreturn {
    var status: u8 = 0;
    defer {
        std.process.exit(status);
    }
    errdefer |err| {
        _ = std.io.getStdErr().writer().print("error: {}\n", .{err}) catch {};
        std.process.exit(1);
    }

    var zig = try ZigWrapper.init(std.heap.c_allocator);
    defer zig.deinit();
    status = try zig.run();
}
