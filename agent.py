"""
agent.py — Pinteresto Visual Agent (Production v5 — 100% Visual Strategy)

LangGraph StateGraph architecture with:
  - 100% VIRAL_PIN — no affiliate links, no product sourcing
  - CMO strategy injected: visual_style, visual_prompt, title, description, tags
  - generate_pin_image() for every post (OpenRouter FLUX -> Pollinations fallback)
  - ImgBB mandatory hosting gateway before every Pinterest webhook call

run_agent() accepts cmo_strategy dict from the Mastermind graph.
analyze_niche_stock and fetch_aliexpress_products are kept in code but NOT registered
as agent tools — they will not be called until re-enabled.

CMO Mastermind: Gemini 2.5 Flash -> Cerebras fallback
Execution Agent: Groq (llama-3.3-70b-versatile) with Cerebras fallback
"""

import asyncio
import logging
import os
import random
import time
from typing import Annotated, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict
from tools.image_creator import generate_pin_image, upload_raw_image
from config import (
    CEREBRAS_API_KEY,
    CEREBRAS_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
)
from tools.admitad import enrich_with_affiliate_link
from tools.aliexpress import DEFAULT_KEYWORDS, KEYWORDS_BY_NICHE, search_products
from tools.google_drive import (
    count_pending,
    get_pending_products,
    get_products_without_niche,
    mark_as_posted,
    save_products,
    update_niche,
)
from tools.groq_ai import filter_product, generate_pin_copy
from tools.llm import chat
from tools.make_webhook import post_to_pinterest

# ── Explicit environment key loading ─────────────────────────────────────────
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")

logger = logging.getLogger(__name__)

# Global trigger — set at the start of each run_agent() call
CURRENT_TRIGGER: Optional[str] = None

# Global CMO strategy — injected by Mastermind graph, consumed by publish_next_pin
CURRENT_CMO_STRATEGY: Optional[dict] = None


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph State
# ─────────────────────────────────────────────────────────────────────────────

class BotState(TypedDict):
    messages:     Annotated[list, add_messages]
    posted_count: int
    refilled:     bool
    errors:       list[str]


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph Tools
# ─────────────────────────────────────────────────────────────────────────────

@tool
def fill_missing_niches() -> dict:
    """
    Scan Google Sheet for products with an empty niche column and classify them
    using the LLM. Call this at the very start of every pipeline cycle.
    """
    products = get_products_without_niche()
    if not products:
        return {"updated": 0, "message": "All products already have niche set ✅"}

    VALID_NICHES = [
        "home", "kitchen", "cozy", "gadgets", "organize",
        "tech", "budget", "phone", "smarthome", "wfh",
    ]
    updated = 0
    for p in products:
        name = p.get("product_name", "")
        prompt = (
            f"You are a product categorization expert. "
            f"Product: {name}. "
            f"Available niches: {VALID_NICHES}. "
            f"Respond with ONLY the single best matching niche, lowercase, no punctuation."
        )
        try:
            niche = chat(prompt, temperature=0.1).strip().lower()
            if niche not in VALID_NICHES:
                niche = "home"
            update_niche(name, niche)
            updated += 1
            time.sleep(2.5)
        except Exception as e:
            logger.error(f"❌ Niche classification failed for '{name}': {e}")
            time.sleep(2.5)

    return {"updated": updated, "message": f"✅ {updated} niches filled"}


@tool
def analyze_niche_stock() -> dict:
    """
    Check stock levels for the active account's niches.
    Returns selected_niche, stock_count, and needs_fetching flag.
    If needs_fetching is True you MUST call fetch_aliexpress_products() before publishing.
    """
    global CURRENT_TRIGGER
    allowed_niches = (
        ["home", "kitchen", "cozy", "gadgets", "organize"]
        if "account1" in str(CURRENT_TRIGGER)
        else ["tech", "budget", "phone", "smarthome", "wfh"]
    )
    total_pending = count_pending()
    pending_all   = get_pending_products(limit=200, allowed_niches=allowed_niches)

    stock_map = {n: 0 for n in allowed_niches}
    for p in pending_all:
        if p.get("niche") in stock_map:
            stock_map[p.get("niche")] += 1

    if total_pending > 150:
        available = [n for n, c in stock_map.items() if c > 0]
        chosen    = random.choice(available) if available else random.choice(allowed_niches)
        return {
            "selected_niche": chosen,
            "stock_count":    stock_map.get(chosen, 0),
            "needs_fetching": False,
        }

    chosen = random.choice(allowed_niches)
    return {
        "selected_niche": chosen,
        "stock_count":    stock_map[chosen],
        "needs_fetching": stock_map[chosen] == 0,
    }


@tool
async def fetch_aliexpress_products(niche: str, keyword: str = "") -> dict:
    """
    Fetch trending Amazon affiliate products for the selected niche and save them
    to the Google Sheet. Call this ONLY when analyze_niche_stock() returns
    needs_fetching=True — never skip the refill step.
    """
    keywords_to_try = (
        [keyword] if keyword
        else random.sample(KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS), 2)
    )

    for kw in keywords_to_try:
        logger.info(f"🛒 [Fetch] Niche='{niche}' Keyword='{kw}'")
        raw = await search_products(keyword=kw, max_results=20, niche=niche)
        if not raw:
            continue
        linked   = [enrich_with_affiliate_link(p) for p in raw]
        approved = [p for p in linked if filter_product(p)]
        if approved:
            for p in approved:
                p["niche"] = niche
            save_products(approved)
            return {
                "keyword":  kw,
                "niche":    niche,
                "fetched":  len(raw),
                "approved": len(approved),
            }

    return {"approved": 0, "fetched": 0, "error": "All fetch attempts failed."}


@tool
async def publish_next_pin(visual_style: str) -> dict:
    """
    Generate and publish a 100% VIRAL_PIN for the given visual style.

    No product sourcing, no affiliate links — purely AI-generated aesthetic imagery.
    CMO-generated title, description, tags, visual_prompt, and ratio are read from
    the injected CURRENT_CMO_STRATEGY global.

    Args:
        visual_style: one of green_minimalist | sunset_landscape | cozy_architecture | cinematic_retro
    """
    global CURRENT_TRIGGER, CURRENT_CMO_STRATEGY

    target_account = (
        "Account1_HomeDecor"
        if "account1" in str(CURRENT_TRIGGER)
        else "Account2_Tech"
    )

    # ── 1. Read CMO strategy ─────────────────────────────────────────────────
    cmo           = CURRENT_CMO_STRATEGY or {}
    visual_prompt = str(cmo.get("visual_prompt", ""))
    ratio         = cmo.get("ratio", "9:16")
    title         = str(cmo.get("title", "Aesthetic Inspiration"))[:100]
    desc          = str(cmo.get("description", ""))
    tags          = list(cmo.get("tags", []))
    alt_text      = str(cmo.get("alt_text", ""))

    if not visual_prompt:
        visual_prompt = (
            f"aesthetic {visual_style.replace('_', ' ')} photography, "
            "ultra-realistic, 4K ultra HD, photorealistic, highly detailed"
        )

    logger.info(
        f"[{target_account}] VIRAL_PIN | style={visual_style} | ratio={ratio} | "
        f"prompt={visual_prompt[:60]}..."
    )

    # ── 2. Generate AI image (OpenRouter -> Pollinations fallback) ────────────
    imgbb_url = await generate_pin_image(visual_prompt=visual_prompt, ratio=ratio)
    if not imgbb_url:
        return {"success": False, "reason": "Image generation failed — all layers exhausted."}

    # ── 3. Post to Pinterest via Make.com webhook — no affiliate link ─────────
    # Extract niche from CMO strategy (if available, else default to visual_style as fallback)
    niche = cmo.get("niche", visual_style)
    
    try:
        success = await post_to_pinterest(
            image_url=imgbb_url,
            title=title,
            description=desc,
            link="",          # No affiliate links — 100% visual strategy
            tags=tags,
            niche=niche,
            target_account=target_account,
            alt_text=alt_text,
        )
    except Exception as e:
        return {"success": False, "reason": f"Webhook error: {e}"}

    if success:
        return {
            "success":      True,
            "visual_style": visual_style,
            "pin_type":     "VIRAL_PIN",
            "image_url":    imgbb_url,
        }

    return {"success": False, "reason": "Webhook returned failure status."}


# ─────────────────────────────────────────────────────────────────────────────
# Tool Registry & LLM
# ─────────────────────────────────────────────────────────────────────────────

# analyze_niche_stock and fetch_aliexpress_products are kept in code above
# but NOT registered here — product sourcing disabled until further notice.
ALL_TOOLS = [fill_missing_niches, publish_next_pin]


def _build_llm():
    primary  = ChatGroq(
        api_key=GROQ_API_KEY or "placeholder",
        model=GROQ_MODEL,
        temperature=0.1,
    ).bind_tools(ALL_TOOLS)
    fallback = ChatOpenAI(
        api_key=CEREBRAS_API_KEY or "placeholder",
        base_url="https://api.cerebras.ai/v1",
        model=CEREBRAS_MODEL,
        temperature=0.1,
    ).bind_tools(ALL_TOOLS)
    return primary.with_fallbacks([fallback])


llm = _build_llm()


# ─────────────────────────────────────────────────────────────────────────────
# System Prompt Builder — CMO Strategy Injected Here
# ─────────────────────────────────────────────────────────────────────────────

def _build_system_prompt(cmo_strategy: Optional[dict] = None) -> str:
    """
    Build the agent system prompt.

    If `cmo_strategy` is provided (from Mastermind graph), inject the pin_type,
    title, description, tags, and visual_prompt so the agent uses them directly.

    If `cmo_strategy` is None (standalone run), keep an open-ended prompt.
    """
    if cmo_strategy:
        visual_style  = cmo_strategy.get("visual_style", "green_minimalist")
        strategy      = cmo_strategy.get("strategy", "Visual Style Pivot")
        vibe          = cmo_strategy.get("vibe", "")
        title         = cmo_strategy.get("title", "")
        description   = cmo_strategy.get("description", "")
        tags          = cmo_strategy.get("tags", [])
        visual_prompt = cmo_strategy.get("visual_prompt", "")
        ratio         = cmo_strategy.get("ratio", "9:16")

        cmo_brief = f"""
CMO MASTERMIND BRIEF — FOLLOW THIS EXACTLY
  PIN TYPE      : VIRAL_PIN (100% visual — no products, no affiliate links)
  STRATEGY      : {strategy}
  VISUAL STYLE  : {visual_style}
  VIBE          : {vibe}
  TITLE         : {title}
  DESCRIPTION   : {description}
  TAGS          : {tags}
  VISUAL PROMPT : {visual_prompt}
  RATIO         : {ratio}
publish_next_pin() reads the full CMO strategy automatically — pass the visual_style above.
"""
    else:
        visual_style = "green_minimalist"
        cmo_brief = """
STANDALONE MODE — No CMO strategy injected.
publish_next_pin() will use a default green_minimalist visual style.
"""

    return f"""You are PINTERESTO — an autonomous Pinterest visual content agent.
{cmo_brief}
SYSTEM ARCHITECTURE (v5 — 100% Visual Strategy):
  CMO Mastermind  : Gemini 2.5 Flash -> Cerebras fallback — picks best Visual Style from analytics
  Execution LLM   : Groq (llama-3.3-70b-versatile) + Cerebras fallback
  Pin Type        : ALWAYS VIRAL_PIN — pure AI-generated aesthetic imagery
  No products, no affiliate links, no Google Sheets product dependency.
  Scheduler       : 10 pins/day — 5 per account — EST 7:30 AM to 7:30 PM window

VISUAL STYLES (CMO picks one based on analytics):
  green_minimalist  — Lush plants, white walls, natural light, Scandinavian-biophilic
  sunset_landscape  — Golden hour, dramatic skies, open horizons, cinematic nature
  cozy_architecture — Warm wooden interiors, stone fireplaces, hygge atmosphere
  cinematic_retro   — 35mm film grain, vintage color grading, nostalgic urban scenes

IMAGE GENERATION (dual-layer fallback):
  Layer 1 — OpenRouter FLUX (black-forest-labs/flux.2-pro) | timeout=180s
  Layer 2 — Pollinations.ai (free, URL-based)              | timeout=180s
  Hosted on ImgBB before every Pinterest post.

You MUST follow this EXACT protocol on every run:

STEP 1 → CALL publish_next_pin(visual_style="{visual_style}")
  - Reads all CMO content (title, description, tags, visual_prompt, ratio) automatically.
  - Generates AI image via OpenRouter FLUX -> Pollinations fallback.
  - Uploads to ImgBB. Posts to Pinterest via Make.com webhook. No affiliate link.

STEP 2 → END
  Output your final report in EXACTLY this format:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  VISUAL STYLE   : "[visual_style]"
  PIN TYPE       : "VIRAL_PIN"
  IMAGE SOURCE   : [OpenRouter-FLUX / Pollinations]
  STATUS         : Success OR Failed — [reason]
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


# ─────────────────────────────────────────────────────────────────────────────
# Graph Nodes
# ─────────────────────────────────────────────────────────────────────────────

async def agent_node(state: BotState) -> dict:
    if len(state["messages"]) > 16:
        return {"messages": [SystemMessage(content="⚠️ Loop Guard: Max iterations reached.")]}
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}


def should_continue(state: BotState):
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and len(last.tool_calls) > 0:
        return "tools"
    return END


# ─────────────────────────────────────────────────────────────────────────────
# Graph Builder & Entry Point
# ─────────────────────────────────────────────────────────────────────────────

def build_agent():
    g = StateGraph(BotState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(ALL_TOOLS))
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


async def run_agent(
    trigger: str = "scheduled",
    cmo_strategy: Optional[dict] = None,   # ← NEW: injected by Mastermind graph
) -> dict:
    """
    Entry point for the Pinteresto agent cycle.

    Args:
        trigger:      "account1" or "account2" (set by Mastermind graph node_agent_executor)
                      or "scheduled" / "manual" for standalone runs.
        cmo_strategy: Optional dict with keys: pin_type, strategy, vibe, title,
                      description, tags, visual_prompt.
                      When provided (Mastermind mode), the CMO's decisions are injected
                      and used directly in publish_next_pin().
                      When None (standalone mode), publish_next_pin() defaults to VIRAL_PIN.

    Returns:
        dict with keys: status, summary
    """
    global CURRENT_TRIGGER, CURRENT_CMO_STRATEGY
    CURRENT_TRIGGER      = trigger
    CURRENT_CMO_STRATEGY = cmo_strategy

    logger.info(
        f"🤖 [Agent] Starting cycle | trigger={trigger} | "
        f"CMO strategy={'INJECTED — ' + cmo_strategy.get('strategy', '?') if cmo_strategy else 'standalone'}"
    )

    agent = build_agent()

    # Build system prompt — with or without CMO brief
    system_prompt = _build_system_prompt(cmo_strategy)

    # Human message — tell agent the strategy is ready (Mastermind mode)
    if cmo_strategy:
        human_msg = (
            f"Run pipeline cycle. Trigger: {trigger}. "
            f"CMO strategy is already set in your brief above — use it exactly as given."
        )
    else:
        human_msg = f"Run pipeline cycle. Trigger: {trigger}"

    initial_state: BotState = {
        "messages": [
            SystemMessage(content=system_prompt),
            HumanMessage(content=human_msg),
        ],
        "posted_count": 0,
        "refilled":     False,
        "errors":       [],
    }

    try:
        final_state = await agent.ainvoke(initial_state)
        summary = final_state["messages"][-1].content
        logger.info(f"✅ [Agent] Cycle complete:\n{summary}")
        return {"status": "ok", "summary": summary}
    except Exception as e:
        msg = f"❌ [Agent] Graph execution failed: {e}"
        logger.error(msg)
        return {"status": "error", "summary": msg}
