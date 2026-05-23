"""
sheets/analytics.py — Pinterest analytics rows from named sheet tabs.

Each tab expected columns: Date | Impressions | Clicks | Outbound Clicks | Saves
Account 1 tab: Analytics_Log
Account 2 tab: Analytics_logs2
"""
import logging
from datetime import datetime, timedelta
from sheets.base import _open_worksheet, _throttled_read

logger = logging.getLogger(__name__)


def get_analytics_rows(sheet_name: str, days: int = 7) -> list:
    """
    Fetch the last `days` days of Pinterest analytics from a named sheet tab.
    Returns a list of dicts (one per day).
    Raises on connection error — calling node catches and applies stagnant fallback.
    """
    def _read():
        ws = _open_worksheet(sheet_name)
        return ws.get_all_records()

    records = _throttled_read(_read)

    if not records:
        logger.warning(f"⚠️  [{sheet_name}] Sheet is empty — no analytics rows.")
        return []

    cutoff       = datetime.now() - timedelta(days=days)
    filtered     = []
    parse_errors = 0

    for row in records:
        raw_date = str(row.get("Date", "")).strip()
        if not raw_date:
            continue
        parsed = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y"):
            try:
                parsed = datetime.strptime(raw_date, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            parse_errors += 1
            filtered.append(row)
        elif parsed >= cutoff:
            filtered.append(row)

    if parse_errors:
        logger.warning(f"⚠️  [{sheet_name}] {parse_errors} rows had unparseable dates — included as-is.")

    if not filtered:
        filtered = records[-days:]
        logger.info(f"ℹ️  [{sheet_name}] Date filter returned 0 rows — using last {days} rows.")

    logger.info(f"✅ [{sheet_name}] {len(filtered)} analytics rows loaded.")
    return filtered
