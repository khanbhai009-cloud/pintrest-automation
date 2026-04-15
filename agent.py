"""
agent.py — Pinteresto Mastermind Agent (Production v2)

LangGraph StateGraph architecture with:
  - Explicit env loading (IMGBB_API_KEY, etc.)
  - Full async httpx for all network I/O
  - CMO strategy-aware routing (Visual Pivot / Viral-Bait / Aggressive Affiliate Strike)
  - Dual image pipeline: T2I (Pollinations → Puter fallback) vs I2I (Puter)
  - ImgBB mandatory hosting gateway before every Pinterest webhook call
  - Mandatory stock refill guard before publishing
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


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph State
# ─────────────────────────────────────────────────────────────────────────────

class BotState(TypedDict):
    messages:     Annotated[list, add_messages]
    posted_count: int
    refilled:     bool
    errors:       list[str]


# ─────────────────────────────────────────────────────────────────────────────
# Internal async image helpers — ALL use httpx.AsyncClient
# ─────────────────────────────────────────────────────────────────────────────

async def _download_bytes(url: str, timeout: int = 45) -> Optional[bytes]:
    """Download raw bytes from any public URL using an async client."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.error(f"❌ _download_bytes failed [{url[:60]}]: {e}")
        return None


async def _t2i_pollinations(prompt: str) -> Optional[bytes]:
    """
    PRIMARY text-to-image path.
    Pollinations.ai — free, no key required, returns image bytes directly.
    Uses portrait 1024×1792 for Pinterest's optimal aspect ratio.
    """
    encoded = urllib.parse.quote(
        f"{prompt}, ultra-realistic, 8k pinterest aesthetic, high-fidelity"
    )
    seed = uuid.uuid4().int % 99999
    url = (
        f"https://pollinations.ai/p/{encoded}"
        f"?width=1024&height=1792&nologo=true&model=flux&seed={seed}"
    )
    logger.info(f"🎨 [T2I-Pollinations] Generating image...")
    try:
        async with httpx.AsyncClient(timeout=90, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.content
            if len(data) < 5000:
                raise ValueError("Suspiciously small response — not a real image.")
            logger.info(f"✅ [T2I-Pollinations] {len(data)} bytes received.")
            return data
    except Exception as e:
        logger.warning(f"⚠️ [T2I-Pollinations] Failed: {e}")
        return None


async def _t2i_puter(prompt: str) -> Optional[bytes]:
    """
    FALLBACK text-to-image path.
    Calls the Puter.js REST API (drivers/call — openai-image-gen interface).
    Returns image bytes by downloading the returned URL.
    """
    if not PUTER_API_KEY:
        logger.warning("⚠️ [T2I-Puter] PUTER_API_KEY not set — skipping Puter fallback.")
        return None

    payload = {
        "interface": "puter-image-generation",
        "driver":    "openai-image-gen",
        "test_mode": False,
        "method":    "generate",
        "args": {
            "prompt": f"{prompt}, ultra-realistic, 8k, Pinterest portrait",
            "n":      1,
            "size":   "1024x1792",
        },
    }
    headers = {
        "Authorization": f"Bearer {PUTER_API_KEY}",
        "Content-Type":  "application/json",
    }
    logger.info("🎨 [T2I-Puter] Calling Puter image generation API...")
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://api.puter.com/drivers/call",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()

        img_url = (
            result.get("result", {}).get("url")
            or result.get("result", {}).get("data", [{}])[0].get("url")
        )
        if not img_url:
            raise ValueError(f"No image URL in Puter response: {result}")

        logger.info(f"✅ [T2I-Puter] Got URL, downloading bytes...")
        return await _download_bytes(img_url)

    except Exception as e:
        logger.error(f"❌ [T2I-Puter] Failed: {e}")
        return None


async def _i2i_puter(product_image_url: str, aesthetic_prompt: str) -> Optional[bytes]:
    """
    IMAGE-TO-IMAGE path — exclusive to 'Aggressive Affiliate Strike'.
    Sends the raw Amazon product image URL + CMO aesthetic prompt to Puter.
    Puter composites the product onto the aesthetic background/lighting.
    Returns image bytes.
    """
    if not PUTER_API_KEY:
        logger.warning("⚠️ [I2I-Puter] PUTER_API_KEY not set — falling back to T2I.")
        return await _t2i_pollinations(aesthetic_prompt)

    full_prompt = (
        f"Product photograph of item shown in the reference image, "
        f"placed in this environment: {aesthetic_prompt}. "
        f"Ultra-realistic, 8k, Pinterest aesthetic, perfect lighting."
    )
    payload = {
        "interface": "puter-image-generation",
        "driver":    "openai-image-gen",
        "test_mode": False,
        "method":    "edit",
        "args": {
            "image_url": product_image_url,
            "prompt":    full_prompt,
            "n":         1,
            "size":      "1024x1792",
        },
    }
    headers = {
        "Authorization": f"Bearer {PUTER_API_KEY}",
        "Content-Type":  "application/json",
    }
    logger.info(f"🖼️  [I2I-Puter] Compositing product image with vibe prompt...")
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                "https://api.puter.com/drivers/call",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            result = resp.json()

        img_url = (
            result.get("result", {}).get("url")
            or result.get("result", {}).get("data", [{}])[0].get("url")
        )
        if not img_url:
            raise ValueError(f"No image URL in Puter I2I response: {result}")

        logger.info("✅ [I2I-Puter] Composite generated. Downloading bytes...")
        return await _download_bytes(img_url)

    except Exception as e:
        logger.error(f"❌ [I2I-Puter] Failed: {e}. Falling back to T2I-Pollinations.")
        return await _t2i_pollinations(aesthetic_prompt)


async def _upload_to_imgbb(image_bytes: bytes) -> Optional[str]:
    """
    MANDATORY ImgBB gateway — uploads image bytes and returns a 30-minute
    temporary public URL that Pinterest / Make.com webhook can reliably fetch.

    expiration=1800 (30 min) — pins post within seconds so this is sufficient.
    """
    if not IMGBB_API_KEY:
        logger.error("❌ [ImgBB] IMGBB_API_KEY not set — cannot upload image.")
        return None

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    logger.info(f"⬆️  [ImgBB] Uploading {len(image_bytes)} bytes...")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.imgbb.com/1/upload",
                data={
                    "key":        IMGBB_API_KEY,
                    "image":      encoded,
                    "expiration": "1800",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        direct_url = data["data"]["url"]
        logger.info(f"✅ [ImgBB] Hosted: {direct_url}")
        return direct_url

    except Exception as e:
        logger.error(f"❌ [ImgBB] Upload failed: {e}")
        return None


async def _orchestrate_image(
    strategy: str,
    vibe: str,
    image_prompt: str,
    raw_product_image_url: str,
) -> Optional[str]:
    """
    Master image orchestrator.

    PATH A — 'Visual Pivot' or 'Viral-Bait':
        T2I via Pollinations → on failure, T2I via Puter → ImgBB → return URL

    PATH B — 'Aggressive Affiliate Strike':
        I2I via Puter (product image + aesthetic prompt) → ImgBB → return URL

    Always returns an ImgBB-hosted URL or None on complete failure.
    """
    composite_prompt = f"{image_prompt}, {vibe}" if image_prompt else vibe
    image_bytes: Optional[bytes] = None

    if "Aggressive Affiliate Strike" in strategy:
        logger.info("🎯 [Image] PATH B — Image-to-Image (Affiliate Strike)")
        image_bytes = await _i2i_puter(raw_product_image_url, composite_prompt)
    else:
        logger.info("🎨 [Image] PATH A — Text-to-Image (Visual Pivot / Viral-Bait)")
        image_bytes = await _t2i_pollinations(composite_prompt)
        if not image_bytes:
            logger.warning("⚠️ [Image] Pollinations failed — trying Puter fallback...")
            image_bytes = await _t2i_puter(composite_prompt)

    if not image_bytes:
        logger.error("❌ [Image] All image generation paths failed.")
        return None

    return await _upload_to_imgbb(image_bytes)


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

    Pipeline:
      1. Fetch pending product from Sheet
      2. Generate SEO copy via LLM
      3. Route to T2I or I2I image generator (Pollinations → Puter fallback)
      4. Upload image bytes to ImgBB (expiration=1800s) — MANDATORY
      5. POST ImgBB URL to Make.com Pinterest webhook
      6. Mark product as POSTED in Sheet
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
        # Last-resort: upload the raw product image through ImgBB so URL is always stable
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
# System Prompt — CMO Strategy Aware
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are PINTERESTO — an autonomous Pinterest affiliate marketing agent powered by the Mastermind CEO pipeline.

You operate under a CMO strategy issued by the Mastermind CEO (Gemini). The strategy is ONE of:
  • "Visual Pivot"              — Post aspirational aesthetic content. Generate T2I images. Strip affiliate links.
  • "Viral-Bait"               — Post high-quality purely aesthetic content to warm up the algorithm. Generate T2I images. Strip affiliate links.
  • "Aggressive Affiliate Strike" — Post product pins with affiliate links. Use the raw product image composed into the vibe (I2I). Keep affiliate links.

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
    strategy="<CMO strategy — one of the three above>",
    vibe="<CMO's exact aesthetic vibe command>",
    image_prompt="<CMO's high-fidelity image generation direction>"
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


async def run_agent(trigger: str = "scheduled") -> dict:
    """
    Entry point for the standalone Pinteresto agent cycle.
    The Mastermind CEO graph (mastermind/graph.py) calls run_mastermind() independently.
    This agent can be triggered directly for single-account runs or debugging.
    """
    global CURRENT_TRIGGER
    CURRENT_TRIGGER = trigger
    logger.info(f"🤖 [Agent] Starting cycle | trigger={trigger}")

    agent = build_agent()
    initial_state: BotState = {
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Run pipeline cycle. Trigger: {trigger}"),
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
