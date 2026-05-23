"""
mastermind/node_blog_trigger.py — Node 4: Blog Trigger

Decides whether to create a blog post for this pin cycle.
Runs AFTER agent_executor. All checks must pass → should_create_blog=True.

Checks (in order):
  1. FIREBASE_CREDS_JSON env var set?
  2. last_posted_image_url present in state?
  3. Daily counter < 2? (check_and_increment_daily_counter)
  4. Active account's pin_type == "VIRAL_PIN"?
"""

import logging
import os

logger = logging.getLogger(__name__)


async def node_blog_trigger(state: dict) -> dict:
    """
    Node 4 — Blog Trigger.
    Returns state with should_create_blog set to True or False.
    """

    def _skip(reason: str) -> dict:
        logger.info(f"📝 Blog trigger: SKIP — {reason}")
        return {**state, "should_create_blog": False}

    # ── Check 1: Firebase configured ─────────────────────────────────────────
    if not os.getenv("FIREBASE_CREDS_JSON"):
        return _skip("FIREBASE_CREDS_JSON not set")

    # ── Check 2: Image URL available ─────────────────────────────────────────
    if not state.get("last_posted_image_url"):
        return _skip("last_posted_image_url is empty — no pin was posted")

    # ── Check 3: Daily blog limit ─────────────────────────────────────────────
    try:
        from tools.firebase_publisher import check_and_increment_daily_counter
        can_post = await check_and_increment_daily_counter()
        if not can_post:
            return _skip("daily blog limit reached (2/2)")
    except Exception as e:
        logger.error(f"❌ [BlogTrigger] Counter check failed: {e}")
        return _skip(f"counter check error: {e}")

    # ── Check 4: Only VIRAL_PINs get blog posts ───────────────────────────────
    trigger = state.get("cycle_trigger", "")
    if "account2" in trigger and "account1" not in trigger:
        active_strategy = state.get("a2_cmo_strategy", {})
    else:
        active_strategy = state.get("a1_cmo_strategy", {})

    pin_type = active_strategy.get("pin_type", "")
    if pin_type != "VIRAL_PIN":
        return _skip(f"pin_type={pin_type} — blog only for VIRAL_PIN")

    logger.info("📝 Blog trigger: GO ✅")
    return {**state, "should_create_blog": True}
