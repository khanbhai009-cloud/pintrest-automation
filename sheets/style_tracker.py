"""
sheets/style_tracker.py — Style rotation tracker (Style_Tracker sheet tab).

Tab columns: account_1 | account_2 | next_turn
Row 2 = current rotation indices (int) + whose turn is next (str).
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

_read_cache: dict | None = None
_read_cache_ts: float    = 0.0
_READ_TTL = 300  # seconds


def _invalidate_cache() -> None:
    global _read_cache, _read_cache_ts
    _read_cache = None
    _read_cache_ts = 0.0


def load_style_tracker() -> dict:
    """
    Load style rotation indices + turn state.
    Priority: in-memory TTL cache → Style_Tracker sheet tab → local JSON → empty dict.
    """
    global _read_cache, _read_cache_ts
    now = time.monotonic()

    if _read_cache is not None and (now - _read_cache_ts) < _READ_TTL:
        return dict(_read_cache)

    try:
        def _read():
            sheet = _open_worksheet("Style_Tracker")
            return sheet.get_all_records()

        records = _throttled_read(_read)
        if records:
            data = {}
            for k, v in records[0].items():
                if v == "":
                    continue
                data[k] = str(v) if k == "next_turn" else int(v)
            logger.info(f"✅ Style_Tracker loaded from Sheets: {data}")
            _read_cache = data
            _read_cache_ts = now
            return dict(data)
    except Exception as e:
        logger.warning(f"Style_Tracker Sheet failed — {type(e).__name__}: {e} | trying local file")

    try:
        if os.path.exists(_LOCAL_FILE):
            with open(_LOCAL_FILE, "r") as f:
                data = json.load(f)
                logger.info(f"Style_Tracker loaded from local file: {data}")
                _read_cache = data
                _read_cache_ts = now
                return dict(data)
    except Exception as e:
        logger.warning(f"Style_Tracker local file failed — {type(e).__name__}: {e} | starting from 0")

    return {}


def save_style_tracker(tracker: dict) -> None:
    """
    Save style rotation indices + turn state.
    Always writes local JSON first, then tries Sheets (best effort).
    NOTE: On GitHub Actions the local JSON does NOT persist across runs
    (fresh runner every time) — Sheets is the real source of truth.
    """
    _invalidate_cache()

    try:
        os.makedirs(os.path.dirname(_LOCAL_FILE), exist_ok=True)
        with open(_LOCAL_FILE, "w") as f:
            json.dump(tracker, f, indent=2)
    except Exception as e:
        logger.error(f"Style_Tracker local save failed — {type(e).__name__}: {e}")

    try:
        def _write():
            sheet = _open_worksheet("Style_Tracker")
            records = sheet.get_all_records()
            a1_val = tracker.get("account_1", 0)
            a2_val = tracker.get("account_2", 0)
            turn_val = tracker.get("next_turn", "account_1")
            if not records:
                sheet.append_row(["account_1", "account_2", "next_turn"])
                sheet.append_row([a1_val, a2_val, turn_val])
            else:
                headers = sheet.row_values(1)
                if "next_turn" not in headers:
                    sheet.update_cell(1, 3, "next_turn")
                sheet.update("A2", [[a1_val, a2_val, turn_val]])

        _throttled_write(_write)
        logger.info(f"✅ Style_Tracker saved to Sheets: {tracker}")
    except Exception as e:
        logger.warning(f"Style_Tracker Sheet save failed (local saved) — {type(e).__name__}: {e}")
