"""
pipeline/keyword_agent.py — Weekly Viral Keywords + Daily Pin Slot Planner

HOW IT WORKS:
- User ek Weekly_Keywords sheet me keywords data deta hai (ya neeche ke dict me hardcode karta hai)
- Yahan se har roz ke liye 15 pin slots plan hote hain (max 20/day, 105/week)
- Har slot me ek keyword hota hai jiske basis pe pin banega

SHEET FORMAT (Weekly_Keywords tab):
  week_number | keyword | niche | account | day_target | priority
  1           | wall art bedroom ideas | home | acc1 | monday | high

Ya seedha is file me WEEKLY_KEYWORDS dict fill karo.
"""

import logging
import time
from datetime import date, datetime
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════════════════════

PINS_PER_WEEK  = 105   # Total weekly target
PINS_PER_DAY   = 15    # Default per day (max 20)
MAX_PER_DAY    = 20    # Hard cap

# ── Weekly Keywords — User yahan apna data fill kare ─────────────────────────
# Format: list of dicts
# keyword    : Pinterest pe search hone wala viral keyword
# niche      : board niche (home/kitchen/cozy/gadgets/organize/tech/budget/phone/smarthome/wfh)
# account    : "acc1" (HomeDecor) ya "acc2" (Tech)
# priority   : "high" / "medium" / "low"
# days       : list of weekday names jab ye keyword use ho (empty = sab din)
#
# NOTE: Inhe replace karo apne actual viral keywords se
WEEKLY_KEYWORDS = [
    # ── HOME DECOR (Account 1) ───────────────────────────────────────────────
    {"keyword": "aesthetic bedroom wall decor ideas 2025",  "niche": "home",     "account": "acc1", "priority": "high",   "days": []},
    {"keyword": "small living room transformation ideas",    "niche": "home",     "account": "acc1", "priority": "high",   "days": []},
    {"keyword": "amazon home finds under 30 dollars",        "niche": "home",     "account": "acc1", "priority": "high",   "days": []},
    {"keyword": "cozy bedroom aesthetic setup 2025",         "niche": "cozy",     "account": "acc1", "priority": "high",   "days": []},
    {"keyword": "kitchen organization hacks amazon",         "niche": "kitchen",  "account": "acc1", "priority": "medium", "days": []},
    {"keyword": "boho home decor living room",               "niche": "home",     "account": "acc1", "priority": "medium", "days": []},
    {"keyword": "minimalist bedroom decor ideas",            "niche": "home",     "account": "acc1", "priority": "medium", "days": []},
    {"keyword": "cute desk setup aesthetic home office",     "niche": "organize", "account": "acc1", "priority": "medium", "days": []},
    {"keyword": "viral kitchen gadgets 2025 tiktok",         "niche": "kitchen",  "account": "acc1", "priority": "high",   "days": []},
    {"keyword": "led lights room aesthetic pinterest",       "niche": "cozy",     "account": "acc1", "priority": "medium", "days": []},
    {"keyword": "bathroom shelf decor aesthetic",            "niche": "organize", "account": "acc1", "priority": "low",    "days": []},
    {"keyword": "wall art prints bedroom inspo",             "niche": "home",     "account": "acc1", "priority": "medium", "days": []},
    {"keyword": "amazon must haves for home 2025",           "niche": "home",     "account": "acc1", "priority": "high",   "days": []},
    {"keyword": "reading nook ideas cozy corner",            "niche": "cozy",     "account": "acc1", "priority": "low",    "days": []},
    {"keyword": "plant shelf ideas indoor aesthetic",        "niche": "home",     "account": "acc1", "priority": "medium", "days": []},

    # ── TECH / GADGETS (Account 2) ───────────────────────────────────────────
    {"keyword": "aesthetic desk setup ideas 2025",           "niche": "tech",     "account": "acc2", "priority": "high",   "days": []},
    {"keyword": "cool gadgets you need from amazon",         "niche": "gadgets",  "account": "acc2", "priority": "high",   "days": []},
    {"keyword": "work from home setup ideas aesthetic",      "niche": "wfh",      "account": "acc2", "priority": "high",   "days": []},
    {"keyword": "budget gaming setup under 500",             "niche": "budget",   "account": "acc2", "priority": "medium", "days": []},
    {"keyword": "smart home gadgets 2025 amazon",            "niche": "smarthome","account": "acc2", "priority": "high",   "days": []},
    {"keyword": "iphone accessories aesthetic magsafe",      "niche": "phone",    "account": "acc2", "priority": "medium", "days": []},
    {"keyword": "viral tech gadgets tiktok 2025",            "niche": "gadgets",  "account": "acc2", "priority": "high",   "days": []},
    {"keyword": "rgb desk setup ideas gaming",               "niche": "tech",     "account": "acc2", "priority": "medium", "days": []},
    {"keyword": "best laptop accessories for students",      "niche": "wfh",      "account": "acc2", "priority": "medium", "days": []},
    {"keyword": "futuristic home gadgets 2025",              "niche": "smarthome","account": "acc2", "priority": "low",    "days": []},
    {"keyword": "galaxy projector room aesthetic",           "niche": "smarthome","account": "acc2", "priority": "medium", "days": []},
    {"keyword": "mechanical keyboard aesthetic desk",        "niche": "tech",     "account": "acc2", "priority": "medium", "days": []},
    {"keyword": "mini gadgets amazon under 20",              "niche": "budget",   "account": "acc2", "priority": "low",    "days": []},
    {"keyword": "phone stand aesthetic wireless charging",   "niche": "phone",    "account": "acc2", "priority": "low",    "days": []},
    {"keyword": "ambient room lighting smart bulbs",         "niche": "smarthome","account": "acc2", "priority": "medium", "days": []},
]


# ══════════════════════════════════════════════════════════════════════════════
# DATA CLASS
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class WeeklyKeyword:
    keyword:  str
    niche:    str
    account:  str          # "acc1" or "acc2"
    priority: str = "medium"
    days:     List[str] = field(default_factory=list)  # empty = all days


# ══════════════════════════════════════════════════════════════════════════════
# FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def get_weekly_plan() -> List[WeeklyKeyword]:
    """
    Weekly keywords ka full list return karo.
    Aage jake yahan Google Sheet se bhi fetch kar sakte ho.
    """
    return [
        WeeklyKeyword(
            keyword  = kw["keyword"],
            niche    = kw["niche"],
            account  = kw["account"],
            priority = kw.get("priority", "medium"),
            days     = kw.get("days", []),
        )
        for kw in WEEKLY_KEYWORDS
    ]


def get_todays_keywords(
    account: Optional[str] = None,
    limit: int = PINS_PER_DAY,
) -> List[WeeklyKeyword]:
    """
    Aaj ke liye keywords return karo.

    Args:
        account : "acc1" ya "acc2" — None means dono ke keywords
        limit   : max kitne keywords chahiye (default 15)

    Returns:
        List[WeeklyKeyword] — aaj ke pin slots ke liye
    """
    today_name = datetime.now().strftime("%A").lower()  # "monday", "tuesday", etc.
    all_kw     = get_weekly_plan()

    # Filter by account
    if account:
        all_kw = [k for k in all_kw if k.account == account]

    # Filter by day (empty days = valid on all days)
    todays = [
        k for k in all_kw
        if (not k.days) or (today_name in [d.lower() for d in k.days])
    ]

    # Priority sort: high > medium > low
    _prio = {"high": 0, "medium": 1, "low": 2}
    todays.sort(key=lambda k: _prio.get(k.priority, 1))

    # Cap at limit
    selected = todays[:min(limit, MAX_PER_DAY)]

    logger.info(
        f"📅 Today ({today_name}): {len(selected)} keyword slots "
        f"{'for ' + account if account else '(both accounts)'}"
    )
    for kw in selected:
        logger.info(f"  • [{kw.priority.upper()}] [{kw.account}] [{kw.niche}] {kw.keyword}")

    return selected


# ══════════════════════════════════════════════════════════════════════════════
# SHEET INTEGRATION (Optional — uncomment when Weekly_Keywords tab ready)
# ══════════════════════════════════════════════════════════════════════════════

_sheet_cache: List[WeeklyKeyword] = []
_sheet_cache_ts: float = 0.0
_SHEET_TTL = 3600  # 1 hour


def _try_load_from_sheet() -> List[WeeklyKeyword]:
    """
    Weekly_Keywords sheet se keywords load karo (optional).
    Sheet format:  keyword | niche | account | priority | days (comma-sep)
    """
    global _sheet_cache, _sheet_cache_ts
    now = time.monotonic()
    if (now - _sheet_cache_ts) < _SHEET_TTL and _sheet_cache:
        return _sheet_cache

    try:
        from sheets.base import _open_worksheet
        sheet   = _open_worksheet("Weekly_Keywords")
        records = sheet.get_all_records()
        loaded  = []
        for r in records:
            kw = str(r.get("keyword", "")).strip()
            if not kw:
                continue
            days_raw = str(r.get("days", "")).strip()
            days     = [d.strip().lower() for d in days_raw.split(",") if d.strip()] if days_raw else []
            loaded.append(WeeklyKeyword(
                keyword  = kw,
                niche    = str(r.get("niche", "home")).strip(),
                account  = str(r.get("account", "acc1")).strip(),
                priority = str(r.get("priority", "medium")).strip(),
                days     = days,
            ))
        if loaded:
            _sheet_cache    = loaded
            _sheet_cache_ts = now
            logger.info(f"✅ Weekly_Keywords sheet se {len(loaded)} keywords loaded.")
            return loaded
    except Exception as e:
        logger.warning(f"⚠️ Weekly_Keywords sheet load failed: {e} — using hardcoded list.")

    return []
