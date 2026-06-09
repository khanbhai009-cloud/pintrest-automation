"""
mastermind/node_firebase.py — Firebase Loader Node

Pipeline mein PEHLA node hai.
Firestore se boards + active trends load karta hai dono accounts ke liye.
Firebase unavailable ho to local boards_config.json se load karta hai.
"""
import logging

logger = logging.getLogger(__name__)


async def node_firebase_loader(state: dict) -> dict:
    """
    Node 0 — Local Boards Loader (Firebase removed)
    data_intelligence se PEHLE run hota hai.
    Boards load karta hai from data/boards_config.json via local_boards only.
    """
    logger.info("[Node 0 — LocalBoards] Loading boards for both accounts from local config...")

    a1_boards, a1_trends = {}, {}
    a2_boards, a2_trends = {}, {}

    # ── Load from local boards config only ────────────────────────────────────
    try:
        from tools.local_boards import get_local_boards
        local_a1 = get_local_boards("account_1")
        local_a2 = get_local_boards("account_2")

        if local_a1:
            # Convert list format → dict keyed by board_id for compatibility
            a1_boards = {b["board_id"]: {
                "board_name": b.get("name", ""),
                "board_id": b.get("board_id", ""),
                "description": b.get("description", ""),
                "niche_keywords": [],
                "priority": i,
                "_source": "local",
            } for i, b in enumerate(local_a1)}
            logger.info(f"[LocalBoards] ✅ account_1 — {len(a1_boards)} boards loaded from local config")

        if local_a2:
            a2_boards = {b["board_id"]: {
                "board_name": b.get("name", ""),
                "board_id": b.get("board_id", ""),
                "description": b.get("description", ""),
                "niche_keywords": [],
                "priority": i,
                "_source": "local",
            } for i, b in enumerate(local_a2)}
            logger.info(f"[LocalBoards] ✅ account_2 — {len(a2_boards)} boards loaded from local config")

    except Exception as e:
        logger.warning(f"[LocalBoards] ⚠️ Local boards load failed: {e}")

    return {
        **state,
        "a1_boards":         a1_boards,
        "a2_boards":         a2_boards,
        "a1_trend_keywords": a1_trends,
        "a2_trend_keywords": a2_trends,
    }
