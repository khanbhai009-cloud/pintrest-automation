"""
sheets/style_tracker.py — Style rotation tracker (Style_Tracker sheet tab).

Tab columns: account_1 | account_2
Row 2 = current rotation indices (int).
Local JSON fallback: data/style_tracker_local.json

Reads are TTL-cached (5 min) to avoid hammering Sheets quota.
"""
import json
import logging
import os
import time
from sheets.base import _open_worksheet, _throttled_write, _throttled_read

logger = logging.getLogger(__name__)

_LOCAL_FILE = "data/style_tracker_local.json"

# ── Read cache (5 minute TTL) ──────────────────────────────────────────────
_read_cache: dict | None = None
_read_cache_ts: float    = 0.0
_READ_TTL = 300  # seconds


def _invalidate_cache() -> None:
    global _read_cache, _read_cache_ts
    _read_cache    = None
    _read_cache_ts = 0.0


def load_style_tracker() -> dict:
    """
    Load style rotation indices.
    Priority: in-memory TTL cache → Style_Tracker sheet tab → local JSON → empty dict.
    """
    global _read_cache, _read_cache_ts
    now = time.monotonic()

    # Return cached value if still fresh
    if _read_cache is not None and (now - _read_cache_ts) < _READ_TTL:
        return dict(_read_cache)

    # 1. Try Google Sheets
    try:
        def _read():
            sheet = _open_worksheet("Style_Tracker")
            return sheet.get_all_records()

        records = _throttled_read(_read)
        if records:
            data = {k: int(v) for k, v in records[0].items() if v != ""}
            logger.info(f"✅ Style_Tracker loaded from Sheets: {data}")
            _read_cache    = data
            _read_cache_ts = now
            return dict(data)
    except Exception as e:
        logger.warning(f"Style_Tracker Sheet failed — {type(e).__name__}: {e} | trying local file")

    # 2. Local JSON fallback
    try:
        if os.path.exists(_LOCAL_FILE):
            with open(_LOCAL_FILE, "r") as f:
                data = json.load(f)
                logger.info(f"Style_Tracker loaded from local file: {data}")
                _read_cache    = data
                _read_cache_ts = now
                return dict(data)
    except Exception as e:
        logger.warning(f"Style_Tracker local file failed — {type(e).__name__}: {e} | starting from 0")

    return {}


def save_style_tracker(tracker: dict) -> None:
    """
    Save style rotation indices.
    Always writes local JSON first, then tries Sheets (best effort).
    Invalidates read cache so next load_style_tracker() gets fresh data.
    """
    _invalidate_cache()

    # Always save locally first
    try:
        os.makedirs(os.path.dirname(_LOCAL_FILE), exist_ok=True)
        with open(_LOCAL_FILE, "w") as f:
            json.dump(tracker, f, indent=2)
    except Exception as e:
        logger.error(f"Style_Tracker local save failed — {type(e).__name__}: {e}")

    # Best-effort Sheets save (throttled)
    try:
        def _write():
            sheet   = _open_worksheet("Style_Tracker")
            records = sheet.get_all_records()
            a1_val  = tracker.get("account_1", 0)
            a2_val  = tracker.get("account_2", 0)
            if not records:
                sheet.append_row(["account_1", "account_2"])
                sheet.append_row([a1_val, a2_val])
            else:
                sheet.update("A2", [[a1_val, a2_val]])

        _throttled_write(_write)
        logger.info(f"✅ Style_Tracker saved to Sheets: {tracker}")
    except Exception as e:
        logger.warning(f"Style_Tracker Sheet save failed (local saved) — {type(e).__name__}: {e}")
