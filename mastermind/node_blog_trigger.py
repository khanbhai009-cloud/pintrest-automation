"""
mastermind/node_blog_trigger.py — Node 4: Blog Trigger

Decides whether to create a blog post for this pin cycle.
Runs AFTER agent_executor. All checks must pass → should_create_blog=True.

Checks (in order):
  1. FIREBASE_CREDS_JSON env var set?
  2. last_posted_image_url present in state?
  3. Per-account daily counter < 5? (check_and_increment_daily_counter)

Note: Runs for ALL pin types (VIRAL_PIN + AFFILIATE_PIN).
      Limit: 5 blogs per account per day = 10 total.
"""

import logging
import os

logger = logging.getLogger(__name__)


def _get_account(trigger: str) -> str:
    """Derive account string from cycle_trigger for per-account counter."""
    if "account2" in trigger and "account1" not in trigger:
        return "account2"
    return "account1"


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

    # ── Check 3: Per-account daily blog limit ─────────────────────────────────
    account = _get_account(state.get("cycle_trigger", ""))
    try:
        from tools.firebase_publisher import check_and_increment_daily_counter
        can_post = await check_and_increment_daily_counter(account=account)
        if not can_post:
            return _skip(f"daily blog limit reached (5/5) for {account}")
    except Exception as e:
        logger.error(f"❌ [BlogTrigger] Counter check failed: {e}")
        return _skip(f"counter check error: {e}")

    logger.info(f"📝 Blog trigger: GO ✅ (account={account})")
    return {**state, "should_create_blog": True}
