"""
sheets/vision_tracker.py — Vision Feeder processed-image log (Vision_Tracker sheet tab).

Tab columns: date | file_name | style_key | account | status | timestamp
One row per image processed. Used for daily count (restart-safe) + audit trail.

Count reads are TTL-cached (60 s) to avoid hammering Sheets quota.
"""
import logging
import time
from datetime import datetime, date
from sheets.base import _open_worksheet, _throttled_write

logger = logging.getLogger(__name__)

# ── Daily-count cache (60 second TTL) ─────────────────────────────────────
_count_cache: dict = {"date": None, "count": 0, "ts": 0.0}
_COUNT_TTL = 60  # seconds


def _invalidate_count_cache() -> None:
    _count_cache["ts"] = 0.0


def log_to_vision_tracker(
    file_name: str,
    style_key: str,
    account:   str,
    status:    str = "processed"
) -> None:
    """
    Har processed image ke baad Vision_Tracker sheet mein ek row append karo.
    Agar sheet empty hai toh header row pehle inject karo.
    """
    try:
        def _write():
            sheet   = _open_worksheet("Vision_Tracker")
            records = sheet.get_all_records()
            if not records:
                sheet.append_row(["date", "file_name", "style_key", "account", "status", "timestamp"])
            now = datetime.now()
            sheet.append_row([
                str(date.today()),
                file_name,
                style_key,
                account,
                status,
                now.strftime("%I:%M %p")
            ])

        _throttled_write(_write)
        _invalidate_count_cache()
        logger.info(f"✅ Vision_Tracker logged: {file_name} → {style_key} ({account})")
    except Exception as e:
        logger.warning(f"⚠️ Vision_Tracker sheet log failed — {type(e).__name__}: {e}")


def get_today_count_from_sheet() -> int:
    """
    Vision_Tracker sheet se aaj ki processed image count return karo.
    TTL-cached (60 s) — dashboard refresh pe baar baar Sheets hit nahi hoga.
    Restart-safe: app restart ke baad bhi sahi count milti hai.
    Returns 0 on any failure — caller falls back to in-memory count.
    """
    today = str(date.today())
    now   = time.monotonic()

    # Return cached value if still fresh and same day
    if (
        _count_cache["date"] == today
        and (now - _count_cache["ts"]) < _COUNT_TTL
    ):
        return _count_cache["count"]

    try:
        sheet   = _open_worksheet("Vision_Tracker")
        records = sheet.get_all_records()
        count   = sum(1 for r in records if str(r.get("date", "")).strip() == today)
        _count_cache.update({"date": today, "count": count, "ts": now})
        logger.info(f"✅ Vision_Tracker: {count} images processed today (from Sheets)")
        return count
    except Exception as e:
        logger.warning(f"⚠️ Vision_Tracker count failed — {type(e).__name__}: {e} | using in-memory")
        return 0
