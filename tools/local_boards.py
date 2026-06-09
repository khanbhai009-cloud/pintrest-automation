"""
tools/local_boards.py — Local Board Config Storage

New JSON format:
{
  "account_1": {
    "boards": [
      {"board_id": "...", "name": "...", "description": "..."}
    ]
  },
  "account_2": {
    "boards": [...]
  }
}

Saved to: data/boards_config.json
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

BOARDS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "boards_config.json")
BOARDS_FILE = os.path.normpath(BOARDS_FILE)


def load_boards_config() -> dict:
    """Load boards config from local JSON file."""
    try:
        if os.path.exists(BOARDS_FILE):
            with open(BOARDS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"[LocalBoards] Could not load boards_config.json: {e}")
    return {}


def save_boards_config(data: dict) -> bool:
    """Save boards config to local JSON file. Returns True on success."""
    try:
        os.makedirs(os.path.dirname(BOARDS_FILE), exist_ok=True)
        with open(BOARDS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"[LocalBoards] Saved boards config to {BOARDS_FILE}")
        return True
    except Exception as e:
        logger.error(f"[LocalBoards] Save failed: {e}")
        return False


def get_local_boards(account: str) -> list:
    """
    Return boards list for given account.
    Each item: {"board_id": "...", "name": "...", "description": "..."}
    """
    config = load_boards_config()
    acc = config.get(account, {})
    return acc.get("boards", [])


def format_boards_for_prompt(boards_list: list) -> str:
    """
    Format board list for AI prompt injection.
    Input: [{"board_id": "...", "name": "...", "description": "..."}, ...]
    """
    if not boards_list:
        return "No boards configured — niche-based board routing will be used."
    lines = []
    for i, board in enumerate(boards_list, 1):
        lines.append(
            f"[{i}] \"{board.get('name', 'Unnamed')}\"\n"
            f"  Board ID  : {board.get('board_id', 'MISSING')}\n"
            f"  About     : {board.get('description', 'N/A')}"
        )
    return "\n\n".join(lines)


def get_boards_status() -> dict:
    """Return a summary dict of current local boards for the API status endpoint."""
    config = load_boards_config()
    result = {}
    for acc_key in ["account_1", "account_2"]:
        boards = config.get(acc_key, {}).get("boards", [])
        result[acc_key] = {
            "count": len(boards),
            "boards": [
                {"board_id": b.get("board_id", ""), "name": b.get("name", "")}
                for b in boards
            ],
        }
    return result
