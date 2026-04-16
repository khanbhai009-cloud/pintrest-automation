"""
mastermind/graph.py — LangGraph Mastermind CEO Pipeline
Two-node directed graph — CMO decides, agent.py executes:

  [data_intelligence] → [cmo_mastermind] → [agent_executor] → END

Node 3 (fast_copywriters) and Node 4 (execution_engine) are REMOVED.
The CMO strategy is passed directly to agent.py (run_agent), which has
all the tools to execute the full pipeline end-to-end.
"""
import logging

from langgraph.graph import END, StateGraph

from mastermind.node_cmo import node_cmo_mastermind
from mastermind.node_data import node_data_intelligence
from mastermind.state import MastermindState
from agent import run_agent  # agent.py's entry point

logger = logging.getLogger(__name__)


# ── Node: Agent Executor ──────────────────────────────────────────────────────

async def node_agent_executor(state: MastermindState) -> dict:
    """
    Node 3 — Agent Executor.
    Checks cycle_trigger to decide which account(s) to run:
      - "account1" in trigger (no "account2") → only Account 1
      - "account2" in trigger (no "account1") → only Account 2
      - otherwise (both/manual/scheduled)     → both accounts sequentially
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

    SKIPPED = {"status": "skipped", "summary": "Skipped — not in this trigger"}

    # ── Account 1 ──────────────────────────────────────────────────────────────
    if run_a1 and a1_strategy:
        logger.info(f"▶️  [Agent Executor] Running Account 1 | Strategy: {a1_strategy.get('strategy')}")
        a1_result = await run_agent(trigger="account1", cmo_strategy=a1_strategy)
    else:
        logger.info("⏭️  [Agent Executor] Account 1 — SKIPPED")
        a1_result = SKIPPED

    # ── Account 2 ──────────────────────────────────────────────────────────────
    if run_a2 and a2_strategy:
        logger.info(f"▶️  [Agent Executor] Running Account 2 | Strategy: {a2_strategy.get('strategy')}")
        a2_result = await run_agent(trigger="account2", cmo_strategy=a2_strategy)
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
    }


# ── Graph Builder ─────────────────────────────────────────────────────────────

def build_mastermind_graph():
    """Compile and return the Mastermind CEO LangGraph (2-node pipeline)."""
    g = StateGraph(MastermindState)

    g.add_node("data_intelligence", node_data_intelligence)
    g.add_node("cmo_mastermind",    node_cmo_mastermind)
    g.add_node("agent_executor",    node_agent_executor)   # replaces node 3 + 4

    g.set_entry_point("data_intelligence")
    g.add_edge("data_intelligence", "cmo_mastermind")
    g.add_edge("cmo_mastermind",    "agent_executor")      # strategy goes straight to agent
    g.add_edge("agent_executor",    END)

    return g.compile()


# ── Entry Point ───────────────────────────────────────────────────────────────

async def run_mastermind(trigger: str = "scheduled") -> dict:
    """
    Entry-point for the Mastermind CEO pipeline.

    Args:
        trigger: descriptive label (e.g. "manual", "scheduled", "account1-only")

    Returns:
        dict with keys: status, summary, a1_strategy, a2_strategy,
                        a1_posted, a2_posted, fallback_triggered
    """
    graph = build_mastermind_graph()

    initial_state: MastermindState = {
        "a1_raw_analytics":  [],
        "a2_raw_analytics":  [],
        "a1_cmo_strategy":   {},
        "a2_cmo_strategy":   {},
        "a1_final_seo_copy": {},   # kept in state schema for compatibility
        "a2_final_seo_copy": {},   # (not written anymore — agent handles copy internally)
        "a1_publish_status": {},
        "a2_publish_status": {},
        "fallback_triggered": False,
        "cycle_trigger":     trigger,
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
        }

    except Exception as e:
        msg = f"❌ Mastermind graph failed: {e}"
        logger.error(msg)
        return {"status": "error", "summary": msg}
