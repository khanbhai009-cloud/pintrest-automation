"""
mastermind/node_data.py — Node 1: Data Intelligence
Fetches last-7-day Pinterest analytics from two isolated Google Sheet tabs.
Accounts are treated as completely separate data sources — no mixing.
Falls back to a "Stagnant" analytics profile on any failure; never crashes.
"""
import logging
from mastermind.state import MastermindState
from tools.google_drive import get_analytics_rows

logger = logging.getLogger(__name__)

# ── Default stagnant profile injected on sheet failure ───────────────────────
STAGNANT_PROFILE = [
    {
        "Date": "fallback",
        "Impressions": 0,
        "Clicks": 0,
        "Outbound Clicks": 0,
        "Saves": 0,
    }
]


def node_data_intelligence(state: MastermindState) -> dict:
    """
    Node 1 — Data Intelligence.
    Fetches 7-day analytics for Account 1 (Analytics_Log) and
    Account 2 (Analytics_logs2) independently.
    On gspread failure → sets fallback_triggered=True and injects STAGNANT_PROFILE.
    """
    logger.info("📊 [Node 1 — Data Intelligence] Fetching analytics for both accounts...")
    fallback_triggered = state.get("fallback_triggered", False)

    # ── Account 1 ─────────────────────────────────────────────────────────────
    try:
        a1_rows = get_analytics_rows("Analytics_Log", days=7)
        if not a1_rows:
            logger.warning("⚠️ [Acc 1] Analytics_Log returned 0 rows — injecting Stagnant profile.")
            a1_rows = STAGNANT_PROFILE
            fallback_triggered = True
        else:
            logger.info(f"✅ [Acc 1] {len(a1_rows)} analytics rows fetched.")
    except Exception as e:
        logger.warning(f"⚠️ [Acc 1] Analytics fetch failed ({e}) — injecting Stagnant profile.")
        a1_rows = STAGNANT_PROFILE
        fallback_triggered = True

    # ── Account 2 ─────────────────────────────────────────────────────────────
    try:
        a2_rows = get_analytics_rows("Analytics_logs2", days=7)
        if not a2_rows:
            logger.warning("⚠️ [Acc 2] Analytics_logs2 returned 0 rows — injecting Stagnant profile.")
            a2_rows = STAGNANT_PROFILE
            fallback_triggered = True
        else:
            logger.info(f"✅ [Acc 2] {len(a2_rows)} analytics rows fetched.")
    except Exception as e:
        logger.warning(f"⚠️ [Acc 2] Analytics fetch failed ({e}) — injecting Stagnant profile.")
        a2_rows = STAGNANT_PROFILE
        fallback_triggered = True

    logger.info(
        f"📊 [Node 1 — Done] A1: {len(a1_rows)} rows | A2: {len(a2_rows)} rows | "
        f"Fallback: {fallback_triggered}"
    )

    return {
        "a1_raw_analytics": a1_rows,
        "a2_raw_analytics": a2_rows,
        "fallback_triggered": fallback_triggered,
    }
