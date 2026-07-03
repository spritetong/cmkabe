const std = @import("std");
const utils = @import("utils.zig");
const parser_mod = @import("parser.zig");
const SimpleOptionParser = parser_mod.SimpleOptionParser;
const main_mod = @import("main.zig");
const ZigWrapper = main_mod.ZigWrapper;
const command_mod = @import("command.zig");
const ZigCommand = command_mod.ZigCommand;

const StringArray = std.array_list.Managed([]const u8);
const ZigArgFilterArray = std.array_list.Managed(ZigArgFilter);

pub const ZigArgFilter = struct {
    const Self = @This();
    pub const MAX_COMMANDS = 8;
    _container: ?*ZigArgFilterArray,
    matchers: std.array_list.Managed(Matcher),
    replacers: std.array_list.Managed(Replacer),

    pub const Matcher = union(enum) {
        allow_partial_opt: void,
        command: [MAX_COMMANDS]?ZigCommand,
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
    pub const query_version_opts: []const []const u8 = &.{
        "--help",
        "--version",
        "-version",
        "-qversion",
        "-dumpversion",
    };
    pub const compiler_query_version_opts: []const []const u8 = &.{
        "-V",
        "-v",
        "-verbose",
        "--verbose",
    };

    /// Options to search directories
    pub const search_dir_opts: []const []const u8 = &.{
        "-print-resource-dir",
        "-print-search-dirs",
        "-print-multi-os-directory",
    };

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
            map.initFilter("-I").allowPartialOpt()
                .match("/usr/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().eof()
                .match("/usr/local/include").replaceWith(&.{"-idirafter"}).replaceWithOptValue().done();
            // MSVC
            map.initFilter("-Xlinker")
                .match("/MANIFEST:EMBED").eof()
                .match("/version:0.0").eof()
                // CMake
                .next().match("--dependency-file=*").done();
            // CC
            map.initFilter("-std").command(&.{.cc}).replaceWithSubString(0, "++", "").done();
            // GCC / Clang
            map.initFilter("-Werror").replaceWithArg(0).replaceWith(&.{"-Wno-error=date-time"}).done();
            // -m <target>, unknown Clang option: '-m'
            map.initFilter("-m").match("*").done();
            // -version
            map.initFilter("-qversion").replaceWith(&.{"-version"}).done();
            map.initFilter("-V").replaceWith(&.{"-version"}).done();
            // -verbose
            map.initFilter("-verbose").replaceWith(&.{"-v"}).done();
            // -Wl,[...]
            map.initFilter("-Wl,")
                .match("-v").eof()
                .match("-x").replaceWith(&.{"-Wl,--strip-all"}).done();
            map.initFilter("-v").linker(true).done();
            // OpenMP
            map.initFilter("-fopenmp=libomp").linker(true).replaceWithArg(0).replaceWith(&.{"-lomp"}).done();
            // Autoconfig
            map.initFilter("-link").done();
            map.initFilter("-dll").replaceWith(&.{"-shared"}).done();
            // Invalid CPU types
            map.initFilter("-march")
                .target("x86_64*").match("i386").eof()
                .target("x86_64*").match("i586").eof()
                .target("x86_64*").match("i686").done();

            // Windows GNU
            if (ctx.target_is_windows and !ctx.target_is_msvc) {
                // -Wl,[...]
                map.initFilter("-Wl,")
                    .match("--disable-auto-image-base").eof()
                    .match("--enable-auto-image-base").eof()
                    .match("--add-stdcall-alias").done();
                map.initFilter("-l").allowPartialOpt()
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
        if (utils.getEnvVar(ctx.environ_map, "ZIG_WRAPPER_FILTERS")) |env_filters| {
            map.parseAndApplyEnvFilters(ctx, env_filters) catch |err| {
                std.debug.print("Failed to parse ZIG_WRAPPER_FILTERS: {}\n", .{err});
            };
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

    pub fn init(container: *ZigArgFilterArray) Self {
        return .{
            ._container = container,
            .matchers = std.array_list.Managed(Matcher).init(container.allocator),
            .replacers = std.array_list.Managed(Replacer).init(container.allocator),
        };
    }

    pub fn deinit(self: Self) void {
        self.matchers.deinit();
        self.replacers.deinit();
    }

    pub inline fn done(self: *Self) void {
        self._container = null;
    }

    /// Set the end of the current filter, and return the next one.
    pub inline fn eof(self: *Self) *Self {
        const container = self._container.?;
        self._container = null;
        container.append(ZigArgFilter.init(container)) catch unreachable;
        return &container.items.ptr[container.items.len - 1];
    }

    pub fn allowPartialOpt(self: *Self) *Self {
        self.matchers.append(.{ .allow_partial_opt = {} }) catch unreachable;
        return self;
    }

    pub fn target(self: *Self, pattern: []const u8) *Self {
        self.matchers.append(.{ .target = pattern }) catch unreachable;
        return self;
    }

    pub fn command(self: *Self, cmds: []const ZigCommand) *Self {
        var arr = [_]?ZigCommand{null} ** MAX_COMMANDS;
        for (cmds, 0..) |cmd, i| {
            if (i >= MAX_COMMANDS) break;
            arr[i] = cmd;
        }
        self.matchers.append(.{ .command = arr }) catch unreachable;
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
    map: std.array_hash_map.String(ZigArgFilterArray),

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

    pub fn parseAndApplyEnvFilters(self: *Self, _: *ZigWrapper, env_val: []const u8) !void {
        var rule_it = std.mem.tokenizeSequence(u8, env_val, ";");
        while (rule_it.next()) |rule| {
            const rule_trimmed = std.mem.trim(u8, rule, " \t\r\n");
            if (rule_trimmed.len == 0) continue;

            var left: []const u8 = rule_trimmed;
            var right: []const u8 = "";
            if (std.mem.indexOf(u8, rule_trimmed, "->")) |idx| {
                left = std.mem.trim(u8, rule_trimmed[0..idx], " \t\r\n");
                right = std.mem.trim(u8, rule_trimmed[idx + 2 ..], " \t\r\n");
            }

            var left_it = std.mem.tokenizeAny(u8, left, " \t");
            const option_token = left_it.next() orelse continue;
            const duped_option_key = try self.allocator.dupe(u8, option_token);

            const filter = self.initFilter(duped_option_key);
            errdefer filter.done();

            while (left_it.next()) |token| {
                if (std.mem.eql(u8, token, "partial")) {
                    _ = filter.allowPartialOpt();
                } else if (std.mem.startsWith(u8, token, "command:")) {
                    var cmds_buf: [ZigArgFilter.MAX_COMMANDS]ZigCommand = undefined;
                    var cmds_count: usize = 0;
                    var it = std.mem.splitScalar(u8, token[8..], ',');
                    while (it.next()) |cmd_str| {
                        if (cmds_count >= ZigArgFilter.MAX_COMMANDS) break;
                        if (ZigCommand.fromStr(cmd_str)) |cmd| {
                            cmds_buf[cmds_count] = cmd;
                            cmds_count += 1;
                        }
                    }
                    _ = filter.command(cmds_buf[0..cmds_count]);
                } else if (std.mem.startsWith(u8, token, "linker:")) {
                    const is_linker = std.mem.eql(u8, token[7..], "true");
                    _ = filter.linker(is_linker);
                } else if (std.mem.startsWith(u8, token, "target:")) {
                    const pattern = try self.allocator.dupe(u8, token[7..]);
                    _ = filter.target(pattern);
                } else if (std.mem.startsWith(u8, token, "match:")) {
                    const pattern = try self.allocator.dupe(u8, token[6..]);
                    _ = filter.match(pattern);
                } else if (std.mem.eql(u8, token, "next")) {
                    _ = filter.next();
                }
            }

            var right_it = std.mem.tokenizeAny(u8, right, " \t");
            while (right_it.next()) |token| {
                if (std.mem.eql(u8, token, "opt_val")) {
                    _ = filter.replaceWithOptValue();
                } else if (std.mem.startsWith(u8, token, "replace_arg:")) {
                    const idx = try std.fmt.parseInt(usize, token[12..], 10);
                    _ = filter.replaceWithArg(idx);
                } else if (std.mem.startsWith(u8, token, "replace_sub:")) {
                    var sub_it = std.mem.splitScalar(u8, token[12..], ':');
                    const idx_str = sub_it.next() orelse return error.InvalidSubst;
                    const needle = sub_it.next() orelse return error.InvalidSubst;
                    const replacement = sub_it.next() orelse return error.InvalidSubst;
                    const idx = try std.fmt.parseInt(usize, idx_str, 10);
                    _ = filter.replaceWithSubString(
                        idx,
                        try self.allocator.dupe(u8, needle),
                        try self.allocator.dupe(u8, replacement),
                    );
                } else {
                    const duped_token = try self.allocator.dupe(u8, token);
                    try filter.replacers.append(.{ .string = duped_token });
                }
            }
            filter.done();
        }
    }

    pub fn initFilter(self: *Self, option: []const u8) *ZigArgFilter {
        const entry = self.map.getPtr(option) orelse blk: {
            self.map.put(
                self.allocator,
                option,
                ZigArgFilterArray.init(self.allocator),
            ) catch unreachable;
            break :blk self.map.getPtr(option).?;
        };

        if (entry.items.len == 0) {
            entry.ensureUnusedCapacity(8) catch unreachable;
        }
        entry.append(ZigArgFilter.init(entry)) catch unreachable;
        return &entry.items.ptr[entry.items.len - 1];
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
                            .command => |cmds| {
                                var matched = false;
                                for (cmds) |cmd| {
                                    if (cmd) |c| {
                                        if (c == ctx.command) {
                                            matched = true;
                                            break;
                                        }
                                    } else {
                                        break;
                                    }
                                }
                                if (!matched) {
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
                                    try utils.dupeAndAppend(u8, output, ctx.allocator, opt_value);
                                }
                            },
                            .string => |str| {
                                try utils.dupeAndAppend(u8, output, ctx.allocator, str);
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
                                    try utils.dupeAndAppend(u8, output, ctx.allocator, s);
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

        try utils.dupeAndAppend(u8, output, ctx.allocator, opt);
        return;
    }
};
