"""
tools/board_selector.py

Board selection logic for Pinteresto v3.
Matches image keywords/description to best Pinterest board using:
  1. Groq llama-3.3-70b (primary — fast)
  2. Cerebras qwen-3-235b (fallback)
  3. Keyword overlap scoring (last resort — no API call)
"""

import json
import os
import logging
from openai import OpenAI

logger = logging.getLogger(__name__)

# ── LLM clients (same pattern as rest of codebase) ──────────────────────────

def _get_groq_client():
    return OpenAI(
        api_key=os.environ.get("GROQ_API_KEY"),
        base_url="https://api.groq.com/openai/v1",
    )

def _get_cerebras_client():
    return OpenAI(
        api_key=os.environ.get("CEREBRAS_API_KEY"),
        base_url="https://api.cerebras.ai/v1",
    )

# ── Boards config loader ─────────────────────────────────────────────────────

def _load_boards(account_key: str) -> list[dict]:
    """Load boards for given account from data/boards_config.json."""
    config_path = os.path.join("data", "boards_config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    account_data = config.get(account_key)
    if not account_data:
        raise ValueError(f"[BoardSelector] Account '{account_key}' not found in boards_config.json")

    return account_data["boards"]


# ── Board list formatter (for LLM prompt) ───────────────────────────────────

def _format_boards_for_prompt(boards: list[dict]) -> str:
    """Format boards into a numbered list string for the LLM."""
    lines = []
    for i, board in enumerate(boards, 1):
        lines.append(
            f"{i}. board_id: {board['board_id']}\n"
            f"   name: {board['name']}\n"
            f"   description: {board['description']}"
        )
    return "\n\n".join(lines)


# ── LLM prompt ───────────────────────────────────────────────────────────────

BOARD_SELECTOR_PROMPT = """You are a Pinterest board classifier for a lifestyle & aesthetic content account.

Your task: Select the BEST matching Pinterest board for an image based on its keywords and description.

Image Keywords: {keywords}
Image Description: {description}
Image Style: {style_key}

Available Boards:
{boards_list}

Rules:
- Pick exactly ONE board that best matches the image content
- Base your decision on the image keywords, description, and style
- Return ONLY the board_id value as plain text — no explanation, no quotes, no extra text

board_id:"""


# ── LLM call helpers ─────────────────────────────────────────────────────────

def _call_llm(client: OpenAI, model: str, prompt: str) -> str:
    """Single LLM call, returns stripped board_id string."""
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=50,
        temperature=0.0,  # deterministic — we want consistent board selection
    )
    return response.choices[0].message.content.strip()


# ── Keyword overlap fallback ──────────────────────────────────────────────────

def _keyword_overlap_score(query_text: str, board: dict) -> int:
    """
    Simple word overlap score between query and board description.
    Last resort when all LLM calls fail.
    """
    query_words = set(query_text.lower().split())
    board_words = set(board["description"].lower().split())
    board_words.update(set(board["name"].lower().split()))
    return len(query_words & board_words)


def _fallback_keyword_select(boards: list[dict], keywords: list[str], description: str, style_key: str) -> str:
    """Select board by keyword overlap scoring when LLMs are unavailable."""
    query = " ".join(keywords) + " " + description + " " + style_key
    scores = [(board, _keyword_overlap_score(query, board)) for board in boards]
    best = max(scores, key=lambda x: x[1])
    board_id = best[0]["board_id"]
    board_name = best[0]["name"]
    logger.info(f"[BoardSelector] ⚠️ Keyword fallback selected: '{board_name}' ({board_id})")
    return board_id


# ── Board ID validator ────────────────────────────────────────────────────────

def _validate_board_id(raw_output: str, boards: list[dict]) -> str | None:
    """
    Check if LLM returned a valid board_id.
    Returns the board_id if valid, None if garbage output.
    """
    candidate = raw_output.strip().strip('"').strip("'")
    valid_ids = {b["board_id"] for b in boards}
    if candidate in valid_ids:
        return candidate
    return None


# ── Main public function ──────────────────────────────────────────────────────

def select_board(
    account_key: str,
    board_keywords: list[str],
    description: str,
    style_key: str = "",
) -> tuple[str, str]:
    """
    Select the best Pinterest board for an image.

    Args:
        account_key:     "account_1" or "account_2"
        board_keywords:  List of keywords from CMO output (e.g. ["cozy bedroom", "fairy lights"])
        description:     Pin description from CMO output
        style_key:       Visual style key (e.g. "boho_aesthetic_study")

    Returns:
        (board_id, board_name) tuple
    """
    boards = _load_boards(account_key)

    # Safety: if only 1 board exists, skip LLM entirely
    if len(boards) == 1:
        return boards[0]["board_id"], boards[0]["name"]

    boards_list_str = _format_boards_for_prompt(boards)
    keywords_str = ", ".join(board_keywords)

    prompt = BOARD_SELECTOR_PROMPT.format(
        keywords=keywords_str,
        description=description[:400],   # truncate to keep prompt short
        style_key=style_key,
        boards_list=boards_list_str,
    )

    # ── Attempt 1: Groq ───────────────────────────────────────────────────────
    try:
        logger.info(f"[BoardSelector] Trying Groq for {account_key}...")
        client = _get_groq_client()
        raw = _call_llm(client, "llama-3.3-70b-versatile", prompt)
        board_id = _validate_board_id(raw, boards)

        if board_id:
            board_name = next(b["name"] for b in boards if b["board_id"] == board_id)
            logger.info(f"[BoardSelector] ✅ Groq selected: '{board_name}' ({board_id})")
            return board_id, board_name
        else:
            logger.warning(f"[BoardSelector] Groq returned invalid board_id: '{raw}' — trying Cerebras")

    except Exception as e:
        logger.warning(f"[BoardSelector] Groq failed: {e} — trying Cerebras")

    # ── Attempt 2: Cerebras ───────────────────────────────────────────────────
    try:
        logger.info(f"[BoardSelector] Trying Cerebras for {account_key}...")
        client = _get_cerebras_client()
        raw = _call_llm(client, "qwen-3-235b", prompt)
        board_id = _validate_board_id(raw, boards)

        if board_id:
            board_name = next(b["name"] for b in boards if b["board_id"] == board_id)
            logger.info(f"[BoardSelector] ✅ Cerebras selected: '{board_name}' ({board_id})")
            return board_id, board_name
        else:
            logger.warning(f"[BoardSelector] Cerebras returned invalid board_id: '{raw}' — using keyword fallback")

    except Exception as e:
        logger.warning(f"[BoardSelector] Cerebras failed: {e} — using keyword fallback")

    # ── Attempt 3: Keyword overlap (no API) ───────────────────────────────────
    board_id = _fallback_keyword_select(boards, board_keywords, description, style_key)
    board_name = next(b["name"] for b in boards if b["board_id"] == board_id)
    return board_id, board_name
