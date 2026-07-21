// Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
//
// This software is under the MIT License
// https://github.com/spritetong/cmkabe

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

    pub const ReplaceStep = union(enum) {
        sub_string: struct { []const u8, []const u8 }, // needle, replacement
        regex: struct { []const u8, []const u8 }, // pattern, replacement
    };

    pub const Replacer = union(enum) {
        opt_value: void,
        string: []const u8,
        /// { index, needle, replacement }
        arg_index: struct { usize, []const u8, []const u8 },
        arg_chained_replace: struct {
            arg_index: usize,
            steps: std.array_list.Managed(ReplaceStep),
        },
    };

    /// Options to query the compiler version only.
    pub const query_version_opts: []const []const u8 = &.{
        "--help",
        "--version",
        "-version",
        "-qversion",
        "-dumpversion",
        "-?",
    };
    pub const compiler_query_version_opts: []const []const u8 = &.{
        "-V",
        "-v",
        "-verbose",
        "--verbose",
        "-nologo-",
        "-nologo",
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

    /// Fix MSVC-style built-in options in non-MSVC Windows targets
    pub const windows_gnu_builtin_opts: []const []const u8 = &.{};

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
                .match("--dependency-file=*").done();
            // CC
            map.initFilter("-std").command(&.{.cc}).replaceWithSubString(0, "++", "").done();
            // GCC / Clang
            map.initFilter("-Werror").replaceWithArg(0).replaceWith(&.{"-Wno-error=date-time"}).done();
            // -m <target>, unknown Clang option: '-m'
            map.initFilter("-m").match("*").done();
            // -Wa,[...]
            map.initFilter("-Wa,")
                .match("--debug-prefix-map=*").done();
            // -Wl,[...]
            map.initFilter("-Wl,")
                .match("-v").eof()
                .match("-x").replaceWith(&.{"-Wl,--strip-all"}).done();
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
            // Fix `aarch64` architucture
            map.initFilter("-march")
                .match("armv8.5-a*").replaceWithSubString(0, "armv8.5-a", "apple-a14").eof()
                .match("armv8.4-a*").replaceWithSubString(0, "armv8.4-a", "apple-a13").eof()
                .match("armv8.3-a*").replaceWithSubString(0, "armv8.3-a", "apple-a12").eof()
                .match("armv8.2-a*").replaceWithSubString(0, "armv8.2-a", "cortex-a55").eof()
                .match("armv8.1-a*").replaceWithSubString(0, "armv8.1-a", "cortex-a53").eof()
                .match("armv8.0-a*").replaceWithSubString(0, "armv8.0-a", "cortex-a53").eof()
                .match("armv8-a*").replaceWithSubString(0, "armv8-a", "generic").eof()
                .match("armv8*").replaceWithSubString(0, "armv8", "generic").eof()
                .match("armv9.2-a*").replaceWithSubString(0, "armv9.2-a", "cortex-a725").eof()
                .match("armv9.1-a*").replaceWithSubString(0, "armv9.1-a", "cortex-a715").eof()
                .match("armv9.0-a*").replaceWithSubString(0, "armv9.0-a", "cortex-a710").eof()
                .match("armv9-a*").replaceWithSubString(0, "armv9-a", "cortex-a710").eof()
                .match("armv9*").replaceWithSubString(0, "armv9", "cortex-a710").done();

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

            // zig: warning: argument unused during preprocessing
            if (ctx.is_preprocessor) {
                map.initFilter("-fms-compatibility-version").done();
                map.initFilter("-fno-sanitize").done();
                map.initFilter("-fvisibility-ms-compat").done();
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

    pub fn init(container: *ZigArgFilterArray) Self {
        return .{
            ._container = container,
            .matchers = std.array_list.Managed(Matcher).init(container.allocator),
            .replacers = std.array_list.Managed(Replacer).init(container.allocator),
        };
    }

    pub fn deinit(self: Self) void {
        self.matchers.deinit();
        for (self.replacers.items) |replacer| {
            switch (replacer) {
                .arg_chained_replace => |*chained| {
                    chained.steps.deinit();
                },
                else => {},
            }
        }
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

    pub fn replaceWithChained(self: *Self, arg_index: usize) *Self {
        const steps = std.array_list.Managed(ReplaceStep).init(self.replacers.allocator);
        self.replacers.append(.{ .arg_chained_replace = .{
            .arg_index = arg_index,
            .steps = steps,
        } }) catch unreachable;
        return self;
    }

    pub fn addRegexStep(self: *Self, pattern: []const u8, replacement: []const u8) *Self {
        const last = &self.replacers.items[self.replacers.items.len - 1];
        switch (last.*) {
            .arg_chained_replace => |*chained| {
                chained.steps.append(.{ .regex = .{ pattern, replacement } }) catch unreachable;
            },
            else => unreachable,
        }
        return self;
    }

    pub fn addSubStringStep(self: *Self, needle: []const u8, replacement: []const u8) *Self {
        const last = &self.replacers.items[self.replacers.items.len - 1];
        switch (last.*) {
            .arg_chained_replace => |*chained| {
                chained.steps.append(.{ .sub_string = .{ needle, replacement } }) catch unreachable;
            },
            else => unreachable,
        }
        return self;
    }
};

pub const ZigArgFilterMap = struct {
    const Self = @This();
    allocator: std.mem.Allocator,
    map: std.array_hash_map.String(ZigArgFilterArray),
    allocations: std.array_list.Managed([]const u8),

    pub fn init(allocator: std.mem.Allocator) Self {
        return .{
            .allocator = allocator,
            .map = .{},
            .allocations = std.array_list.Managed([]const u8).init(allocator),
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
        for (self.allocations.items) |slice| {
            self.allocator.free(slice);
        }
        self.allocations.deinit();
    }

    pub fn dupeAndTrack(self: *Self, string: []const u8) ![]const u8 {
        const duped = try self.allocator.dupe(u8, string);
        errdefer self.allocator.free(duped);
        try self.allocations.append(duped);
        return duped;
    }

    pub fn parseAndApply(self: *Self, _: *ZigWrapper, env_val: []const u8) !void {
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
            const duped_option_key = try self.dupeAndTrack(option_token);

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
                    const pattern = try self.dupeAndTrack(token[7..]);
                    _ = filter.target(pattern);
                } else if (std.mem.startsWith(u8, token, "match:")) {
                    const pattern = try self.dupeAndTrack(token[6..]);
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
                        try self.dupeAndTrack(needle),
                        try self.dupeAndTrack(replacement),
                    );
                } else if (std.mem.startsWith(u8, token, "replace_chain:")) {
                    const idx = try std.fmt.parseInt(usize, token[14..], 10);
                    _ = filter.replaceWithChained(idx);
                } else if (std.mem.startsWith(u8, token, "step_sub:")) {
                    var sub_it = std.mem.splitScalar(u8, token[9..], ':');
                    const needle = sub_it.next() orelse return error.InvalidSubst;
                    const replacement = sub_it.next() orelse return error.InvalidSubst;
                    _ = filter.addSubStringStep(
                        try self.dupeAndTrack(needle),
                        try self.dupeAndTrack(replacement),
                    );
                } else if (std.mem.startsWith(u8, token, "step_re:")) {
                    var re_it = std.mem.splitScalar(u8, token[8..], ':');
                    const pattern = re_it.next() orelse return error.InvalidSubst;
                    const replacement = re_it.next() orelse return error.InvalidSubst;
                    _ = filter.addRegexStep(
                        try self.dupeAndTrack(pattern),
                        try self.dupeAndTrack(replacement),
                    );
                } else {
                    const duped_token = try self.dupeAndTrack(token);
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
                var opt_value_init: []const u8 = undefined;
                var opt_value_valid_init = false;
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
                                opt_value_init = opt[i + 1 ..];
                                opt_value_valid_init = true;
                                break :blk v.items;
                            }
                        },
                        2 => if (std.mem.indexOf(u8, opt, ",")) |i| {
                            // match [-|--]<key>,<value>
                            if (self.map.getPtr(opt[0 .. i + 1])) |v| {
                                opt_value_init = opt[i + 1 ..];
                                opt_value_valid_init = true;
                                break :blk v.items;
                            }
                        },
                        3 => if (opt.len > 2 and opt[1] != '-') {
                            // match -<letter><value>
                            if (self.map.getPtr(opt[0..2])) |v| {
                                opt_value_init = opt[2..];
                                opt_value_valid_init = true;
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
                    var opt_value = opt_value_init;
                    var opt_value_valid = opt_value_valid_init;

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
                            .arg_chained_replace => |chained| {
                                const arg_index = chained.arg_index;
                                const s = if (arg_index == 0)
                                    opt
                                else if (arg_index <= consumed)
                                    input.args[arg_index - 1]
                                else
                                    continue;
                                var current_str: []const u8 = try ctx.allocator.dupe(u8, s);
                                errdefer ctx.allocator.free(current_str);

                                for (chained.steps.items) |step| {
                                    switch (step) {
                                        .sub_string => |pair| {
                                            const next_str = try std.mem.replaceOwned(
                                                u8,
                                                ctx.allocator,
                                                current_str,
                                                pair[0],
                                                pair[1],
                                            );
                                            ctx.allocator.free(current_str);
                                            current_str = next_str;
                                        },
                                        .regex => |pair| {
                                            const next_str = try utils.reReplace(
                                                ctx.allocator,
                                                current_str,
                                                pair[0],
                                                pair[1],
                                            );
                                            ctx.allocator.free(current_str);
                                            current_str = next_str;
                                        },
                                    }
                                }
                                try output.append(current_str);
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

test "regex replace and chained replace" {
    const allocator = std.testing.allocator;

    // Test reReplace directly
    {
        const result = try utils.reReplace(allocator, "foo123bar456", "[0-9]+", "X");
        defer allocator.free(result);
        try std.testing.expectEqualStrings("fooXbarX", result);
    }

    // Test filter builder and execution with chained replace
    {
        var map = ZigArgFilterMap.init(allocator);
        defer map.deinit();

        var filter = map.initFilter("-march");
        _ = filter.replaceWithChained(0)
            .addRegexStep("[0-9]+", "X")
            .addSubStringStep("foo", "baz");
        filter.done();

        var output = StringArray.init(allocator);
        defer utils.freeStringArray(allocator, &output);

        var input = SimpleOptionParser{ .args = &.{"-march=foo123"} };
        var ctx: ZigWrapper = undefined;
        ctx.allocator = allocator;
        _ = try map.next(&ctx, &input, &output);

        try std.testing.expectEqual(@as(usize, 1), output.items.len);
        try std.testing.expectEqualStrings("-march=bazX", output.items[0]);
    }

    // Test parseAndApply with chained/regex steps
    {
        var map = ZigArgFilterMap.init(allocator);
        defer map.deinit();

        var ctx: ZigWrapper = undefined;
        ctx.allocator = allocator;

        try map.parseAndApply(&ctx, "-march -> replace_chain:0 step_re:[0-9]+:Y step_sub:abc:def");

        var output = StringArray.init(allocator);
        defer utils.freeStringArray(allocator, &output);

        var input = SimpleOptionParser{ .args = &.{"-march=abc123abc"} };
        _ = try map.next(&ctx, &input, &output);

        try std.testing.expectEqual(@as(usize, 1), output.items.len);
        try std.testing.expectEqualStrings("-march=defYdef", output.items[0]);
    }

    // Test filtering -Xlinker /version:0.0
    {
        var map = ZigArgFilterMap.init(allocator);
        defer map.deinit();

        var ctx: ZigWrapper = undefined;
        ctx.allocator = allocator;
        ctx.command = .cc;

        map.initFilter("-Xlinker")
            .match("/MANIFEST:EMBED").eof()
            .match("/version:0.0").eof()
            .match("--dependency-file=*").done();

        var output = StringArray.init(allocator);
        defer utils.freeStringArray(allocator, &output);

        var input = SimpleOptionParser{ .args = &.{ "-Xlinker", "/version:0.0" } };
        _ = try map.next(&ctx, &input, &output);

        try std.testing.expectEqual(@as(usize, 0), output.items.len);
        try std.testing.expectEqual(@as(usize, 0), input.args.len);
    }
}

test "comprehensive initFilterMap rules" {
    const allocator = std.testing.allocator;

    const Helper = struct {
        fn check(
            alloc: std.mem.Allocator,
            cmd: ZigCommand,
            is_lnk: bool,
            is_prep: bool,
            tgt: []const u8,
            args: []const []const u8,
            expected: []const []const u8,
        ) !void {
            var map = ZigArgFilterMap.init(alloc);
            defer map.deinit();

            var ctx: ZigWrapper = undefined;
            ctx.allocator = alloc;
            ctx.command = cmd;
            ctx.is_linker = is_lnk;
            ctx.is_preprocessor = is_prep;
            ctx.zig_target = tgt;
            ctx.clang_target = tgt;
            ctx.target_is_windows = std.mem.indexOf(u8, tgt, "-windows") != null;

            ZigArgFilter.initFilterMap(&ctx, &map);

            var input = SimpleOptionParser{ .args = args };
            var output = StringArray.init(alloc);
            defer utils.freeStringArray(alloc, &output);

            while (input.hasArgument()) {
                _ = try map.next(&ctx, &input, &output);
            }

            try std.testing.expectEqual(expected.len, output.items.len);
            for (expected, 0..) |exp_str, i| {
                try std.testing.expectEqualStrings(exp_str, output.items[i]);
            }
        }
    };

    // 1. Linux include paths
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-I/usr/include"}, &.{ "-idirafter", "/usr/include" });
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-I/usr/local/include"}, &.{ "-idirafter", "/usr/local/include" });
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-I/some/other/path"}, &.{"-I/some/other/path"});

    // 2. MSVC Linker Flags
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-msvc", &.{ "-Xlinker", "/MANIFEST:EMBED" }, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-msvc", &.{ "-Xlinker", "/version:0.0" }, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-msvc", &.{ "-Xlinker", "--dependency-file=test.d" }, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-msvc", &.{ "-Xlinker", "/some-flag" }, &.{ "-Xlinker", "/some-flag" });

    // 3. Dialect Suffix
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-std=c++17"}, &.{"-std=c17"});
    try Helper.check(allocator, .cxx, false, false, "x86_64-linux-gnu", &.{"-std=c++17"}, &.{"-std=c++17"});

    // 4. Diagnostic Warnings
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-Werror"}, &.{ "-Werror", "-Wno-error=date-time" });

    // 5. Unsupported Options
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-m32"}, &.{"-m32"});
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{ "-m", "32" }, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-municode"}, &.{"-municode"});

    // 6. Linker Options
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-Wl,-v"}, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-Wl,-x"}, &.{"-Wl,--strip-all"});
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-Wl,-some-flag"}, &.{"-Wl,-some-flag"});

    // 7. OpenMP Linker Option
    try Helper.check(allocator, .cc, true, false, "x86_64-linux-gnu", &.{"-fopenmp=libomp"}, &.{ "-fopenmp=libomp", "-lomp" });
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-fopenmp=libomp"}, &.{"-fopenmp=libomp"});

    // 8. Autoconfig Options
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-link"}, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-dll"}, &.{"-shared"});

    // 9. Invalid CPU Types
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{ "-march", "i386" }, &.{});
    try Helper.check(allocator, .cc, false, false, "aarch64-linux-gnu", &.{ "-march", "i386" }, &.{ "-march", "i386" });

    // 10. Aarch64 architecture overrides
    try Helper.check(allocator, .cc, false, false, "aarch64-linux-gnu", &.{"-march=armv8.5-a"}, &.{"-march=apple-a14"});
    try Helper.check(allocator, .cc, false, false, "aarch64-linux-gnu", &.{"-march=armv9.2-a+crc"}, &.{"-march=cortex-a725+crc"});
    try Helper.check(allocator, .cc, false, false, "aarch64-linux-gnu", &.{"-march=armv9-a"}, &.{"-march=cortex-a710"});

    // 11. Windows GNU specifics
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-gnu", &.{"-Wl,--disable-auto-image-base"}, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-gnu", &.{"-lmingw32"}, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-gnu", &.{"-lstdc++"}, &.{ "-lc++", "-lc++abi" });
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-gnu", &.{"-lfoo"}, &.{"-lfoo"});
    try Helper.check(allocator, .cc, true, false, "x86_64-windows-gnu", &.{"-flto"}, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-windows-gnu", &.{"-flto"}, &.{"-flto"});

    // 12. Preprocessor warnings/arguments
    try Helper.check(allocator, .cc, false, true, "x86_64-linux-gnu", &.{"-fms-compatibility-version"}, &.{});
    try Helper.check(allocator, .cc, false, true, "x86_64-linux-gnu", &.{"-fno-sanitize"}, &.{});
    try Helper.check(allocator, .cc, false, true, "x86_64-linux-gnu", &.{"-fvisibility-ms-compat"}, &.{});
    try Helper.check(allocator, .cc, false, false, "x86_64-linux-gnu", &.{"-fno-sanitize"}, &.{"-fno-sanitize"});

    // 13. MSVC Linker wrapper
    try Helper.check(allocator, .link, false, false, "x86_64-windows-msvc", &.{"--help"}, &.{"-help"});
    try Helper.check(allocator, .link, false, false, "x86_64-windows-msvc", &.{"-v"}, &.{"--version"});
}
