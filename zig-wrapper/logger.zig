const std = @import("std");
const builtin = @import("builtin");

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
