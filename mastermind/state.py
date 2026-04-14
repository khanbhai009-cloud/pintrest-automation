"""
mastermind/state.py
Strict isolated state for Account 1 (HomeDecor) and Account 2 (Tech).
Zero cross-contamination by design — each account has its own analytics,
CMO strategy, SEO copy, and publish status fields.
"""
from typing import Any, Dict, List
from typing_extensions import TypedDict


class MastermindState(TypedDict):
    # ── Account 1 — HomeDecor (home, kitchen, cozy, gadgets, organize) ────
    a1_raw_analytics: List[Dict[str, Any]]
    a1_cmo_strategy:  Dict[str, Any]
    a1_final_seo_copy: Dict[str, Any]
    a1_publish_status: Dict[str, Any]

    # ── Account 2 — Tech (tech, budget, phone, smarthome, wfh) ───────────
    a2_raw_analytics: List[Dict[str, Any]]
    a2_cmo_strategy:  Dict[str, Any]
    a2_final_seo_copy: Dict[str, Any]
    a2_publish_status: Dict[str, Any]

    # ── Global pipeline flags ────────────────────────────────────────────
    fallback_triggered: bool
    cycle_trigger: str
