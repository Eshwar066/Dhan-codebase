"""Bound growth of engine JSONL audit logs (events / intent pipeline)."""

from __future__ import annotations

import logging
import os
from typing import Union

logger = logging.getLogger(__name__)

# Line-based: same idea as indicator_history trim.
JSONL_TRIM_TRIGGER_LINES = 5_000
JSONL_TRIM_DROP_LINES = 3_000
# Size-based safety net (events used to dump megabyte contexts).
JSONL_TRIM_TRIGGER_BYTES = 8 * 1024 * 1024  # 8 MiB
JSONL_KEEP_TAIL_BYTES = 2 * 1024 * 1024  # keep last ~2 MiB


def maybe_trim_jsonl_file(
    path: Union[str, os.PathLike],
    *,
    trigger_lines: int = JSONL_TRIM_TRIGGER_LINES,
    drop_lines: int = JSONL_TRIM_DROP_LINES,
    trigger_bytes: int = JSONL_TRIM_TRIGGER_BYTES,
    keep_tail_bytes: int = JSONL_KEEP_TAIL_BYTES,
) -> bool:
    """
    Trim ``path`` when too many lines or too large on disk.

    Prefer line-based drop of oldest lines; if the file is huge (oversized payloads),
    keep only the trailing ``keep_tail_bytes`` (aligned to next newline).
    """
    p = os.fspath(path)
    if not p or not os.path.isfile(p):
        return False

    try:
        size = os.path.getsize(p)
    except OSError:
        return False

    did = False
    # Oversized binary-ish growth: keep a byte tail (fast), then fall through to line trim.
    if trigger_bytes > 0 and size >= trigger_bytes and keep_tail_bytes > 0:
        try:
            with open(p, "rb") as f:
                f.seek(max(0, size - keep_tail_bytes))
                data = f.read()
            # Align to next newline so we don't leave a partial JSON line.
            nl = data.find(b"\n")
            if nl >= 0:
                data = data[nl + 1 :]
            tmp = f"{p}.trim.tmp"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, p)
            logger.info(
                "Trimmed JSONL by size %s: %s -> %s bytes",
                p,
                size,
                len(data),
            )
            size = len(data)
            did = True
        except OSError:
            logger.exception("Failed size-trim of JSONL: %s", p)
            try:
                if os.path.exists(f"{p}.trim.tmp"):
                    os.remove(f"{p}.trim.tmp")
            except OSError:
                pass
            return False

    if trigger_lines <= 0 or drop_lines <= 0 or drop_lines >= trigger_lines:
        return did

    try:
        with open(p, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        logger.exception("Failed reading JSONL for trim: %s", p)
        return did

    n = len(lines)
    if n < trigger_lines:
        return did

    kept = lines[drop_lines:]
    tmp = f"{p}.trim.tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(kept)
        os.replace(tmp, p)
    except OSError:
        logger.exception("Failed line-trim of JSONL: %s", p)
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass
        return did

    logger.info(
        "Trimmed JSONL %s: %s -> %s lines (dropped first %s)",
        p,
        n,
        len(kept),
        drop_lines,
    )
    return True
