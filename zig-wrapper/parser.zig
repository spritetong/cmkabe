// Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
//
// This software is under the MIT License
// https://github.com/spritetong/cmkabe

const std = @import("std");
const utils = @import("utils.zig");

pub const SimpleOptionParser = struct {
    const Self = @This();
    args: []const []const u8,
    always_positional: bool = false,
    consumed: []const []const u8 = &[_][]const u8{},
    option: []const u8 = "",
    value: []const u8 = "",

    pub inline fn hasArgument(self: Self) bool {
        return self.args.len > 0;
    }

    /// Get the first argument and retain it.
    pub fn first(self: Self) ?[]const u8 {
        if (self.hasArgument()) {
            return self.args[0];
        }
        return null;
    }

    /// Pick the next argument.
    pub fn next(self: *Self) ?[]const u8 {
        if (self.hasArgument()) {
            self.advance(1);
            return self.consumed.ptr[0];
        }
        return null;
    }

    /// Skip the next `count` arguments.
    pub fn advance(self: *Self, count: usize) void {
        self.consumed = self.args[0..count];
        self.args = self.args[count..];
    }

    /// Do not consume any argument if failed.
    pub fn parsePositional(self: *Self, accept_double_dash: bool) ?[]const u8 {
        while (self.first()) |arg| {
            if (self.always_positional or !utils.strStartsWith(arg, "-")) {
                self.advance(1);
                return arg;
            }
            if (utils.strEql(arg, "--")) {
                self.always_positional = true;
                self.advance(1);
                if (accept_double_dash) return arg;
            } else {
                break;
            }
        }
        return null;
    }

    /// Do not consume any argument if failed.
    pub fn parseNamed(self: *Self, options: []const []const u8, require_value: bool) bool {
        if (self.first()) |arg| {
            for (options) |opt| {
                if (utils.strEql(arg, opt)) {
                    if (!require_value) {
                        self.option = arg;
                        self.advance(1);
                        return true;
                    } else if (self.args.len > 1) {
                        self.option = arg;
                        self.value = self.args[1];
                        self.advance(2);
                        return true;
                    } else {
                        return false;
                    }
                }

                if (!require_value) continue;

                if (utils.strStartsWith(arg, opt)) {
                    if (opt.len == 2 and opt[0] == '-') {
                        self.option = arg[0..opt.len];
                        self.value = arg[opt.len..];
                        self.advance(1);
                        return true;
                    } else if (arg[opt.len] == '=') {
                        self.option = arg[0..opt.len];
                        self.value = arg[opt.len + 1 ..];
                        self.advance(1);
                        return true;
                    }
                }
            }
        }
        return false;
    }
};
