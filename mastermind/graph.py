"""
mastermind/graph.py — LangGraph Mastermind CEO Pipeline
Three-node directed graph:

  [data_intelligence] → [cmo_mastermind] → [agent_executor] → END

Blog pipeline runs INLINE inside publish_next_pin (agent.py):
  Image created → Vision AI → Blog written → Firebase → blog_url
  → Pinterest post WITH blog_url as destination link

Manual blog triggers (dashboard buttons) use _run_blog_pipeline() in main.py.

CMO engine  : Cerebras qwen-3-235b-a22b-instruct-2507
Exec engine : Groq llama-3.3-70b-versatile (Cerebras fallback)
Blog engine : Gemini 2.5 Flash (writer + vision) + Firebase Firestore
"""
import logging

from langgraph.graph import END, StateGraph

from mastermind.node_firebase import node_firebase_loader
from mastermind.node_cmo import node_cmo_mastermind
from mastermind.node_data import node_data_intelligence
from mastermind.node_board_selector import node_board_selector
from mastermind.state import MastermindState
from agent import run_agent

logger = logging.getLogger(__name__)


# ── Node: Agent Executor ──────────────────────────────────────────────────────

async def node_agent_executor(state: MastermindState) -> dict:
    """
    Node 3 — Agent Executor.
    Checks cycle_trigger to decide which account(s) to run:
      - "account1" in trigger (no "account2") → only Account 1
      - "account2" in trigger (no "account1") → only Account 2
      - otherwise (both/manual/scheduled)     → both accounts sequentially

    Blog pipeline now runs INSIDE publish_next_pin (inline), so this node
    only needs to handle the agent execution and capture the result.
    """
    trigger     = state.get("cycle_trigger", "")
    a1_strategy = state.get("a1_cmo_strategy", {})
    a2_strategy = state.get("a2_cmo_strategy", {})

    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    logger.info(
        f"🤖 [Node 3 — Agent Executor] trigger={trigger} | "
        f"run_a1={run_a1} run_a2={run_a2}"
    )

    SKIPPED = {"status": "skipped", "summary": "Skipped — not in this trigger", "last_posted_image_url": ""}
    last_image_url = ""

    # ── Account 1 ──────────────────────────────────────────────────────────────
    if run_a1 and a1_strategy:
        logger.info(f"▶️  [Agent Executor] Running Account 1 | Strategy: {a1_strategy.get('strategy')}")
        a1_result = await run_agent(trigger="account1", cmo_strategy=a1_strategy)
        if a1_result.get("last_posted_image_url"):
            last_image_url = a1_result["last_posted_image_url"]
    else:
        logger.info("⏭️  [Agent Executor] Account 1 — SKIPPED")
        a1_result = SKIPPED

    # ── Account 2 ──────────────────────────────────────────────────────────────
    if run_a2 and a2_strategy:
        logger.info(f"▶️  [Agent Executor] Running Account 2 | Strategy: {a2_strategy.get('strategy')}")
        a2_result = await run_agent(trigger="account2", cmo_strategy=a2_strategy)
        if a2_result.get("last_posted_image_url"):
            last_image_url = a2_result["last_posted_image_url"]
    else:
        logger.info("⏭️  [Agent Executor] Account 2 — SKIPPED")
        a2_result = SKIPPED

    logger.info(f"✅ [Agent Executor] A1: {a1_result.get('status')} | A2: {a2_result.get('status')}")

    return {
        "a1_publish_status": {
            "success": a1_result.get("status") == "ok",
            "message": a1_result.get("summary", "")[:200],
        },
        "a2_publish_status": {
            "success": a2_result.get("status") == "ok",
            "message": a2_result.get("summary", "")[:200],
        },
        "last_posted_image_url": last_image_url,
    }


# ── Graph Builder ─────────────────────────────────────────────────────────────

def build_mastermind_graph():
    """Compile and return the Mastermind CEO LangGraph (4-node pipeline)."""
    g = StateGraph(MastermindState)

    g.add_node("firebase_loader",   node_firebase_loader)
    g.add_node("data_intelligence", node_data_intelligence)
    g.add_node("cmo_mastermind",    node_cmo_mastermind)
    g.add_node("board_selector",    node_board_selector)
    g.add_node("agent_executor",    node_agent_executor)

    g.set_entry_point("firebase_loader")
    g.add_edge("firebase_loader",   "data_intelligence")
    g.add_edge("data_intelligence", "cmo_mastermind")
    g.add_edge("cmo_mastermind",    "board_selector")
    g.add_edge("board_selector",    "agent_executor")
    g.add_edge("agent_executor",    END)

    return g.compile()


# ── Entry Point ───────────────────────────────────────────────────────────────

async def run_mastermind(trigger: str = "scheduled", force_blog: bool = False) -> dict:
    """
    Entry-point for the Mastermind CEO pipeline.

    Args:
        trigger: descriptive label (e.g. "manual", "scheduled", "account1-only")

    Returns:
        dict with keys: status, summary, a1_strategy, a2_strategy,
                        a1_posted, a2_posted, fallback_triggered,
                        blog_published (set by inline pipeline in agent), blog_url
    """
    graph = build_mastermind_graph()

    initial_state: MastermindState = {
        "a1_raw_analytics":  [],
        "a2_raw_analytics":  [],
        "a1_cmo_strategy":   {},
        "a2_cmo_strategy":   {},
        "a1_final_seo_copy": {},
        "a2_final_seo_copy": {},
        "a1_publish_status": {},
        "a2_publish_status": {},
        "fallback_triggered": False,
        "cycle_trigger":     trigger,
        # Blog fields — populated inline by publish_next_pin, kept for manual triggers
        "last_posted_image_url": "",
        "should_create_blog":    False,
        "blog_products":         [],
        "blog_content":          {},
        "blog_url":              "",
        "blog_published":        False,
        "force_blog":            force_blog,
        # V5 Firebase board routing — populated by node_firebase_loader
        "a1_boards":         {},
        "a2_boards":         {},
        "a1_trend_keywords": {},
        "a2_trend_keywords": {},
        # V5 board selection — populated by node_board_selector
        "board_id":          None,
        "board_name":        None,
    }

    try:
        logger.info(f"🧠 MASTERMIND CEO — Starting cycle (trigger={trigger})")
        final = await graph.ainvoke(initial_state)

        a1_pub   = final.get("a1_publish_status", {})
        a2_pub   = final.get("a2_publish_status", {})
        a1_strat = final.get("a1_cmo_strategy", {}).get("strategy", "N/A")
        a2_strat = final.get("a2_cmo_strategy", {}).get("strategy", "N/A")

        a1_icon = "✅" if a1_pub.get("success") else "❌"
        a2_icon = "✅" if a2_pub.get("success") else "❌"

        summary = (
            f"🧠 MASTERMIND CEO CYCLE COMPLETE\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Account 1 (HomeDecor)\n"
            f"  Strategy : {a1_strat}\n"
            f"  Result   : {a1_icon} {a1_pub.get('message', 'N/A')}\n"
            f"Account 2 (Tech)\n"
            f"  Strategy : {a2_strat}\n"
            f"  Result   : {a2_icon} {a2_pub.get('message', 'N/A')}\n"
            f"Blog       : inline via publish_next_pin\n"
            f"Fallback   : {'⚠️ Yes' if final.get('fallback_triggered') else 'No'}\n"
            f"Trigger    : {trigger}"
        )

        logger.info(f"\n{summary}")

        return {
            "status":             "ok",
            "summary":            summary,
            "a1_strategy":        a1_strat,
            "a2_strategy":        a2_strat,
            "a1_posted":          a1_pub.get("success", False),
            "a2_posted":          a2_pub.get("success", False),
            "fallback_triggered": final.get("fallback_triggered", False),
            "blog_published":     False,   # tracked per-pin in agent logs
            "blog_url":           "",
        }

    except Exception as e:
        msg = f"❌ Mastermind graph failed: {e}"
        logger.error(msg)
        return {"status": "error", "summary": msg}
