"""
mastermind/state.py
Strict isolated state for Account 1 (HomeDecor) and Account 2 (Tech).
Zero cross-contamination by design — each account has its own analytics,
CMO strategy, SEO copy, and publish status fields.

V4 additions: blog pipeline fields (should_create_blog → blog_published)
"""
from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class MastermindState(TypedDict):
    # ── Account 1 — HomeDecor (home, kitchen, cozy, gadgets, organize) ────
    a1_raw_analytics:  List[Dict[str, Any]]
    a1_cmo_strategy:   Dict[str, Any]
    a1_final_seo_copy: Dict[str, Any]
    a1_publish_status: Dict[str, Any]

    # ── Account 2 — Tech (tech, budget, phone, smarthome, wfh) ───────────
    a2_raw_analytics:  List[Dict[str, Any]]
    a2_cmo_strategy:   Dict[str, Any]
    a2_final_seo_copy: Dict[str, Any]
    a2_publish_status: Dict[str, Any]

    # ── Global pipeline flags ────────────────────────────────────────────
    fallback_triggered:   bool
    cycle_trigger:        str

    # ── V4 Blog Pipeline fields ───────────────────────────────────────────
    last_posted_image_url: Optional[str]   # ImgBB URL set by agent after pin post
    should_create_blog:    Optional[bool]  # node_blog_trigger decision
    blog_products:         Optional[List[Dict[str, Any]]]  # node_product_researcher
    blog_content:          Optional[Dict[str, Any]]        # node_blog_writer
    blog_url:              Optional[str]   # node_firebase_publisher result
    blog_published:        Optional[bool]  # True if Firebase save succeeded
    force_blog:            Optional[bool]  # bypass daily blog limit when True
