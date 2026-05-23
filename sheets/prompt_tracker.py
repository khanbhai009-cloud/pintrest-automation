"""
sheets/prompt_tracker.py — Per-style prompt rotation indices (Prompt_Tracker sheet tab).

Tab columns: tracker_key | last_idx

Save strategy: batch_update for existing keys + append_rows for new keys.
Yeh ensure karta hai ki poora save sirf 2 API calls mein ho (N calls nahi),
taaki Sheets write quota (60 req/min) kabhi hit na ho.
"""
import logging
import time
from sheets.base import _open_worksheet, _throttled_write, _throttled_read

logger = logging.getLogger(__name__)

# ── Read cache (2 minute TTL) ──────────────────────────────────────────────
_read_cache: dict | None = None
_read_cache_ts: float    = 0.0
_READ_TTL = 120  # seconds


def _invalidate_cache() -> None:
    global _read_cache, _read_cache_ts
    _read_cache    = None
    _read_cache_ts = 0.0


def load_prompt_tracker() -> dict:
    """
    Load per-style prompt rotation indices from Google Sheets.
    TTL-cached (2 min) to avoid hammering the read quota.
    """
    global _read_cache, _read_cache_ts
    now = time.monotonic()

    if _read_cache is not None and (now - _read_cache_ts) < _READ_TTL:
        return dict(_read_cache)

    try:
        def _read():
            sheet   = _open_worksheet("Prompt_Tracker")
            return sheet.get_all_records()

        records = _throttled_read(_read)
        data = {}
        for r in records:
            key = r.get("tracker_key", "")
            val = r.get("last_idx", 0)
            if key and key != "tracker_key":
                try:
                    data[str(key)] = int(val)
                except ValueError:
                    continue

        _read_cache    = data
        _read_cache_ts = now
        logger.info(f"✅ Prompt_Tracker loaded from Sheets — {len(data)} keys")
        return dict(data)

    except Exception as e:
        logger.warning(f"Prompt_Tracker Sheet load failed — {type(e).__name__}: {e}")
        return {}


def save_prompt_tracker(tracker: dict) -> None:
    """
    Save per-style prompt rotation indices to Google Sheets.

    Instead of one API call per key (which triggers 429s), this batches
    everything into at most 2 API calls:
      1. batch_update — updates all existing rows in one request
      2. append_rows  — adds all new rows in one request
    """
    _invalidate_cache()

    try:
        def _write():
            sheet   = _open_worksheet("Prompt_Tracker")
            records = sheet.get_all_records()

            # Agar sheet bilkul khali hai toh header + saara data ek saath
            if not records:
                logger.info("Prompt_Tracker sheet empty — writing header + all data")
                sheet.append_row(["tracker_key", "last_idx"])
                if tracker:
                    sheet.append_rows([[k, v] for k, v in tracker.items()])
                return

            # Row number map: key → sheet row index (1-indexed, row 1 = header)
            existing_keys = {
                str(r["tracker_key"]): i + 2
                for i, r in enumerate(records)
                if r.get("tracker_key")
            }

            batch_updates = []
            new_rows      = []

            for key, idx in tracker.items():
                if key in existing_keys:
                    row_num = existing_keys[key]
                    batch_updates.append({
                        "range":  f"B{row_num}",
                        "values": [[idx]],
                    })
                else:
                    new_rows.append([key, idx])

            # Single batch_update call for all existing key updates
            if batch_updates:
                sheet.batch_update(batch_updates)
                logger.debug(f"[Prompt_Tracker] batch_update: {len(batch_updates)} cells")

            # Single append_rows call for all new keys
            if new_rows:
                sheet.append_rows(new_rows)
                logger.debug(f"[Prompt_Tracker] append_rows: {len(new_rows)} new keys")

        _throttled_write(_write)
        logger.info(f"✅ Prompt_Tracker saved to Sheets — {len(tracker)} keys")

    except Exception as e:
        logger.error(f"❌ Prompt_Tracker Sheet save failed — {type(e).__name__}: {e}")
