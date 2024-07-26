const std = @import("std");

const ZigCommand = enum {
    ar,
    cc,
    cxx,
    dlltool,
    lib,
    objcopy,
    ranlib,
    rc,
    strip,

    fn fromStr(str: []const u8) ?ZigCommand {
        return std.StaticStringMap(ZigCommand).initComptime(.{
            .{ "ar", .ar },
            .{ "cc", .cc },
            .{ "c++", .cxx },
            .{ "dlltool", .dlltool },
            .{ "lib", .lib },
            .{ "objcopy", .objcopy },
            .{ "ranlib", .ranlib },
            .{ "strip", .strip },
            .{ "rc", .rc },
            .{ "gcc", .cc },
            .{ "g++", .cxx },
        }).get(str);
    }

    fn toString(self: ZigCommand) []const u8 {
        return switch (self) {
            .cxx => "c++",
            else => @tagName(self),
        };
    }
};

pub fn main() noreturn {
    std.process.exit(zig_wrapper_run() catch 1);
}

/// Check if `haystack` starts with `needle`.
fn strStartsWith(haystack: []const u8, needle: []const u8) bool {
    if (needle.len > haystack.len) {
        return false;
    }
    return std.mem.eql(u8, haystack[0..needle.len], needle);
}

/// Check if `haystack` ends with `needle`.
fn strEndsWith(haystack: []const u8, needle: []const u8) bool {
    if (needle.len > haystack.len) {
        return false;
    }
    return std.mem.eql(u8, haystack[haystack.len - needle.len ..], needle);
}

fn zig_wrapper_run() !u8 {
    var gpa = std.heap.GeneralPurposeAllocator(.{}){};
    const alloc = gpa.allocator();

    // Parse the command line arguments.
    var args = try std.process.argsWithAllocator(alloc);
    defer args.deinit();

    // Parse the Zig command from argv[0].
    const arg0 = args.next().?;
    const stem = std.fs.path.stem(arg0);
    const ext = std.fs.path.extension(arg0);

    const zig_command = ZigCommand.fromStr(
        stem[std.mem.lastIndexOfScalar(u8, stem, '-').? + 1 ..],
    ) orelse return 1;
    if (zig_command == .strip) {
        _ = try std.io.getStdErr().write("zig-strip is not implemented.\n");
        return 0;
    }

    const zig_root = std.process.getEnvVarOwned(alloc, "ZIG_ROOT") catch
        try alloc.alloc(u8, 0);
    defer alloc.free(zig_root);
    const zig_target = std.process.getEnvVarOwned(alloc, "ZIG_WRAPPER_TARGET") catch
        try alloc.alloc(u8, 0);
    defer alloc.free(zig_target);

    const zig_exe = try std.fmt.allocPrint(alloc, "{s}{s}zig{s}", .{
        zig_root,
        if (zig_root.len == 0) "" else std.fs.path.sep_str,
        ext,
    });
    defer alloc.free(zig_exe);

    // Generate the command line arguments.
    var argv = std.ArrayList([]const u8).init(alloc);
    defer argv.deinit();
    try argv.append(zig_exe);
    try argv.append(zig_command.toString());

    if ((zig_target.len > 0) and
        (zig_command == .cc or zig_command == .cxx))
    {
        try argv.append("-target");
        try argv.append(zig_target);
        // https://github.com/ziglang/zig/wiki/FAQ#why-do-i-get-illegal-instruction-when-using-with-zig-cc-to-build-c-code
        try argv.append("-fno-sanitize=undefined");
    }

    // For libmount
    // switch (zig_command) {
    //     .cc, .cxx => {
    //         try argv.appendSlice(&[_][]const u8{
    //             "-DHAVE_CLOSE_RANGE=1",
    //             "-DHAVE_STATX=1",
    //             "-DHAVE_OPEN_TREE=1",
    //             "-DHAVE_MOVE_MOUNT=1",
    //             "-DHAVE_MOUNT_SETATTR=1",
    //             "-DHAVE_FSCONFIG=1",
    //             "-DHAVE_FSOPEN=1",
    //             "-DHAVE_FSMOUNT=1",
    //             "-DHAVE_FSPICK=1",
    //         });
    //     },
    //     else => {},
    // }

    // Skip the `--target` argument for Clang.
    var skip = false;
    while (args.next()) |arg| {
        if (skip) {
            skip = false;
        } else if (std.mem.eql(u8, arg, "-Wl,-x")) {
            try argv.append("-Wl,--strip-debug");
        } else if (std.mem.eql(u8, arg, "--target") or
            std.mem.eql(u8, arg, "\"--target\""))
        {
            skip = true;
        } else if (!strStartsWith(arg, "--target=") and
            !strEndsWith(arg, "\"--target="))
        {
            try argv.append(arg);
        }
    }

    // Execute the command.
    var proc = std.process.Child.init(argv.items, alloc);
    const term = try proc.spawnAndWait();
    return term.Exited;
}
