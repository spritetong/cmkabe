const std = @import("std");

pub fn main() noreturn {
    std.process.exit(zig_wrapper_run() catch 1);
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
    var zig_command = stem[std.mem.lastIndexOfScalar(u8, stem, '-').? + 1 ..];

    if (std.mem.eql(u8, "gcc", zig_command) or std.mem.eql(u8, "as", zig_command)) {
        zig_command = "cc";
    } else if (std.mem.eql(u8, "g++", zig_command)) {
        zig_command = "c++";
    } else if (std.mem.eql(u8, zig_command, "strip")) {
        std.debug.print("zig-strip is not implemented.\n", .{});
        return 0;
    }

    const zig_exe = try std.fmt.allocPrint(alloc, "zig{s}", .{std.fs.path.extension(arg0)});
    defer alloc.free(zig_exe);

    const zig_target = std.process.getEnvVarOwned(alloc, "ZIG_WRAPPER_TARGET") catch
        try alloc.alloc(u8, 0);
    defer alloc.free(zig_target);

    // Generate the command line arguments.
    var argv = std.ArrayList([]const u8).init(alloc);
    defer argv.deinit();
    try argv.append(zig_exe);
    try argv.append(zig_command);
    if ((zig_target.len > 0) and
        (std.mem.eql(u8, zig_command, "cc") or std.mem.eql(u8, zig_command, "c++")))
    {
        try argv.append("-target");
        try argv.append(zig_target);
    }
    while (args.next()) |arg| {
        try argv.append(arg);
    }

    // Execute the command.
    var proc = std.process.Child.init(argv.items, alloc);
    const term = try proc.spawnAndWait();
    return term.Exited;
}
