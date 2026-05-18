"""
sheets/vision_tracker.py — Vision Feeder processed-image log (Vision_Tracker sheet tab).

Tab columns: date | file_name | style_key | account | status | timestamp
One row per image processed. Used for daily count (restart-safe) + audit trail.
"""
import logging
from datetime import datetime, date
from sheets.base import _open_worksheet

logger = logging.getLogger(__name__)


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
        logger.info(f"✅ Vision_Tracker logged: {file_name} → {style_key} ({account})")
    except Exception as e:
        logger.warning(f"⚠️ Vision_Tracker sheet log failed — {type(e).__name__}: {e}")


def get_today_count_from_sheet() -> int:
    """
    Vision_Tracker sheet se aaj ki processed image count return karo.
    Restart-safe: app restart ke baad bhi sahi count milti hai.
    Returns 0 on any failure — caller falls back to in-memory count.
    """
    today = str(date.today())
    try:
        sheet   = _open_worksheet("Vision_Tracker")
        records = sheet.get_all_records()
        count   = sum(1 for r in records if str(r.get("date", "")).strip() == today)
        logger.info(f"✅ Vision_Tracker: {count} images processed today (from Sheets)")
        return count
    except Exception as e:
        logger.warning(f"⚠️ Vision_Tracker count failed — {type(e).__name__}: {e} | using in-memory")
        return 0
