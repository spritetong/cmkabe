const std = @import("std");
const builtin = @import("builtin");

pub const ZigLog = struct {
    const Self = @This();
    io: std.Io,
    file: ?std.Io.File,
    pos: u64,

    pub fn init(io: std.Io, path_: ?[]const u8) !Self {
        if (path_) |path| {
            const cwd = std.Io.Dir.cwd();
            if (cwd.createFile(io, path, .{
                .read = true,
                .truncate = false,
            })) |file| {
                errdefer file.close(io);

                // Lock file.
                try file.lock(io, .exclusive);

                const pos = file.length(io) catch 0;

                return .{ .io = io, .file = file, .pos = pos };
            } else |_| {}
        }
        return .{ .io = io, .file = null, .pos = 0 };
    }

    pub fn deinit(self: *Self) void {
        if (self.file) |file| {
            file.sync(self.io) catch {};
            file.unlock(self.io);
            file.close(self.io);
            self.file = null;
        }
    }

    pub fn enabled(self: *Self) bool {
        return self.file != null;
    }

    pub fn write(self: *Self, bytes: []const u8) void {
        if (self.file) |file| {
            file.writePositionalAll(self.io, bytes, self.pos) catch {};
            self.pos += bytes.len;
        }
    }

    pub fn print(self: *Self, comptime fmt: []const u8, args: anytype) void {
        if (self.file) |file| {
            var large_buf: [4096]u8 = undefined;
            const s = std.fmt.bufPrint(&large_buf, fmt, args) catch return;
            file.writePositionalAll(self.io, s, self.pos) catch {};
            self.pos += s.len;
        }
    }
};

pub const TempFile = struct {
    const Self = @This();
    io: std.Io,
    file: ?std.Io.File,
    _path: std.array_list.Managed(u8),
    pos: u64,

    pub fn init(io: std.Io, a: std.mem.Allocator, env_map: *const std.process.Environ.Map) !Self {
        const chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789";

        const tmp_dir = try Self.getSysTmpDir(a, env_map);
        defer a.free(tmp_dir);

        var path = try std.array_list.Managed(u8).initCapacity(a, tmp_dir.len + 32);
        errdefer path.deinit();
        path.appendSlice(tmp_dir) catch unreachable;
        path.append(std.fs.path.sep) catch unreachable;
        path.appendSlice("zig-wrapper") catch unreachable;

        // Create the `zig-wrapper` directory in the `tmp` dir.
        const cwd = std.Io.Dir.cwd();
        try cwd.createDirPath(io, path.items);
        path.append(std.fs.path.sep) catch unreachable;
        const dir_len = path.items.len;

        var rand_bytes: [10]u8 = undefined;
        while (true) {
            path.resize(dir_len) catch unreachable;
            io.random(&rand_bytes);
            for (rand_bytes) |b| {
                const index = b % chars.len;
                path.append(chars[index]) catch unreachable;
            }
            path.appendSlice(".tmp") catch unreachable;

            // Check file existence.
            const file = cwd.createFile(io, path.items, .{
                .exclusive = true,
            }) catch |err| switch (err) {
                error.PathAlreadyExists => continue,
                else => |e| return e,
            };
            return .{ .io = io, .file = file, ._path = path, .pos = 0 };
        }
    }

    pub fn deinit(self: *Self) void {
        self.close();
        std.Io.Dir.cwd().deleteFile(self.io, self.getPath()) catch {};
        self._path.deinit();
    }

    pub fn close(self: *Self) void {
        if (self.file) |file| {
            file.close(self.io);
            self.file = null;
        }
    }

    pub inline fn getPath(self: *Self) []const u8 {
        return self._path.items;
    }

    pub fn write(self: *Self, bytes: []const u8) !void {
        if (self.file) |file| {
            try file.writePositionalAll(self.io, bytes, self.pos);
            self.pos += bytes.len;
        }
    }

    fn getSysTmpDir(a: std.mem.Allocator, env_map: *const std.process.Environ.Map) ![]const u8 {
        if (env_map.get("TMPDIR")) |val| return a.dupe(u8, val);
        if (env_map.get("TMP")) |val| return a.dupe(u8, val);
        if (env_map.get("TEMP")) |val| return a.dupe(u8, val);
        if (env_map.get("TEMPDIR")) |val| return a.dupe(u8, val);
        return a.dupe(u8, if (builtin.os.tag == .windows) "." else "/tmp");
    }
};
