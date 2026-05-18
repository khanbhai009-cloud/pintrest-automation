"""
sheets/prompts_master.py — Prompts_Master sheet tab fetch with TTL cache.

Tab columns: style_key | account | label | description | t2i_base | niche_affinity | tags
Account values: account_1 | account_2
TTL: 30 minutes — new rows added to the sheet auto-picked up within 30 min.
"""
import time
import logging
from sheets.base import _open_worksheet

logger = logging.getLogger(__name__)

_cache: list | None = None
_cache_ts: float    = 0.0
_TTL: int           = 1800   # 30 minutes


def get_prompts_master() -> list:
    """
    Fetch all rows from Prompts_Master tab.
    TTL-cached (30 min) — new rows in the sheet are picked up automatically.
    Raises on connection failure — caller handles fallback.
    """
    global _cache, _cache_ts
    now = time.time()
    if _cache is not None and (now - _cache_ts) < _TTL:
        return _cache
    ws            = _open_worksheet("Prompts_Master")
    records       = ws.get_all_records()
    _cache        = records
    _cache_ts     = now
    logger.info(f"✅ [Prompts_Master] {len(records)} prompts loaded (TTL refreshed).")
    return records


def invalidate_cache() -> None:
    """Force next call to re-fetch from Sheets."""
    global _cache, _cache_ts
    _cache    = None
    _cache_ts = 0.0


def append_prompt_row(data: dict) -> None:
    """
    Vision Feeder se extract ki gayi DNA row ko Prompts_Master mein append karo.
    TTL cache invalidate karta hai taaki next fetch fresh rows laye.
    Columns: style_key | account | label | description | t2i_base | niche_affinity | tags
    """
    ws  = _open_worksheet("Prompts_Master")
    row = [
        data.get("style_key",      ""),
        data.get("account",        "account_1"),
        data.get("label",          ""),
        data.get("description",    ""),
        data.get("t2i_base",       ""),
        data.get("niche_affinity", ""),
        data.get("tags",           ""),
    ]
    ws.append_row(row)
    invalidate_cache()
    logger.info(f"✅ [Prompts_Master] Row appended: {data.get('style_key')}")
