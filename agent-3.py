"""
agent.py — Pinteresto Mastermind Agent (Production v2)

LangGraph StateGraph architecture with:
  - Explicit env loading (IMGBB_API_KEY, etc.)
  - Full async httpx for all network I/O
  - CMO strategy-aware routing (Visual Pivot / Viral-Bait / Aggressive Affiliate Strike)
  - Dual image pipeline: T2I (Pollinations → Puter fallback) vs I2I (Puter)
  - ImgBB mandatory hosting gateway before every Pinterest webhook call
  - Mandatory stock refill guard before publishing

CHANGE (Mastermind integration):
  run_agent() now accepts an optional `cmo_strategy` dict from the Mastermind graph.
  When provided, the strategy/vibe/image_prompts are injected directly into the
  system prompt so the agent acts on the CMO's exact commands — no Node 3/4 needed.
"""

import asyncio
import base64
import logging
import os
import random
import time
import urllib.parse
import uuid
from typing import Annotated, Optional

import httpx
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from langgraph.graph import END, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from typing_extensions import TypedDict
from tools.image_creator import generate_pin_image
from config import (
    CEREBRAS_API_KEY,
    CEREBRAS_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
    PINTEREST_ACCOUNTS,
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
IMGBB_API_KEY  = os.getenv("IMGBB_API_KEY")
PUTER_API_KEY  = os.getenv("PUTER_API_KEY")

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
async def publish_next_pin(
    niche:         str,
    strategy:      str = "Visual Pivot",
    vibe:          str = "",
    image_prompt:  str = "",
) -> dict:
    """
    Publish the next PENDING product for the given niche to Pinterest.

    strategy must be exactly one of:
      'Visual Pivot'              → T2I aesthetic pin, affiliate link STRIPPED
      'Viral-Bait'                → T2I aesthetic pin, affiliate link STRIPPED
      'Aggressive Affiliate Strike' → I2I product composite, affiliate link KEPT

    vibe        — CMO's exact aesthetic command (e.g. 'Satisfying ASMR/Luxury...')
    image_prompt — CMO's high-fidelity image generation direction

    NOTE: When called from Mastermind pipeline, strategy/vibe/image_prompt are
    pre-filled by the CMO system prompt — agent just calls this with the right values.
    """
    global CURRENT_TRIGGER
    target_account = (
        "Account1_HomeDecor"
        if "account1" in str(CURRENT_TRIGGER)
        else "Account2_Tech"
    )

    # 1. Fetch product
    pending = get_pending_products(limit=1, allowed_niches=[niche])
    if not pending:
        return {"success": False, "reason": f"No PENDING products for niche '{niche}'"}
    product = pending[0]

    product_name      = product.get("product_name", "Amazing Find")
    raw_img_url       = product.get("image_url", "")
    affiliate_link    = product.get("affiliate_link") or product.get("product_url", "")

    # Strip affiliate link for non-affiliate strategies
    if strategy in ("Visual Pivot", "Viral-Bait"):
        affiliate_link = ""
        logger.info(f"🔗 [{target_account}] Strategy='{strategy}' — affiliate link STRIPPED.")
    else:
        logger.info(f"🔗 [{target_account}] Strategy='{strategy}' — affiliate link KEPT.")

    # 2. SEO copy
    try:
        copy  = generate_pin_copy(product)
        title = copy.get("title", product_name)[:100]
        desc  = copy.get("description", "")
        tags  = copy.get("tags", [])
    except Exception as e:
        logger.error(f"❌ SEO copy generation failed: {e}")
        title = product_name[:100]
        desc  = ""
        tags  = []

    # 3. Image pipeline — T2I or I2I → always ends with ImgBB URL
    imgbb_url = await _orchestrate_image(
        strategy=strategy,
        vibe=vibe,
        image_prompt=image_prompt,
        raw_product_image_url=raw_img_url,
    )

    if not imgbb_url:
        logger.warning(
            "⚠️ [Publish] ImgBB URL unavailable — attempting fallback with raw product image."
        )
        if raw_img_url:
            fallback_bytes = await _download_bytes(raw_img_url)
            if fallback_bytes:
                imgbb_url = await _upload_to_imgbb(fallback_bytes)

    if not imgbb_url:
        return {"success": False, "reason": "Image generation and all fallbacks failed."}

    # 4. Post to Pinterest via Make.com webhook
    try:
        success = await post_to_pinterest(
            image_url=imgbb_url,
            title=title,
            description=desc,
            link=affiliate_link,
            tags=tags,
            niche=niche,
            target_account=target_account,
        )
    except Exception as e:
        return {"success": False, "reason": f"Webhook error: {e}"}

    # 5. Mark as posted
    if success:
        mark_as_posted(product_name)
        return {
            "success":   True,
            "product":   product_name,
            "niche":     niche,
            "strategy":  strategy,
            "image_url": imgbb_url,
        }

    return {"success": False, "reason": "Webhook returned failure status."}


# ─────────────────────────────────────────────────────────────────────────────
# Tool Registry & LLM
# ─────────────────────────────────────────────────────────────────────────────

ALL_TOOLS = [fill_missing_niches, analyze_niche_stock, fetch_aliexpress_products, publish_next_pin]


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

    If `cmo_strategy` is provided (from Mastermind graph), inject the exact
    strategy/vibe/image_prompts into the prompt so the agent uses them directly
    when calling publish_next_pin — no guessing, no Node 3 copywriters needed.

    If `cmo_strategy` is None (standalone run), keep the original open-ended prompt.
    """
    if cmo_strategy:
        strategy     = cmo_strategy.get("strategy", "Visual Pivot")
        vibe         = cmo_strategy.get("vibe", "Aspirational aesthetic")
        image_prompts = cmo_strategy.get("image_prompts", ["aesthetic product photo"])
        image_prompt  = image_prompts[0] if image_prompts else "aesthetic product photo"

        cmo_brief = f"""
⚡ CMO MASTERMIND BRIEF — FOLLOW THIS EXACTLY ⚡
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  STRATEGY     : {strategy}
  VIBE         : {vibe}
  IMAGE PROMPT : {image_prompt}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The CMO Mastermind (Gemini) has already decided. You MUST use these EXACT values
in your publish_next_pin() call. Do NOT change strategy, vibe, or image_prompt.
"""
    else:
        cmo_brief = """
⚡ CMO BRIEF — STANDALONE MODE ⚡
No Mastermind strategy injected. Use your judgment to select the best strategy
(Visual Pivot / Viral-Bait / Aggressive Affiliate Strike) based on the account trigger.
"""

    return f"""You are PINTERESTO — an autonomous Pinterest affiliate marketing agent powered by the Mastermind CEO pipeline.
{cmo_brief}
You operate under a CMO strategy that is ONE of:
  • "Visual Pivot"                  — Post aspirational aesthetic content. Generate T2I images. Strip affiliate links.
  • "Viral-Bait"                    — Post high-quality purely aesthetic content to warm up the algorithm. Generate T2I images. Strip affiliate links.
  • "Aggressive Affiliate Strike"   — Post product pins with affiliate links. Use the raw product image composed into the vibe (I2I). Keep affiliate links.

You MUST follow this EXACT 5-step protocol on every run:

STEP 1 → CALL fill_missing_niches()
  - Purpose: Classify any products in the Sheet that have no niche assigned.

STEP 2 → CALL analyze_niche_stock()
  - Purpose: Select the target niche and check stock levels.
  - Note the returned values: selected_niche and needs_fetching.

STEP 3 → MANDATORY STOCK GATE
  - IF needs_fetching == True: You MUST call fetch_aliexpress_products(niche="<selected_niche>")
  - Do NOT skip this. Never proceed to STEP 4 with an empty niche.
  - IF needs_fetching == False: Skip STEP 3 and proceed directly to STEP 4.

STEP 4 → CALL publish_next_pin(
    niche="<selected_niche>",
    strategy="<use the CMO strategy from the brief above — EXACTLY>",
    vibe="<use the CMO vibe from the brief above — EXACTLY>",
    image_prompt="<use the CMO image_prompt from the brief above — EXACTLY>"
  )
  The image pipeline inside publish_next_pin will:
    - For Visual Pivot / Viral-Bait: Generate a fresh T2I image (Pollinations → Puter fallback) and strip affiliate links.
    - For Aggressive Affiliate Strike: Composite the product image with the vibe (I2I via Puter) and keep the affiliate link.
  The image is always routed through ImgBB (30-min temp hosting) before the Pinterest webhook.

STEP 5 → END
  Output your final report in EXACTLY this format:
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  NICHES FILLED  : [X products updated]
  TARGET NICHE   : "[selected_niche]"
  STRATEGY       : "[Visual Pivot / Viral-Bait / Aggressive Affiliate Strike]"
  STOCK REFILLED : [Yes — X products fetched] OR [No — stock sufficient]
  POSTED         : "[product title]"
  IMAGE PATH     : [T2I-Pollinations / T2I-Puter / I2I-Puter]
  STATUS         : ✅ Success OR ❌ Failed — [reason]
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""


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
        cmo_strategy: Optional dict with keys: strategy, vibe, image_prompts.
                      When provided (Mastermind mode), the CMO's exact decisions are
                      injected into the system prompt and used verbatim in publish_next_pin().
                      When None (standalone mode), agent decides strategy independently.

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
