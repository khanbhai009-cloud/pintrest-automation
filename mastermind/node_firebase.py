"""
mastermind/node_firebase.py — Firebase Loader Node

Pipeline mein PEHLA node hai.
Firestore se boards + active trends load karta hai dono accounts ke liye.
Firebase unavailable ho to empty dicts se gracefully continue karta hai.
"""
import logging

logger = logging.getLogger(__name__)


async def node_firebase_loader(state: dict) -> dict:
    """
    Node 0 — Firebase Loader
    data_intelligence se PEHLE run hota hai.
    Boards + trends load karta hai; failures pipeline rok nahi sakti.
    """
    logger.info("[Node 0 — Firebase] Loading boards + trends for both accounts...")

    a1_boards, a1_trends = {}, {}
    a2_boards, a2_trends = {}, {}

    try:
        from tools.firebase_boards import get_boards, get_all_active_trends

        # Account 1 — HomeDecor
        try:
            a1_boards = get_boards("account_1")
            a1_trends = get_all_active_trends("account_1")
            logger.info(
                f"[Firebase] ✅ account_1 — {len(a1_boards)} boards, "
                f"{len(a1_trends)} active trend sets"
            )
        except Exception as e:
            logger.warning(f"[Firebase] ⚠️ account_1 load failed: {type(e).__name__}: {e}")

        # Account 2 — Tech
        try:
            a2_boards = get_boards("account_2")
            a2_trends = get_all_active_trends("account_2")
            logger.info(
                f"[Firebase] ✅ account_2 — {len(a2_boards)} boards, "
                f"{len(a2_trends)} active trend sets"
            )
        except Exception as e:
            logger.warning(f"[Firebase] ⚠️ account_2 load failed: {type(e).__name__}: {e}")

    except ImportError as e:
        logger.warning(f"[Firebase] firebase_boards import failed: {e} — continuing without boards.")

    return {
        **state,
        "a1_boards":         a1_boards,
        "a2_boards":         a2_boards,
        "a1_trend_keywords": a1_trends,
        "a2_trend_keywords": a2_trends,
    }
