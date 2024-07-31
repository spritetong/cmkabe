const std = @import("std");
const builtin = @import("builtin");

const ZigCommand = enum {
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

    const Self = @This();

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

const ZigLog = struct {
    file: ?std.fs.File,

    const Self = @This();

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
    allocator: std.mem.Allocator,
    buffers: std.ArrayList([]const u8),
    arg_iter: std.process.ArgIterator,
    sys_argv: std.ArrayList([]const u8),
    log: ZigLog,
    command: ZigCommand,
    /// <arch>-<vendor>-<os>-<abi>
    clang_target: []const u8,
    /// <arch>-<os>-<abi>
    zig_target: []const u8,
    args: std.ArrayList([]const u8),

    const Self = @This();

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

        return .{
            .allocator = allocator,
            .buffers = std.ArrayList([]const u8).init(allocator),
            .arg_iter = arg_iter,
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
        const zig_exe = getEnvVarOwned(self.allocator, "ZIG_EXECUTABLE") catch
            try std.fmt.allocPrint(
            self.allocator,
            "zig{s}",
            .{builtin.os.tag.exeFileExt(builtin.cpu.arch)},
        );
        self.buffers.append(zig_exe) catch unreachable;
        try self.args.append(zig_exe);

        // command
        try self.args.append(self.command.toName());

        // cc, c++: -target <target>
        if (getEnvVarOwned(self.allocator, "ZIG_WRAPPER_CLANG_TARGET")) |target| {
            self.buffers.append(target) catch unreachable;
            self.clang_target = target;
        } else |_| {}
        try self.targetInit(blk: {
            if (getEnvVarOwned(self.allocator, "ZIG_WRAPPER_TARGET")) |target| {
                self.buffers.append(target) catch unreachable;
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

        var skip = false;
        for (self.sys_argv.items) |arg| {
            self.log.write(" ");
            self.log.write(arg);
            switch (self.trySkip(arg)) {
                0 => try self.appendArgument(arg),
                1 => {},
                2 => skip = true,
                else => unreachable,
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
        self.arg_iter.deinit();
        for (self.buffers.items) |buf| {
            self.allocator.free(buf);
        }
        self.buffers.clearAndFree();
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
                const flags_str = getEnvVarOwned(self.allocator, key) catch continue;
                defer self.allocator.free(flags_str);
                var args_iter = std.process.ArgIteratorGeneral(.{}).init(
                    self.allocator,
                    flags_str,
                ) catch unreachable;
                defer args_iter.deinit();
                args.clearRetainingCapacity();
                while (args_iter.next()) |arg| {
                    try args.append(arg);
                }

                // Do not append the same flags.
                if (!stringsContains(self.args.items[1..], args.items) and
                    !stringsContains(self.sys_argv.items, args.items))
                {
                    var skip = false;
                    for (args.items) |_arg| {
                        const arg = try self.allocator.dupe(u8, _arg);
                        self.buffers.append(arg) catch unreachable;

                        switch (self.trySkip(arg)) {
                            0 => try self.appendArgument(arg),
                            1 => {},
                            2 => skip = true,
                            else => unreachable,
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

    fn trySkip(self: *Self, arg: []const u8) usize {
        const skip_two = std.StaticStringMap(void).initComptime(.{
            // --target <target>
            .{"--target"},
            // "--target" <target>
            .{"\"--target\""},
            // -m <target>, unknown Clang option: '-m'
            .{"-m"},
        });
        switch (self.command) {
            .cc, .cxx => {
                // Skip:
                //     --target=<target>
                //     "--target=<target>"
                //     -Wl,-v
                if (strStartsWith(arg, "--target=") or
                    strStartsWith(arg, "\"--target="))
                {
                    return 1;
                }
                if (skip_two.get(arg) != null) {
                    return 2;
                }
            },
            else => {},
        }
        return 0;
    }

    fn appendArgument(self: *Self, arg: []const u8) !void {
        const replacement = std.StaticStringMap([]const u8).initComptime(.{
            // strip local symbols
            .{ "-Wl,-x", "-Wl,--strip-debug" },
            .{ "-Wl,-v", "" },
            // x265
            .{ "-march=i586", "" },
            .{ "-march=i686", "" },
        });
        switch (self.command) {
            .cc, .cxx => {
                if (replacement.get(arg)) |s| {
                    if (s.len > 0) {
                        try self.args.append(s);
                    }
                    return;
                }
            },
            else => {},
        }
        return self.args.append(arg);
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
