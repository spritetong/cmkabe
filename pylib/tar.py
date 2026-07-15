# -*- coding: utf-8 -*-
# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe

import glob
import os
import re
import tarfile
from typing import Callable, List, Optional


def _ensure_xz_crc32():
    """Patch tarfile to support CRC32 checksum for xz."""
    if hasattr(tarfile.TarFile, 'xzopen_crc32'):
        return

    from lzma import LZMAFile, LZMAError, CHECK_CRC32

    def xzopen_crc32(name, mode='r', fileobj=None, preset=None, **kwargs):
        if mode not in ('r', 'w', 'x'):
            raise ValueError("mode must be 'r', 'w' or 'x'")

        check = CHECK_CRC32 if mode in ('w', 'x') else -1
        fileobj = LZMAFile(fileobj or name, mode, preset=preset, check=check)

        try:
            t = tarfile.TarFile.taropen(name, mode, fileobj, **kwargs)
        except (LZMAError, EOFError) as e:
            fileobj.close()
            if mode == 'r':
                raise tarfile.ReadError('not an lzma file') from e
            raise
        except Exception:
            fileobj.close()
            raise

        if hasattr(t, '_extfileobj'):
            t._extfileobj = False  # pyright: ignore[reportAttributeAccessIssue]
        return t

    setattr(tarfile.TarFile, 'xzopen_crc32', xzopen_crc32)
    tarfile.TarFile.OPEN_METH['xz-crc32'] = 'xzopen_crc32'  # pyright: ignore[reportIndexIssue]


def _add_to_tar(
    tar: tarfile.TarFile,
    src_path: str,
    arcname: str,
    user_filter: Optional[Callable[[tarfile.TarInfo], tarfile.TarInfo]],
    is_excluded: Callable[[str], bool],
):
    """Add a file, directory, or symlink to tar, setting permissions."""

    def _set_perms(tarinfo: tarfile.TarInfo) -> tarfile.TarInfo:
        tarinfo.uid = 0
        tarinfo.gid = 0
        tarinfo.uname = 'root'
        tarinfo.gname = 'root'
        if tarinfo.isdir() or arcname.lower().endswith(
            ('.sh', '.py', '.exe', '.bat', '.cmd')
        ):
            tarinfo.mode = 0o755
        elif tarinfo.issym():
            tarinfo.mode = 0o777
        else:
            tarinfo.mode = 0o644
        if user_filter:
            tarinfo = user_filter(tarinfo)
        return tarinfo

    # Directories: manually traverse
    if os.path.isdir(src_path):
        # Add directory entry (skip if arcname is empty = root)
        if arcname and not is_excluded(arcname + '/'):
            dir_info = tarfile.TarInfo(name=arcname + '/')
            dir_info.type = tarfile.DIRTYPE
            dir_info = _set_perms(dir_info)
            tar.addfile(dir_info)
        for root, dirs, files in os.walk(src_path):
            rel_root = os.path.relpath(root, src_path)
            for d in dirs:
                child_arc = os.path.join(arcname, rel_root, d).replace('\\', '/')
                if child_arc.startswith('./'):
                    child_arc = child_arc[2:]
                if is_excluded(child_arc + '/'):
                    continue
                _add_to_tar(
                    tar,
                    os.path.join(root, d),
                    child_arc,
                    user_filter=user_filter,
                    is_excluded=is_excluded,
                )
            for f in files:
                child_arc = os.path.join(arcname, rel_root, f).replace('\\', '/')
                if child_arc.startswith('./'):
                    child_arc = child_arc[2:]
                if is_excluded(child_arc):
                    continue
                _add_to_tar(
                    tar,
                    os.path.join(root, f),
                    child_arc,
                    user_filter=user_filter,
                    is_excluded=is_excluded,
                )
        return

    # Files and symlinks: tar.add handles both
    if not is_excluded(arcname):
        tar.add(src_path, arcname=arcname, filter=_set_perms)


def tar_create(
    items: List[tuple],
    output_path: str,
    *,
    mode: str = 'w:xz-crc32',
    format: int = tarfile.GNU_FORMAT,
    filter: Optional[Callable[[tarfile.TarInfo], tarfile.TarInfo]] = None,
    exclude: Optional[List[str]] = None,
):
    """
    Pack files into a tar.xz archive.

    :param items: List of (src_pattern_or_path, dest_arcname) tuples.
                  src can be a glob pattern. dest_arcname ending with '/' means directory.
                  Use '' for dest to place files at root.
    :param output_path: Output .txz file path.
    :param mode: Tar file open mode (default: 'w:xz-crc32').
    :param format: Tar format (default: GNU_FORMAT).
    :param filter: Optional filter function applied after default permissions.
                   Signature: filter(tarinfo: TarInfo) -> TarInfo
    :param exclude: List of regex patterns to exclude (e.g. ['.*\\.pyc$', '__pycache__']).
    """
    _ensure_xz_crc32()

    def _is_excluded(arcname: str) -> bool:
        if not exclude:
            return False
        return any(re.search(pat, arcname) for pat in exclude)

    with tarfile.open(output_path, mode=mode, format=format) as tar:  # pyright: ignore[reportCallIssue,reportArgumentType]
        for src_pattern, dest in items:
            matched = glob.glob(src_pattern, recursive=True)
            if not matched:
                print(f'Warning: no match for {src_pattern}')
                continue
            for src_path in matched:
                if dest == '':
                    # Root level: use basename for files, '' for dirs
                    if os.path.isdir(src_path):
                        arcname = ''
                    else:
                        arcname = os.path.basename(src_path)
                elif dest.endswith('/'):
                    arcname = os.path.join(dest, os.path.basename(src_path)).replace(
                        '\\', '/'
                    )
                else:
                    arcname = dest.replace('\\', '/')
                if _is_excluded(arcname):
                    continue
                _add_to_tar(
                    tar, src_path, arcname, user_filter=filter, is_excluded=_is_excluded
                )
