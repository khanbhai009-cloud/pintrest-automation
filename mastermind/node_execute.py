"""
mastermind/node_execute.py — Final Version (Pollinations + Puter Fallback)
Strict isolation, link stripping for Viral-Bait, and direct public URLs.
"""
import asyncio
import logging
import os
import uuid
import urllib.parse
from mastermind.state import MastermindState
from tools.google_drive import get_pending_products, mark_as_posted
from tools.make_webhook import post_to_pinterest

logger = logging.getLogger(__name__)

# ── Per-account routing ──────────────────────────
_ACCOUNT_CONFIG = {
    "account_1": { "name": "Account1_HomeDecor", "niches": ["home", "kitchen", "cozy", "gadgets", "organize"] },
    "account_2": { "name": "Account2_Tech", "niches": ["tech", "budget", "phone", "smarthome", "wfh"] },
}

# ─────────────────────────────────────────────────────────────────────────────
# AI Image Orchestrator (Primary: Pollinations | Fallback: Puter Logic)
# ─────────────────────────────────────────────────────────────────────────────

async def _generate_ai_image(strategy_name: str, cmo_strategy: dict, account_label: str) -> str | None:
    """Returns a DIRECT public URL for Pinterest to fetch."""
    image_prompt_direction = (cmo_strategy.get("image_prompts") or ["aesthetic Pinterest pin"])[0]
    vibe = cmo_strategy.get("vibe", "aspirational")
    
    # Clean prompt for URL
    clean_prompt = f"{image_prompt_direction}, {vibe}, high-resolution, pinterest aesthetic, 8k"
    encoded_prompt = urllib.parse.quote(clean_prompt)
    seed = uuid.uuid4().int % 10000

    # 1. Primary: Pollinations.ai (Fastest & Public)
    pollinations_url = f"https://pollinations.ai/p/{encoded_prompt}?width=1024&height=1792&nologo=true&model=flux&seed={seed}"
    
    # 2. Fallback Logic: Puter/Imagen Style (If needed in future)
    # Note: For now, we return Pollinations because Pinterest needs a direct public URL.
    # If Pollinations failed, the pipeline automatically uses the Sheet's raw image_url.
    
    logger.info(f"🎨 [{account_label}] Strategy: {strategy_name} | AI URL: {pollinations_url[:60]}...")
    return pollinations_url

# ─────────────────────────────────────────────────────────────────────────────
# Execution Pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def _execute_for_account(account_key: str, seo_copy: dict, cmo_strategy: dict) -> dict:
    cfg = _ACCOUNT_CONFIG[account_key]
    account_name = cfg["name"]
    strategy_name = cmo_strategy.get("strategy", "")

    # 1. Product Fetch
    try:
        products = get_pending_products(limit=1, allowed_niches=cfg["niches"])
        if not products: return {"success": False, "message": "No products.", "account": account_name}
        product = products[0]
    except Exception as e:
        return {"success": False, "message": str(e), "account": account_name}

    product_name = product.get("product_name", "Amazing Find")
    raw_img_url = product.get("image_url", "")

    # 2. Viral-Bait Check: Link Stripping
    affiliate_link = product.get("affiliate_link") or product.get("product_url", "")
    if "Viral-Bait" in strategy_name:
        affiliate_link = "" # SHAMELESS STRIP
        logger.info(f"🎯 [{account_name}] Viral-Bait detected. Affiliate link REMOVED.")

    # 3. Get AI Image URL
    final_image_url = await _generate_ai_image(strategy_name, cmo_strategy, account_name)
    if not final_image_url: final_image_url = raw_img_url # Sheet Fallback

    # 4. Post to Pinterest
    try:
        success = await post_to_pinterest(
            image_url=final_image_url,
            title=(seo_copy.get("title") or product_name)[:100],
            description=seo_copy.get("description", ""),
            link=affiliate_link,
            tags=seo_copy.get("tags") or [],
            niche=product.get("niche") or cfg["niches"][0],
            target_account=account_name,
        )
        if success: mark_as_posted(product_name)
    except Exception as e:
        return {"success": False, "message": str(e), "account": account_name}

    return {"success": success, "message": f"Posted: {product_name[:30]}", "account": account_name}

# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def node_execution_engine(state: MastermindState) -> dict:
    trigger = state.get("cycle_trigger", "scheduled")
    logger.info(f"🚀 [Node 4] Trigger: {trigger}")

    a1_status = {"success": False, "message": "Skipped", "account": "Account1_HomeDecor"}
    a2_status = {"success": False, "message": "Skipped", "account": "Account2_Tech"}

    if trigger == "manual-account1":
        a1_status = await _execute_for_account("account_1", state["a1_final_seo_copy"], state["a1_cmo_strategy"])
    elif trigger == "manual-account2":
        a2_status = await _execute_for_account("account_2", state["a2_final_seo_copy"], state["a2_cmo_strategy"])
    else:
        # Scheduled Sequential
        a1_status = await _execute_for_account("account_1", state["a1_final_seo_copy"], state["a1_cmo_strategy"])
        await asyncio.sleep(5)
        a2_status = await _execute_for_account("account_2", state["a2_final_seo_copy"], state["a2_cmo_strategy"])

    return {"a1_publish_status": a1_status, "a2_publish_status": a2_status}
