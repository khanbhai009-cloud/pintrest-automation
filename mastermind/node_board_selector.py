"""
mastermind/node_board_selector.py

LangGraph node that selects the correct Pinterest board for a generated pin.
Sits between node_cmo_mastermind and node_agent_executor in the graph.

Graph position:
  node_data_intelligence → node_cmo_mastermind → node_board_selector → node_agent_executor
"""

import logging
from mastermind.state import MastermindState
from tools.board_selector import select_board

logger = logging.getLogger(__name__)


def node_board_selector(state: MastermindState) -> MastermindState:
    """
    Reads board_keywords + description + style_key from state["strategy"],
    calls select_board(), writes board_id and board_name back into strategy.
    """
    account_key = state.get("account_key", "account_1")
    strategy = state.get("strategy", {})

    # ── Extract inputs from CMO output ───────────────────────────────────────
    board_keywords = strategy.get("board_keywords", [])
    description = strategy.get("description", "")
    style_key = strategy.get("visual_style", "")
    title = strategy.get("title", "")

    # If CMO didn't produce board_keywords, build a minimal fallback from title + niche
    if not board_keywords:
        niche = strategy.get("niche", "")
        vibe = strategy.get("vibe", "")
        board_keywords = [w for w in [niche, vibe, style_key] if w]
        logger.warning(
            f"[BoardSelector Node] board_keywords missing from CMO output — "
            f"using fallback keywords: {board_keywords}"
        )

    logger.info(
        f"[BoardSelector Node] Selecting board for {account_key} | "
        f"keywords={board_keywords} | style={style_key}"
    )

    # ── Call board selector ───────────────────────────────────────────────────
    try:
        board_id, board_name = select_board(
            account_key=account_key,
            board_keywords=board_keywords,
            description=description,
            style_key=style_key,
        )

        logger.info(f"[BoardSelector Node] ✅ Board selected: '{board_name}' (id={board_id})")

        # Write back into strategy dict (agent.py reads from here)
        strategy["board_id"] = board_id
        strategy["board_name"] = board_name

    except Exception as e:
        logger.error(f"[BoardSelector Node] ❌ Board selection failed: {e}")
        # Don't abort the pipeline — let agent.py handle missing board_id
        strategy["board_id"] = None
        strategy["board_name"] = None
        state["error"] = f"BoardSelector failed: {e}"

    return {**state, "strategy": strategy}
