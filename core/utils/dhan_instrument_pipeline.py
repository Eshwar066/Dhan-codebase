"""
Daily / on-demand Dhan instrument master sync (scrip master CSV).

Source URL matches Tradehull.get_instrument_file():
https://images.dhan.co/api-data/api-scrip-master.csv

Use from a scheduled job: compare row count / hash with previous snapshot and alert on drift.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

SCRIP_MASTER_URL = "https://images.dhan.co/api-data/api-scrip-master.csv"


def download_scrip_master(dest_csv: Path) -> Path:
    """Download full scrip master to dest_csv (parent dirs created)."""
    dest_csv.parent.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(SCRIP_MASTER_URL, low_memory=False)
    if "SEM_CUSTOM_SYMBOL" in df.columns:
        df["SEM_CUSTOM_SYMBOL"] = (
            df["SEM_CUSTOM_SYMBOL"].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
        )
    df.to_csv(dest_csv, index=False, float_format="%.2f")
    logger.info("Wrote Dhan scrip master: %s rows -> %s", len(df), dest_csv)
    return dest_csv


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def diff_against_previous(
    new_csv: Path,
    previous_csv: Optional[Path],
) -> Dict[str, Any]:
    """
    Compare row count and content hash to previous file.
    Returns dict with changed=True if missing previous or hash differs.
    """
    new_hash = file_sha256(new_csv)
    try:
        new_df = pd.read_csv(new_csv, low_memory=False)
        new_rows = len(new_df)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    out: Dict[str, Any] = {
        "ok": True,
        "new_rows": new_rows,
        "new_sha256": new_hash,
        "changed": True,
    }
    if not previous_csv or not previous_csv.is_file():
        out["message"] = "No previous file — baseline established"
        return out
    old_hash = file_sha256(previous_csv)
    try:
        old_df = pd.read_csv(previous_csv, low_memory=False)
        old_rows = len(old_df)
    except Exception as e:
        out["message"] = f"Could not read previous: {e}"
        return out
    out["old_rows"] = old_rows
    out["old_sha256"] = old_hash
    out["changed"] = new_hash != old_hash or new_rows != old_rows
    out["message"] = (
        "Instrument master drift detected"
        if out["changed"]
        else "Instrument master unchanged"
    )
    return out


def prune_stale_instrument_csvs(deps_dir: Path, keep: Path) -> int:
    """Delete ``all_instrument*.csv`` files in ``deps_dir`` except ``keep``. Returns count removed."""
    removed = 0
    keep_resolved = keep.resolve()
    for p in deps_dir.glob("all_instrument*.csv"):
        try:
            if p.resolve() == keep_resolved:
                continue
            p.unlink()
            removed += 1
        except OSError as e:
            logger.warning("Could not remove stale instrument file %s: %s", p, e)
    return removed


def sync_with_alert(
    deps_dir: Path,
    current_date_str: str,
    alert_fn: Optional[Callable[[str], None]] = None,
    *,
    prune_stale: bool = True,
) -> Tuple[Path, Dict[str, Any]]:
    """
    Download to ``all_instrument{date}.csv``, diff vs previous day's file if present.
    By default removes older ``all_instrument*.csv`` after the diff.
    alert_fn: optional callback(str) e.g. Telegram.
    """
    deps_dir = Path(deps_dir)
    deps_dir.mkdir(parents=True, exist_ok=True)
    name = f"all_instrument{current_date_str}.csv"
    dest = deps_dir / name
    prev_candidates = [
        p
        for p in sorted(deps_dir.glob("all_instrument*.csv"), reverse=True)
        if p.resolve() != dest.resolve()
    ]
    previous = prev_candidates[0] if prev_candidates else None
    download_scrip_master(dest)
    info = diff_against_previous(dest, previous)
    if prune_stale:
        info["pruned"] = prune_stale_instrument_csvs(deps_dir, dest)
    msg = (
        f"Dhan instrument sync: {info.get('message')} rows={info.get('new_rows')} "
        f"changed={info.get('changed')} pruned={info.get('pruned', 0)}"
    )
    logger.info(msg)
    if info.get("changed") and alert_fn:
        try:
            alert_fn(msg)
        except Exception as e:
            logger.warning("instrument sync alert failed: %s", e)
    return dest, info
