import logging
from tools.google_drive import count_pending
from phases.phase1_filter import run_filter_bot
from config import LOW_STOCK_THRESHOLD

logger = logging.getLogger(__name__)


async def check_and_refill():
    """Phase 3: Check stock, trigger Phase 1 if running low"""
    logger.info("🔄 Phase 3: Stock check")

    pending = count_pending()
    logger.info(f"📊 Pending products remaining: {pending}")

    if pending <= LOW_STOCK_THRESHOLD:
        logger.info(f"⚠️ Low stock ({pending} ≤ {LOW_STOCK_THRESHOLD}). Running Filter Bot...")
        await run_filter_bot()
    else:
        logger.info("✅ Stock OK, no refill needed")

# ─────────────────────────────────────────
# FUTURE: Add multi-CSV rotation here
# e.g. pick next CSV from a queue
# for Level 3 scaled data sourcing
# ─────────────────────────────────────────
