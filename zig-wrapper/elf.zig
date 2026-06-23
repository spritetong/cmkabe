//! ELF Dynamic Library Path Fixer Module
//!
//! This module provides capabilities to parse and modify ELF files in-place.
//! It is used to remove directory paths from dynamic library dependencies (`DT_NEEDED`)
//! and RPATH/RUNPATH entries, keeping only the filenames or filtering directory prefixes.
//!
//! Ported from `elf_path_fixer.py` to native Zig for performance and dependency reduction.

const std = @import("std");
const builtin = @import("builtin");
const utils = @import("utils.zig");
const mvzr = @import("mvzr.zig");

/// Represents an entry in the ELF Dynamic Section (`.dynamic`)
pub const DynEntry = struct {
    tag: i64,
    val: u64,
};

/// Represents a library dependency (`DT_NEEDED`) found in the ELF file
pub const NeededLib = struct {
    name: []const u8,
    offset: u64, // Offset in the dynamic string table
};

/// Represents a library search path entry (`DT_RPATH` or `DT_RUNPATH`)
pub const PathEntry = struct {
    path: []const u8,
    offset: u64, // Offset in the dynamic string table
    tag: i64, // DT_RPATH (15) or DT_RUNPATH (29)
};

/// Represents a library name modification plan
pub const ModifiedLib = struct {
    old_lib: []const u8,
    new_lib: []const u8,
    offset: u64,
};

/// Represents a library search path modification plan
pub const ModifiedPath = struct {
    old_path: []const u8,
    new_path: []const u8,
    offset: u64,
};

/// Pure Zig ELF file parser
pub const ElfParser = struct {
    const Self = @This();

    allocator: std.mem.Allocator,
    io: std.Io,
    file_path: []const u8,
    file: std.Io.File,
    endian: std.builtin.Endian,
    is_64: bool,
    strtab_offset: u64,
    strtab_size: u64,
    dynamic_section: std.array_list.Managed(DynEntry),
    string_table: []u8,

    /// Initialize the ELF parser, opening the file and parsing its headers
    pub fn init(allocator: std.mem.Allocator, io: std.Io, file_path: []const u8) !Self {
        const cwd = std.Io.Dir.cwd();
        var file = try cwd.openFile(io, file_path, .{});
        errdefer file.close(io);

        var self = Self{
            .allocator = allocator,
            .io = io,
            .file_path = file_path,
            .file = file,
            .endian = .little,
            .is_64 = true,
            .strtab_offset = 0,
            .strtab_size = 0,
            .dynamic_section = std.array_list.Managed(DynEntry).init(allocator),
            .string_table = &.{},
        };
        errdefer {
            self.dynamic_section.deinit();
            if (self.string_table.len > 0) {
                self.allocator.free(self.string_table);
            }
        }

        try self.parseElfHeader();
        try self.findDynamicSection();
        try self.loadStringTable();

        return self;
    }

    /// Free resources allocated by the parser
    pub fn deinit(self: *Self) void {
        self.file.close(self.io);
        self.dynamic_section.deinit();
        if (self.string_table.len > 0) {
            self.allocator.free(self.string_table);
        }
    }

    /// Parse the ELF identification header to detect bitness (32 vs 64-bit) and endianness
    fn parseElfHeader(self: *Self) !void {
        var magic: [4]u8 = undefined;
        _ = try self.file.readPositionalAll(self.io, &magic, 0);
        if (!std.mem.eql(u8, &magic, "\x7fELF")) {
            return error.InvalidElfMagic;
        }

        // EI_CLASS (Offset 4): 1 = 32-bit, 2 = 64-bit
        var ei_class: [1]u8 = undefined;
        _ = try self.file.readPositionalAll(self.io, &ei_class, 4);
        self.is_64 = (ei_class[0] == 2);

        // EI_DATA (Offset 5): 1 = Little endian, 2 = Big endian
        var ei_data: [1]u8 = undefined;
        _ = try self.file.readPositionalAll(self.io, &ei_data, 5);
        self.endian = if (ei_data[0] == 2) .big else .little;
    }

    /// Read a file offset (4 bytes for 32-bit, 8 bytes for 64-bit) at the given file address
    fn readOffset(self: *Self, offset: u64) !u64 {
        if (self.is_64) {
            return try self.readInt(u64, offset);
        } else {
            return try self.readInt(u32, offset);
        }
    }

    /// Read an integer of type `T` from the specified offset, respecting ELF endianness
    fn readInt(self: *Self, comptime T: type, offset: u64) !T {
        const size = @sizeOf(T);
        var bytes: [size]u8 = undefined;
        _ = try self.file.readPositionalAll(self.io, &bytes, offset);
        return std.mem.readInt(T, &bytes, self.endian);
    }

    /// Traverse section headers to find the SHT_DYNAMIC section, then parse all dynamic entries
    fn findDynamicSection(self: *Self) !void {
        // e_shoff, e_shentsize, e_shnum offsets differ between 32 and 64-bit headers
        const e_shoff = try self.readOffset(if (self.is_64) @as(u64, 40) else @as(u64, 32));
        const e_shentsize = try self.readInt(u16, if (self.is_64) @as(u64, 58) else @as(u64, 46));
        const e_shnum = try self.readInt(u16, if (self.is_64) @as(u64, 60) else @as(u64, 48));

        var i: usize = 0;
        while (i < e_shnum) : (i += 1) {
            const sh_addr = e_shoff + (i * e_shentsize);
            const sh_type = try self.readInt(u32, sh_addr + 4);

            // 6 = SHT_DYNAMIC
            if (sh_type == 6) {
                const offset_pos = sh_addr + (if (self.is_64) @as(u64, 24) else @as(u64, 16));
                const sh_offset = try self.readOffset(offset_pos);
                const sh_size = try self.readOffset(offset_pos + (if (self.is_64) @as(u64, 8) else @as(u64, 4)));

                const entry_size: u64 = if (self.is_64) @as(u64, 16) else @as(u64, 8);
                const num_entries = sh_size / entry_size;

                // Read all dynamic entries and identify the string table location/size
                var j: usize = 0;
                while (j < num_entries) : (j += 1) {
                    const entry_addr = sh_offset + (j * entry_size);
                    const tag: i64 = if (self.is_64)
                        try self.readInt(i64, entry_addr)
                    else
                        try self.readInt(i32, entry_addr);
                    const val: u64 = if (self.is_64)
                        try self.readInt(u64, entry_addr + 8)
                    else
                        try self.readInt(u32, entry_addr + 4);

                    try self.dynamic_section.append(.{
                        .tag = tag,
                        .val = val,
                    });

                    if (tag == 5) { // DT_STRTAB
                        self.strtab_offset = val;
                    } else if (tag == 10) { // DT_STRSZ
                        self.strtab_size = val;
                    }
                }
                break;
            }
        }
    }

    /// Load the dynamic string table content into memory
    fn loadStringTable(self: *Self) !void {
        if (self.strtab_offset != 0 and self.strtab_size != 0) {
            self.string_table = try self.allocator.alloc(u8, self.strtab_size);
            _ = try self.file.readPositionalAll(self.io, self.string_table, self.strtab_offset);
        }
    }

    /// Retrieve a null-terminated UTF-8 string from the string table at the specified offset
    pub fn getString(self: Self, offset: u64) ?[]const u8 {
        if (self.string_table.len == 0 or offset >= self.string_table.len) {
            return null;
        }
        const start = @as(usize, @intCast(offset));
        var end = start;
        while (end < self.string_table.len) : (end += 1) {
            if (self.string_table[end] == 0) {
                return self.string_table[start..end];
            }
        }
        return null;
    }

    /// Collect all library dependencies (`DT_NEEDED` entries) with their details
    pub fn getNeededLibraries(self: Self, allocator: std.mem.Allocator) ![]NeededLib {
        var list = std.array_list.Managed(NeededLib).init(allocator);
        errdefer list.deinit();

        for (self.dynamic_section.items) |entry| {
            if (entry.tag == 1) { // DT_NEEDED
                if (self.getString(entry.val)) |name| {
                    try list.append(.{
                        .name = name,
                        .offset = entry.val,
                    });
                }
            }
        }
        return list.toOwnedSlice();
    }

    /// Collect all library search paths (`DT_RPATH` / `DT_RUNPATH` entries)
    pub fn getRpathRunpath(self: Self, allocator: std.mem.Allocator) ![]PathEntry {
        var list = std.array_list.Managed(PathEntry).init(allocator);
        errdefer list.deinit();

        for (self.dynamic_section.items) |entry| {
            if (entry.tag == 15 or entry.tag == 29) { // DT_RPATH or DT_RUNPATH
                if (self.getString(entry.val)) |path| {
                    try list.append(.{
                        .path = path,
                        .offset = entry.val,
                        .tag = entry.tag,
                    });
                }
            }
        }
        return list.toOwnedSlice();
    }
};

/// Compile the regex pattern and test if it matches the text using `mvzr`
pub fn matchPattern(pattern: []const u8, text: []const u8) bool {
    const re = mvzr.compile(pattern) orelse return false;
    return re.isMatch(text);
}

/// Helper function to log informational messages
fn printInfo(io: std.Io, quiet: bool, is_verbose_msg: bool, comptime fmt: []const u8, args: anytype) void {
    if (is_verbose_msg or (!quiet and !is_verbose_msg)) {
        const file = std.Io.File.stdout();
        var buf: [1024]u8 = undefined;
        const msg = std.fmt.bufPrint(&buf, "[INFO] " ++ fmt ++ "\n", args) catch return;
        file.writeStreamingAll(io, msg) catch {};
    }
}

/// Helper function to log error messages to stderr
fn printError(io: std.Io, quiet: bool, comptime fmt: []const u8, args: anytype) void {
    if (!quiet) {
        const file = std.Io.File.stderr();
        var buf: [1024]u8 = undefined;
        const msg = std.fmt.bufPrint(&buf, "[ERROR] " ++ fmt ++ "\n", args) catch return;
        file.writeStreamingAll(io, msg) catch {};
    }
}

/// Modify the ELF file to strip directories matching target patterns from library names and search paths
pub fn modifyElfFile(
    allocator: std.mem.Allocator,
    io: std.Io,
    elf_path: []const u8,
    target_patterns: []const []const u8,
    fix_rpath: bool,
    create_backup: bool,
    verbose: bool,
    quiet: bool,
) !bool {
    // 1. Open the file and parse ELF structures
    var parser = ElfParser.init(allocator, io, elf_path) catch |err| {
        printError(io, quiet, "Failed to parse ELF file: {}", .{err});
        return false;
    };
    defer parser.deinit();

    const needed_libs = try parser.getNeededLibraries(allocator);
    defer allocator.free(needed_libs);

    const paths = try parser.getRpathRunpath(allocator);
    defer allocator.free(paths);

    {
        var buf: [512]u8 = undefined;
        const msg = std.fmt.bufPrint(&buf, "Found {d} dynamic libraries in {s}", .{ needed_libs.len, elf_path }) catch "";
        printInfo(io, quiet, false, "{s}", .{msg});
    }
    for (needed_libs) |lib| {
        printInfo(io, quiet, verbose, "  - {s}", .{lib.name});
    }

    printInfo(io, quiet, false, "Found {d} RUNPATH/RPATH entries", .{paths.len});
    for (paths) |path| {
        printInfo(io, quiet, verbose, "  - {s}", .{path.path});
    }

    // 2. Identify libraries that match target patterns and plan replacements
    var modified_libs = std.array_list.Managed(ModifiedLib).init(allocator);
    defer {
        for (modified_libs.items) |ml| {
            allocator.free(ml.old_lib);
            allocator.free(ml.new_lib);
        }
        modified_libs.deinit();
    }

    for (needed_libs) |lib| {
        var matched = false;
        for (target_patterns) |pat| {
            if (matchPattern(pat, lib.name)) {
                matched = true;
                break;
            }
        }
        if (matched) {
            const basename = std.fs.path.basename(lib.name);
            const old_lib = try allocator.dupe(u8, lib.name);
            errdefer allocator.free(old_lib);
            const new_lib = try allocator.dupe(u8, basename);
            errdefer allocator.free(new_lib);

            try modified_libs.append(.{
                .old_lib = old_lib,
                .new_lib = new_lib,
                .offset = lib.offset,
            });
        }
    }

    // 3. Identify path search lists matching target patterns and plan replacements
    var modified_paths = std.array_list.Managed(ModifiedPath).init(allocator);
    defer {
        for (modified_paths.items) |mp| {
            allocator.free(mp.old_path);
            allocator.free(mp.new_path);
        }
        modified_paths.deinit();
    }

    for (paths) |path| {
        var matched = false;
        for (target_patterns) |pat| {
            if (matchPattern(pat, path.path)) {
                matched = true;
                break;
            }
        }
        if (fix_rpath and matched) {
            var new_paths = std.array_list.Managed([]const u8).init(allocator);
            defer new_paths.deinit();

            var iter = std.mem.splitScalar(u8, path.path, ':');
            while (iter.next()) |p| {
                var p_matched = false;
                for (target_patterns) |pat| {
                    if (matchPattern(pat, p)) {
                        p_matched = true;
                        break;
                    }
                }
                if (p_matched) {
                    printInfo(io, quiet, false, "  Removing directory path from: {s}", .{p});
                } else {
                    try new_paths.append(p);
                }
            }

            const joined = try std.mem.join(allocator, ":", new_paths.items);
            errdefer allocator.free(joined);
            const old_path = try allocator.dupe(u8, path.path);
            errdefer allocator.free(old_path);

            try modified_paths.append(.{
                .old_path = old_path,
                .new_path = joined,
                .offset = path.offset,
            });
        }
    }

    // 4. Return immediately if no modifications are required
    if (modified_libs.items.len == 0 and modified_paths.items.len == 0) {
        printInfo(io, quiet, false, "No modifications needed", .{});
        return true;
    }

    const cwd = std.Io.Dir.cwd();

    // 5. Perform backup copying if backup requested
    const use_temp = create_backup;
    var temp_path: ?[]const u8 = null;
    defer if (temp_path) |tp| allocator.free(tp);

    if (create_backup) {
        const backup_path = try std.fmt.allocPrint(allocator, "{s}.backup", .{elf_path});
        defer allocator.free(backup_path);

        temp_path = try std.fmt.allocPrint(allocator, "{s}.tmp", .{elf_path});
        printInfo(io, quiet, false, "Creating temporary copy for backup", .{});
        try cwd.copyFile(elf_path, cwd, temp_path.?, io, .{});

        printInfo(io, quiet, false, "Creating backup at {s}", .{backup_path});
        try cwd.copyFile(elf_path, cwd, backup_path, io, .{});
    }

    const file_to_modify = if (use_temp) temp_path.? else elf_path;

    errdefer {
        if (use_temp) {
            if (temp_path) |tp| {
                cwd.deleteFile(io, tp) catch {};
            }
        }
    }

    // 6. Open the file to modify in read+write mode
    var opt_f: ?std.Io.File = try cwd.createFile(io, file_to_modify, .{
        .read = true,
        .truncate = false,
    });
    defer if (opt_f) |*file| {
        file.close(io);
    };

    // 7. Apply library name replacements
    for (modified_libs.items) |ml| {
        const abs_offset = parser.strtab_offset + ml.offset;

        // Verify the original string in the file matches our expectation
        const actual_bytes = try allocator.alloc(u8, ml.old_lib.len);
        defer allocator.free(actual_bytes);
        _ = try opt_f.?.readPositionalAll(io, actual_bytes, abs_offset);

        if (!std.mem.eql(u8, actual_bytes, ml.old_lib)) {
            printError(io, quiet, "Verification failed: Expected '{s}' but found '{s}' at offset {d}", .{ ml.old_lib, actual_bytes, abs_offset });
            continue;
        }

        printInfo(io, quiet, false, "Replacing {s} with {s}", .{ ml.old_lib, ml.new_lib });

        if (ml.new_lib.len > ml.old_lib.len) {
            printError(io, quiet, "New library name is longer than old name, cannot replace in-place", .{});
            continue;
        }

        // Write the new library name followed by null terminator, keeping length padded with zeros
        var write_buf = try allocator.alloc(u8, ml.old_lib.len + 1);
        defer allocator.free(write_buf);
        @memset(write_buf, 0);
        @memcpy(write_buf[0..ml.new_lib.len], ml.new_lib);

        try opt_f.?.writePositionalAll(io, write_buf, abs_offset);
    }

    // 8. Apply RPATH/RUNPATH replacements
    for (modified_paths.items) |mp| {
        const abs_offset = parser.strtab_offset + mp.offset;

        // Verify the original path string in the file matches our expectation
        const actual_bytes = try allocator.alloc(u8, mp.old_path.len);
        defer allocator.free(actual_bytes);
        _ = try opt_f.?.readPositionalAll(io, actual_bytes, abs_offset);

        if (!std.mem.eql(u8, actual_bytes, mp.old_path)) {
            printError(io, quiet, "Verification failed: Expected '{s}' but found '{s}' at offset {d}", .{ mp.old_path, actual_bytes, abs_offset });
            continue;
        }

        printInfo(io, quiet, false, "Replacing path {s} with {s}", .{ mp.old_path, mp.new_path });

        if (mp.new_path.len > mp.old_path.len) {
            printError(io, quiet, "New path is longer than old path, cannot replace in-place", .{});
            continue;
        }

        // Write the new path followed by null terminator, keeping length padded with zeros
        var write_buf = try allocator.alloc(u8, mp.old_path.len + 1);
        defer allocator.free(write_buf);
        @memset(write_buf, 0);
        @memcpy(write_buf[0..mp.new_path.len], mp.new_path);

        try opt_f.?.writePositionalAll(io, write_buf, abs_offset);
    }

    // Explicitly close before copying to prevent file locking/sharing issues on Windows
    if (opt_f) |*file| {
        file.close(io);
        opt_f = null;
    }

    // 9. Swap the temporary file back to original file if temporary file was used
    if (use_temp) {
        printInfo(io, quiet, false, "Updating {s} with modified version", .{elf_path});
        try cwd.copyFile(temp_path.?, cwd, elf_path, io, .{});
        try cwd.deleteFile(io, temp_path.?);
    }

    printInfo(io, quiet, false, "ELF file successfully updated", .{});
    return true;
}
