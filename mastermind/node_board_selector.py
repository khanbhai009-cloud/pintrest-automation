"""
mastermind/node_board_selector.py

LangGraph node that selects the correct Pinterest board for each account's pin.
Sits between node_cmo_mastermind and node_agent_executor in the graph.

Graph position:
  node_data_intelligence → node_cmo_mastermind → node_board_selector → node_agent_executor

Reads from : a1_cmo_strategy, a2_cmo_strategy  (set by node_cmo_mastermind)
Writes to  : a1_cmo_strategy["board_id"] + ["board_name"]
             a2_cmo_strategy["board_id"] + ["board_name"]

The agent.py publish_next_pin() then reads strategy["board_id"] and passes it
to tools/make_webhook.py → Pinterest via Make.com.
"""

import logging
from mastermind.state import MastermindState
from tools.board_selector import select_board

logger = logging.getLogger(__name__)


# ── Keyword extraction ────────────────────────────────────────────────────────

def _build_board_keywords(strategy: dict) -> list:
    """
    Build a deduplicated keyword list from the actual CMO strategy dict keys.

    CMO output keys we use (in priority order):
      board_keywords  → list already produced by CMO (may exist)
      tags            → list like ["Cottagecore", "FloralFacade", "DreamHome"]
      niche           → string like "home" or "garden" (single niche chosen by CMO)
      visual_style    → string like "charming_flower_cottage"
      description     → sensory copy (passed raw to select_board for context)
    """
    # 1. CMO-provided board_keywords (best signal — use first)
    board_kw = strategy.get("board_keywords", [])
    if isinstance(board_kw, str):
        board_kw = [k.strip() for k in board_kw.split(",") if k.strip()]
    base = list(board_kw[:4]) if isinstance(board_kw, list) else []

    # 2. Tags (CamelCase Pinterest tags — strong semantic signal)
    tags = strategy.get("tags", [])
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    tags = tags[:3] if isinstance(tags, list) else []

    # 3. Niche — CMO writes a single string (e.g. "home", "cozy", "garden")
    #    may also be comma-separated if CMO returned niche_affinity-style
    niche_raw = strategy.get("niche", "") or strategy.get("niche_affinity", "")
    niche_tokens = [n.strip() for n in niche_raw.split(",") if n.strip()][:3]

    # 4. Visual style key (e.g. "charming_flower_cottage")
    style = strategy.get("visual_style", "") or strategy.get("style_key", "")

    # Merge → deduplicate → drop empties
    combined = base + tags + niche_tokens + ([style] if style else [])
    seen = set()
    keywords = []
    for k in combined:
        k = str(k).strip()
        if k and k not in seen:
            seen.add(k)
            keywords.append(k)

    return keywords


# ── Per-account board selection ───────────────────────────────────────────────

def _select_for_account(strategy: dict, account_key: str) -> dict:
    """
    Run board selection for one account.
    Returns a copy of strategy with board_id + board_name injected.
    Never raises — on failure writes None values and logs error.
    """
    if not strategy:
        return strategy

    board_keywords = _build_board_keywords(strategy)
    description    = strategy.get("description", "")
    style_key      = strategy.get("visual_style", "") or strategy.get("style_key", "")

    logger.info(
        f"[BoardSelector] {account_key} | style={style_key} | "
        f"keywords={board_keywords}"
    )

    try:
        board_id, board_name = select_board(
            account_key=account_key,
            board_keywords=board_keywords,
            description=description,
            style_key=style_key,
        )
        logger.info(
            f"[BoardSelector] ✅ {account_key} → '{board_name}' (id={board_id})"
        )
        return {**strategy, "board_id": board_id, "board_name": board_name}

    except Exception as e:
        logger.error(f"[BoardSelector] ❌ {account_key} board selection failed: {e}")
        return {**strategy, "board_id": None, "board_name": None}


# ── LangGraph node ────────────────────────────────────────────────────────────

async def node_board_selector(state: MastermindState) -> dict:
    """
    Node 3 — Board Selector.

    Determines which accounts are active from cycle_trigger, then selects
    the best Pinterest board for each active account's pin.

    board_id + board_name are written into the per-account strategy dicts so
    agent.py → publish_next_pin() → make_webhook.py can route the pin correctly.
    """
    trigger = state.get("cycle_trigger", "")
    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    logger.info(
        f"[BoardSelector Node] trigger={trigger} | "
        f"run_a1={run_a1} run_a2={run_a2}"
    )

    a1_strategy = dict(state.get("a1_cmo_strategy") or {})
    a2_strategy = dict(state.get("a2_cmo_strategy") or {})

    if run_a1 and a1_strategy:
        a1_strategy = _select_for_account(a1_strategy, "account_1")
    elif run_a1:
        logger.warning("[BoardSelector Node] A1 skipped — a1_cmo_strategy is empty")

    if run_a2 and a2_strategy:
        a2_strategy = _select_for_account(a2_strategy, "account_2")
    elif run_a2:
        logger.warning("[BoardSelector Node] A2 skipped — a2_cmo_strategy is empty")

    return {
        "a1_cmo_strategy": a1_strategy,
        "a2_cmo_strategy": a2_strategy,
    }
