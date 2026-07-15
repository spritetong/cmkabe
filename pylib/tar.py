# -*- coding: utf-8 -*-
# Copyright 2024-2026 Sprite Tong (<spritetong@gmail.com>)
#
# This software is under the MIT License
# https://github.com/spritetong/cmkabe

import glob
import os
import re
import tarfile
from typing import Callable, List, Optional, Tuple, Union


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
            setattr(t, '_extfileobj', False)
        return t

    setattr(tarfile.TarFile, 'xzopen_crc32', xzopen_crc32)
    tarfile.TarFile.OPEN_METH['xz-crc32'] = 'xzopen_crc32'  # pyright: ignore[reportIndexIssue]


def _add_to_tar(
    tar: tarfile.TarFile,
    src_path: str,
    arcname: str,
    *,
    set_perms: Callable[
        [tarfile.TarInfo, bool, Optional[str]], Optional[tarfile.TarInfo]
    ],
    is_excluded: Callable[[str, bool, Optional[str]], bool],
):
    """Add a file, directory, or symlink to tar, setting permissions."""
    # Directories: manually traverse (skip symlinks to directories)
    if os.path.isdir(src_path) and not os.path.islink(src_path):
        # Add directory entry (skip if arcname is empty = root)
        if arcname:
            dir_info = tarfile.TarInfo(name=arcname + '/')
            dir_info.type = tarfile.DIRTYPE
            dir_info = set_perms(dir_info, False, src_path)
            if dir_info is not None:
                tar.addfile(dir_info)
        for item in os.listdir(src_path):
            child_src = os.path.join(src_path, item)
            child_arc = (arcname + '/' + item if arcname else item).replace('\\', '/')
            is_child_dir = os.path.isdir(child_src) and not os.path.islink(child_src)
            if is_excluded(
                child_arc + '/' if is_child_dir else child_arc, is_child_dir, child_src
            ):
                continue
            _add_to_tar(
                tar,
                child_src,
                child_arc,
                set_perms=set_perms,
                is_excluded=is_excluded,
            )
        return

    # Files and symlinks: tar.add handles both
    tar.add(src_path, arcname=arcname, filter=lambda ti: set_perms(ti, False, src_path))


def tar_create(
    items: List[Tuple[str, str]],
    output_path: str,
    *,
    mode: str = 'xz',
    format: int = tarfile.GNU_FORMAT,
    filter: Optional[
        Union[
            Callable[[tarfile.TarInfo], Optional[tarfile.TarInfo]],
            List[Tuple[str, Union[int, bool, None]]],
        ]
    ] = None,
    user: Optional[Tuple[int, str]] = None,
    group: Optional[Tuple[int, str]] = None,
    verbose: bool = False,
):
    """
    Pack files into a tar.xz archive.

    :param items: List of (src_pattern_or_path, dest_arcname) tuples.
                  src can be a glob pattern. dest_arcname ending with '/' means directory.
                  Use '' for dest to place files at root.
    :param output_path: Output .txz file path.
    :param mode: Tar file open mode (default: 'xz').
    :param format: Tar format (default: GNU_FORMAT).
    :param filter: Optional filter applied after default permissions.
                   Can be a function: filter(tarinfo: TarInfo) -> Optional[TarInfo]
                   Or a list of [pattern, Union[int, bool, None]] rules, where pattern is a regex,
                   and action is either False (to exclude) or int (to update mode).
    :param user: Optional (uid, uname) tuple to override owner.
    :param group: Optional (gid, gname) tuple to override group.
    :param verbose: Print added file paths if True.
    """
    if isinstance(filter, (list, tuple)):

        def _user_filter(tarinfo: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
            for pattern, action in filter:
                if re.search(pattern, tarinfo.name):
                    if action is False:
                        return None
                    elif isinstance(action, int) and not isinstance(action, bool):
                        tarinfo.mode = action
                        break
                    elif action is True:
                        break
                    elif action is None:
                        continue
            return tarinfo

        user_filter = _user_filter
    elif callable(filter):
        user_filter = filter
    else:
        user_filter = lambda x: x  # noqa: E731

    def set_perms(
        tarinfo: tarfile.TarInfo,
        dry_run: bool = False,
        local_path: Optional[str] = None,
    ) -> Optional[tarfile.TarInfo]:
        tarinfo.uid = user[0] if user else 0
        tarinfo.gid = group[0] if group else 0
        tarinfo.uname = user[1] if user else 'root'
        tarinfo.gname = group[1] if group else 'root'

        is_executable = False
        if tarinfo.isdir() or tarinfo.name.lower().endswith(
            ('.sh', '.exe', '.bat', '.cmd')
        ):
            is_executable = True
        elif tarinfo.issym():
            pass
        elif local_path and os.path.isfile(local_path):
            _, ext = os.path.splitext(local_path)
            if ext in ('', '.py', '.pl', '.rb', '.php'):
                try:
                    with open(local_path, 'r', encoding='utf-8') as f:
                        if f.readline(80).startswith('#!/'):
                            is_executable = True
                except Exception:
                    pass

        if is_executable:
            tarinfo.mode = 0o755
        elif tarinfo.issym():
            tarinfo.mode = 0o777
        else:
            tarinfo.mode = 0o644

        res = user_filter(tarinfo)
        if res is None:
            return None
        tarinfo = res
        if not dry_run and verbose:
            print(tarinfo.name)
        return tarinfo

    def is_excluded(name: str, is_dir: bool, local_path: Optional[str] = None) -> bool:
        ti = tarfile.TarInfo(name=name)
        if is_dir:
            ti.type = tarfile.DIRTYPE
        else:
            ti.type = tarfile.REGTYPE
        return set_perms(ti, dry_run=True, local_path=local_path) is None

    open_mode = mode if mode.startswith('w') else 'w:' + mode
    with tarfile.open(output_path, mode=open_mode, format=format) as tar:  # pyright: ignore[reportCallIssue,reportArgumentType]
        for src_pattern, dest in items:
            matched = glob.glob(src_pattern, recursive=True)
            if not matched:
                print(f'Warning: no match for {src_pattern}')
                continue
            for src_path in matched:
                is_dir = os.path.isdir(src_path)
                if dest == '':
                    # Root level: use basename for files, '' for dirs
                    if is_dir:
                        arcname = ''
                    else:
                        arcname = os.path.basename(src_path)
                elif dest.endswith('/'):
                    arcname = os.path.join(dest, os.path.basename(src_path)).replace(
                        '\\', '/'
                    )
                else:
                    arcname = dest.replace('\\', '/')
                if is_excluded(arcname + '/' if is_dir else arcname, is_dir, src_path):
                    continue
                _add_to_tar(
                    tar,
                    src_path,
                    arcname,
                    set_perms=set_perms,
                    is_excluded=is_excluded,
                )


_ensure_xz_crc32()
