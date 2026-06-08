"""
tools/firebase_boards.py — Firestore Board Routing + Trend Keyword Engine

Collections:
  boards/{account}/items/{niche_key}  — Pinterest board metadata + keywords
  trends/{account}/items/{niche_key}  — Active trend keywords with expiry (ms)

Auth: reuses FIREBASE_CREDS_JSON from config (same credential as firebase_publisher.py)
"""
import json
import logging
import time

from config import FIREBASE_CREDS_JSON

logger = logging.getLogger(__name__)

_db = None


def _get_db():
    """Lazy singleton — reuses existing firebase_admin app if already initialised."""
    global _db
    if _db is not None:
        return _db
    if not FIREBASE_CREDS_JSON:
        raise ValueError("FIREBASE_CREDS_JSON not set — cannot connect to Firestore.")
    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            creds_dict = json.loads(FIREBASE_CREDS_JSON)
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred)

        _db = firestore.client()
        return _db
    except Exception as e:
        raise RuntimeError(f"Firebase init failed: {e}") from e


# ── Boards ─────────────────────────────────────────────────────────────────────

def get_boards(account: str) -> dict:
    """
    Firestore se active boards fetch karo, priority order mein.
    Collection: boards/{account}/items/*
    Returns: {niche_key: {board_name, board_id, description, niche_keywords, priority, ...}}
    """
    db = _get_db()
    docs = db.collection("boards").document(account).collection("items").stream()
    boards = {}
    for doc in docs:
        data = doc.to_dict()
        if data.get("active", True):
            boards[doc.id] = data
    return dict(sorted(boards.items(), key=lambda x: x[1].get("priority", 99)))


def get_all_active_trends(account: str) -> dict:
    """
    Saare active trend keyword sets fetch karo.
    Collection: trends/{account}/items/*
    Expired entries skip ho jaate hain (expires_at ms format).
    Returns: {niche_key: ["kw1", "kw2", ...]}
    """
    db = _get_db()
    docs = db.collection("trends").document(account).collection("items").stream()
    now = time.time() * 1000
    result = {}
    for doc in docs:
        data = doc.to_dict()
        if data.get("expires_at", 0) > now and data.get("keywords"):
            result[doc.id] = data["keywords"]
    return result


# ── Formatters for LLM prompt injection ───────────────────────────────────────

def format_boards_for_prompt(boards: dict) -> str:
    """Boards ko AI-readable format mein convert karo."""
    if not boards:
        return "No boards configured in Firestore — niche-based board routing will be used."
    lines = []
    for niche_key, board in boards.items():
        kws = ", ".join(board.get("niche_keywords", []))
        lines.append(
            f"[{niche_key}] \"{board.get('board_name', niche_key)}\"\n"
            f"  Board ID  : {board.get('board_id', 'MISSING')}\n"
            f"  About     : {board.get('description', 'N/A')}\n"
            f"  Keywords  : {kws}\n"
            f"  Priority  : {board.get('priority', 99)}"
        )
    return "\n\n".join(lines)


def format_trends_for_prompt(trends: dict) -> str:
    """Active trends ko AI-readable format mein convert karo."""
    if not trends:
        return "No active trend keywords this week — use board niche_keywords instead."
    lines = []
    for niche_key, keywords in trends.items():
        lines.append(f"  [{niche_key}]: {', '.join(keywords[:10])}")
    return "\n".join(lines)
