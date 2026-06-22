const std = @import("std");
const utils = @import("utils.zig");
const parser_mod = @import("parser.zig");
const SimpleOptionParser = parser_mod.SimpleOptionParser;
const main_mod = @import("main.zig");
const ZigWrapper = main_mod.ZigWrapper;

const StringArray = std.array_list.Managed([]const u8);

pub const ZigArgFilter = struct {
    const Self = @This();
    matchers: std.array_list.Managed(Matcher),
    replacers: std.array_list.Managed(Replacer),

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
        string: []const u8,
        /// { index, needle, replacement }
        arg_index: struct { usize, []const u8, []const u8 },
    };

    /// Options to query the compiler version only.
    pub const query_version_opts: []const []const u8 = &.{ "--help", "--version", "-version", "-qversion", "-V" };

    /// Options to compile source files only and not to run the linker.
    pub const compile_only_opts: []const []const u8 = &.{ "-c", "-E", "-S" };

    /// Define libraries that should be skipped only if they are not in library paths.
    pub const generic_weak_libs = std.StaticStringMap(void).initComptime(.{
        .{"atomic"},
        .{"omp"},
    });
    pub const windows_gnu_weak_libs = std.StaticStringMap(void).initComptime(.{
        .{"gcc"},
        .{"gcc_eh"},
        .{"msvcrt"},
        .{"msvcrtd"},
        .{"synchronization"},
    });

    pub fn initFilterMap(ctx: *ZigWrapper, map: *ZigArgFilterMap) void {
        if (ctx.command == .cc or ctx.command == .cxx) {
            // Linux system include paths
            map.initFilters("-I", 2).allowPartialOpt()
                .match("/usr/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().eof()
                .match("/usr/local/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().done();
            // MSVC
            map.initFilters("-Xlinker", 3)
                .match("/MANIFEST:EMBED").eof()
                .match("/version:0.0").eof()
                // CMake
                .next().match("--dependency-file=*").done();
            // CC
            map.initFilter("-std").command("cc").replaceWithSubString(0, "++", "").done();
            // GCC / Clang
            map.initFilter("-Werror").replaceWithArg(0).replaceWith(&.{"-Wno-error=date-time"}).done();
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
                // Fix LTO link errors from ZIG 0.16+
                if (ctx.is_linker) {
                    map.initFilter("-flto").done();
                }
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
            .matchers = std.array_list.Managed(Matcher).init(allocator),
            .replacers = std.array_list.Managed(Replacer).init(allocator),
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
        self.replacers.append(.{ .arg_index = .{ arg_index, "", "" } }) catch unreachable;
        return self;
    }

    pub fn replaceWithSubString(
        self: *Self,
        arg_index: usize,
        needle: []const u8,
        replacement: []const u8,
    ) *Self {
        self.replacers.append(.{ .arg_index = .{
            arg_index,
            needle,
            replacement,
        } }) catch unreachable;
        return self;
    }
};

pub const ZigArgFilterMap = struct {
    const Self = @This();
    allocator: std.mem.Allocator,
    map: std.array_hash_map.String(std.array_list.Managed(ZigArgFilter)),

    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .allocator = allocator,
            .map = .{},
        };
    }

    pub fn deinit(self: *Self) void {
        for (self.map.values()) |filters| {
            for (filters.items) |filter| {
                filter.deinit();
            }
            filters.deinit();
        }
        self.map.deinit(self.allocator);
    }

    pub inline fn initFilter(self: *Self, option: []const u8) *ZigArgFilter {
        return self.initFilters(option, 1);
    }

    pub fn initFilters(self: *Self, option: []const u8, count: usize) *ZigArgFilter {
        const entry = self.map.getPtr(option) orelse blk: {
            self.map.put(
                self.allocator,
                option,
                std.array_list.Managed(ZigArgFilter).init(self.allocator),
            ) catch unreachable;
            break :blk self.map.getPtr(option).?;
        };

        const start = entry.items.len;
        entry.ensureUnusedCapacity(count) catch unreachable;
        for (0..count) |_| {
            entry.appendAssumeCapacity(ZigArgFilter.init(self.allocator));
        }
        return &entry.items.ptr[start];
    }

    pub fn next(self: *Self, ctx: *ZigWrapper, input: *SimpleOptionParser, output: *StringArray) !?void {
        const opt = input.next() orelse return null;

        if (utils.strStartsWith(opt, "-")) {
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
                            if (utils.strStartsWith(pattern, "!")) {
                                return !utils.strMatch(pattern[1..], string);
                            } else {
                                return utils.strMatch(pattern, string);
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
                                if (!Matcher.call(pattern, ctx.zig_target.?)) {
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
                                    try output.append(try ctx.allocator.dupe(u8, opt_value));
                                }
                            },
                            .string => |str| {
                                try output.append(try ctx.allocator.dupe(u8, str));
                            },
                            .arg_index => |triple| {
                                const arg_index = triple[0];
                                const s = if (arg_index == 0)
                                    opt
                                else if (arg_index <= consumed)
                                    input.args[arg_index - 1]
                                else
                                    continue;
                                if (triple[1].len == 0) {
                                    try output.append(try ctx.allocator.dupe(u8, s));
                                } else {
                                    const replaced = try std.mem.replaceOwned(
                                        u8,
                                        ctx.allocator,
                                        s,
                                        triple[1],
                                        triple[2],
                                    );
                                    try output.append(replaced);
                                }
                            },
                        }
                    }
                    // consume the input arguments
                    input.advance(consumed);
                    return;
                }
            }
        }

        try output.append(try ctx.allocator.dupe(u8, opt));
        return;
    }
};
