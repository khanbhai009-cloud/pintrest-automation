"""
mastermind/graph.py — LangGraph Mastermind CEO Pipeline
Four-node directed graph with strict account isolation:

  [data_intelligence] → [cmo_mastermind] → [fast_copywriters] → [execution_engine] → END

Each node receives and returns the shared MastermindState.
Async-compatible: uses ainvoke() for end-to-end async execution.
"""
import logging

from langgraph.graph import END, StateGraph

from mastermind.node_cmo import node_cmo_mastermind
from mastermind.node_copy import node_fast_copywriters
from mastermind.node_data import node_data_intelligence
from mastermind.node_execute import node_execution_engine
from mastermind.state import MastermindState

logger = logging.getLogger(__name__)


def build_mastermind_graph():
    """Compile and return the Mastermind CEO LangGraph."""
    g = StateGraph(MastermindState)

    g.add_node("data_intelligence", node_data_intelligence)
    g.add_node("cmo_mastermind",    node_cmo_mastermind)
    g.add_node("fast_copywriters",  node_fast_copywriters)
    g.add_node("execution_engine",  node_execution_engine)

    g.set_entry_point("data_intelligence")
    g.add_edge("data_intelligence", "cmo_mastermind")
    g.add_edge("cmo_mastermind",    "fast_copywriters")
    g.add_edge("fast_copywriters",  "execution_engine")
    g.add_edge("execution_engine",  END)

    return g.compile()


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
        "a1_final_seo_copy": {},
        "a2_final_seo_copy": {},
        "a1_publish_status": {},
        "a2_publish_status": {},
        "fallback_triggered": False,
        "cycle_trigger":     trigger,
    }

    try:
        logger.info(f"🧠 MASTERMIND CEO — Starting cycle (trigger={trigger})")
        final = await graph.ainvoke(initial_state)

        a1_pub = final.get("a1_publish_status", {})
        a2_pub = final.get("a2_publish_status", {})
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
            "status":            "ok",
            "summary":           summary,
            "a1_strategy":       a1_strat,
            "a2_strategy":       a2_strat,
            "a1_posted":         a1_pub.get("success", False),
            "a2_posted":         a2_pub.get("success", False),
            "fallback_triggered": final.get("fallback_triggered", False),
        }

    except Exception as e:
        msg = f"❌ Mastermind graph failed: {e}"
        logger.error(msg)
        return {"status": "error", "summary": msg}
