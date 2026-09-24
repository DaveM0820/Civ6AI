"""Read Firaxis .fpk archives (Civ IV/V Resource packs)."""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from pathlib import Path

_FPK_V6_MAGIC = 0x5F4B5046  # "FPK_"


@dataclass(frozen=True)
class FpkEntry:
    path: str
    offset: int
    length: int
    fpk_path: Path


def _decode_filename(raw: bytes, length: int) -> str:
    return bytes((byte - 1) % 256 for byte in raw[:length]).decode("utf-8", errors="replace")


def _clean_fpk_name(name: str) -> str:
    return re.sub(r"[\x00-\x1f]", "", name).strip()


def _read_fpk_v6_index(fpk_path: Path) -> list[FpkEntry]:
    """Civ V/Beyond Earth FPK version 6 (header FPK_, variable-length file table)."""
    raw = fpk_path.read_bytes()
    if len(raw) < 14:
        return []
    version, magic = struct.unpack_from("<II", raw, 0)
    if version != 6 or magic != _FPK_V6_MAGIC:
        return []
    count = struct.unpack_from("<H", raw, 10)[0]
    pos = 14
    table: list[tuple[str, tuple[int, int, int, int, int]]] = []
    for index in range(count):
        if pos + 4 > len(raw):
            break
        if index == 0:
            name_len = struct.unpack_from("<I", raw, pos)[0]
            pos += 4
        else:
            name_len = raw.find(b"\x00", pos) - pos
            if name_len <= 0:
                break
        blocks = (name_len + 3) // 4
        if pos + blocks * 4 + 20 > len(raw):
            break
        name = _clean_fpk_name(raw[pos:pos + name_len].decode("utf-8", errors="replace"))
        pos += blocks * 4
        meta = struct.unpack_from("<IIIII", raw, pos)
        pos += 20
        if name:
            table.append((name, meta))

    offsets: list[int] = []
    for index, (name, meta) in enumerate(table):
        offset = _fpk_v6_blob_offset(meta, index, name)
        if offset > 0:
            offsets.append(offset)
    offsets = sorted(set(offsets))
    offset_size: dict[int, int] = {}
    for index, offset in enumerate(offsets):
        if index + 1 < len(offsets):
            offset_size[offset] = offsets[index + 1] - offset
    file_size = len(raw)

    entries: list[FpkEntry] = []
    for index, (name, meta) in enumerate(table):
        offset = _fpk_v6_blob_offset(meta, index, name)
        if offset <= 0:
            continue
        length = _fpk_v6_blob_size(meta, index, name, offset_size, file_size)
        if length <= 0 or offset + length > file_size:
            continue
        entries.append(FpkEntry(path=name, offset=offset, length=length, fpk_path=fpk_path))
    return entries


def _fpk_v6_blob_offset(meta: tuple[int, int, int, int, int], index: int, name: str) -> int:
    clean = name.lower()
    if "terrainhex" in clean:
        return meta[3]
    if index == 0:
        return meta[2]
    if meta[3] > meta[2]:
        return meta[3]
    return meta[2]


def _fpk_v6_blob_size(
    meta: tuple[int, int, int, int, int],
    index: int,
    name: str,
    offset_size: dict[int, int],
    file_size: int,
) -> int:
    clean = name.lower()
    if "terrainhex" in clean:
        return meta[2]
    if index == 0:
        return meta[3]
    offset = _fpk_v6_blob_offset(meta, index, name)
    size = offset_size.get(offset)
    if size is not None:
        return size
    return max(0, file_size - offset)


def _read_fpk_legacy_index(fpk_path: Path) -> list[FpkEntry]:
    raw = fpk_path.read_bytes()
    if len(raw) < 8:
        return []
    version, count = struct.unpack_from("<II", raw, 0)
    if version not in (1, 2):
        return []
    entries: list[FpkEntry] = []
    pos = 8
    for _ in range(count):
        if pos + 4 > len(raw):
            break
        name_len = struct.unpack_from("<I", raw, pos)[0]
        pos += 4
        blocks = (name_len + 3) // 4
        name_bytes = raw[pos: pos + blocks * 4]
        pos += blocks * 4
        if pos + 16 > len(raw):
            break
        _checksum, _tag, length, offset = struct.unpack_from("<IIII", raw, pos)
        pos += 16
        if name_len <= 0 or length <= 0:
            continue
        path = _decode_filename(name_bytes, name_len)
        entries.append(FpkEntry(path=path, offset=offset, length=length, fpk_path=fpk_path))
    return entries


def read_fpk_index(fpk_path: Path) -> list[FpkEntry]:
    raw = fpk_path.read_bytes()
    if len(raw) < 8:
        return []
    version = struct.unpack_from("<I", raw, 0)[0]
    if version == 6:
        return _read_fpk_v6_index(fpk_path)
    return _read_fpk_legacy_index(fpk_path)


def extract_entry(entry: FpkEntry) -> bytes:
    data = entry.fpk_path.read_bytes()
    end = entry.offset + entry.length
    if entry.offset < 0 or end > len(data):
        return b""
    return data[entry.offset: end]


def find_in_fpk_indexes(
    indexes: list[list[FpkEntry]],
    suffix: str,
) -> FpkEntry | None:
    needle = suffix.replace("\\", "/").lower()
    base = needle.rsplit("/", 1)[-1]
    for index in indexes:
        for entry in index:
            path = entry.path.replace("\\", "/").lower()
            leaf = path.rsplit("/", 1)[-1]
            if path.endswith(needle) or path == needle or leaf == base or leaf == needle:
                return entry
    return None
