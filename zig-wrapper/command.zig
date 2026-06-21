const std = @import("std");

/// Represents a command that can be executed by the Zig compiler
pub const ZigCommand = enum {
    /// Represents the archive utility (similar to ar)
    ar,
    /// C compiler mode
    cc,
    /// C++ compiler mode
    cxx,
    /// DLL tool for Windows
    dlltool,
    /// Linker mode (LLD)
    ld,
    /// Library manager
    lib,
    /// MSVC-style linker
    link,
    /// Object file copy utility
    objcopy,
    /// Archive index generator
    ranlib,
    /// Resource compiler
    rc,
    /// Symbol stripper
    strip,
    /// Windows resource compiler
    windres,

    const Self = @This();

    /// Converts a string command name to its corresponding ZigCommand
    /// Returns null if the command is not recognized
    pub fn fromStr(str: []const u8) ?Self {
        const map = std.StaticStringMap(ZigCommand).initComptime(.{
            .{ "ar", .ar },
            .{ "cc", .cc },
            .{ "c++", .cxx },
            .{ "dlltool", .dlltool },
            .{ "ld", .ld },
            .{ "lib", .lib },
            .{ "link", .link },
            .{ "objcopy", .objcopy },
            .{ "ranlib", .ranlib },
            .{ "rc", .rc },
            .{ "strip", .strip },
            .{ "windres", .windres },
            .{ "clang", .cc },
            .{ "clang++", .cxx },
            .{ "gcc", .cc },
            .{ "g++", .cxx },
        });
        return map.get(str);
    }

    /// Returns the actual command name to be passed to Zig
    /// Some commands need special naming (e.g., cxx -> c++)
    pub fn toName(self: Self) []const u8 {
        return switch (self) {
            .cxx => "c++",
            .ld => "ld.lld",
            .link => "lld-link",
            .windres => "rc",
            else => @tagName(self),
        };
    }

    pub fn envNameOfFlags(self: Self) ?[]const u8 {
        return switch (self) {
            .ar => "ARFLAGS",
            .cc => "CFLAGS",
            .cxx => "CXXFLAGS",
            .ld => "LDFLAGS",
            .ranlib => "RANLIBFLAGS",
            else => null,
        };
    }

    pub fn isCompiler(self: Self) bool {
        return switch (self) {
            .cc, .cxx => true,
            else => false,
        };
    }
};
