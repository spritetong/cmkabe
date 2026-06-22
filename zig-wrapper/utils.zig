const std = @import("std");
const builtin = @import("builtin");

/// Check if `a` and `b` are equal.
pub inline fn strEql(a: []const u8, b: []const u8) bool {
    return std.mem.eql(u8, a, b);
}

/// Remove trailing whitespace from `s`.
pub inline fn strTrimEnd(s: []const u8) []const u8 {
    return std.mem.trimEnd(u8, s, " \t\r\n");
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

pub fn strEscapeAppend(buffer: *std.array_list.Managed(u8), string: []const u8) !void {
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

pub fn strMatch(pattern: []const u8, string: []const u8) bool {
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

pub fn sysArgMax() usize {
    if (builtin.os.tag == .windows) {
        return 32767;
    } else {
        const unistd = @import("c");
        return @intCast(unistd.sysconf(@intCast(unistd._SC_ARG_MAX)));
    }
}

pub fn getEnvVar(env_map: *const std.process.Environ.Map, allocator: std.mem.Allocator, key: []const u8) ![]u8 {
    const val = env_map.get(key) orelse return error.EnvironmentVariableNotFound;
    const s = strTrimEnd(val);
    if (s.len > 0) {
        return try allocator.dupe(u8, s);
    }
    return error.EnvironmentVariableNotFound;
}

pub fn freeStringArray(allocator: std.mem.Allocator, array: *std.array_list.Managed([]const u8)) void {
    for (array.items) |item| {
        allocator.free(item);
    }
    array.deinit();
}

pub fn freeStringSet(allocator: std.mem.Allocator, set: *std.array_hash_map.String(void)) void {
    for (set.keys()) |key| {
        allocator.free(key);
    }
    set.deinit(allocator);
}
