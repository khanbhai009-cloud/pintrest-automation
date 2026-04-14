"""
mastermind/node_execute.py — Node 4: Execution Engine (Pollinations Edition)

CHANGELOG:
- Removed Gemini Image Generation (to avoid 429 Quota errors).
- Integrated Pollinations.ai for unlimited, free high-aesthetic Pinterest pins.
- Strict Trigger Isolation: manual-account1 vs manual-account2 support.
- Sequential Execution: 60s delay for scheduled runs to keep things stable.
"""
import asyncio
import logging
import os
import time
import uuid
import urllib.parse
from pathlib import Path

import httpx
from mastermind.state import MastermindState
from tools.google_drive import get_pending_products, mark_as_posted
from tools.make_webhook import post_to_pinterest

logger = logging.getLogger(__name__)

# ── Temp image directory (served via FastAPI) ───
_TMP_DIR = Path("static/tmp_pins")
_TMP_DIR.mkdir(parents=True, exist_ok=True)
_TMP_TTL_SECONDS = 3600  

# ── Per-account routing ──────────────────────────
_ACCOUNT_CONFIG = {
    "account_1": {
        "name":   "Account1_HomeDecor",
        "niches": ["home", "kitchen", "cozy", "gadgets", "organize"],
    },
    "account_2": {
        "name":   "Account2_Tech",
        "niches": ["tech", "budget", "phone", "smarthome", "wfh"],
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Utility helpers
# ─────────────────────────────────────────────────────────────────────────────

def _app_base_url() -> str:
    domain = (os.getenv("REPLIT_DEV_DOMAIN") or os.getenv("APP_BASE_URL", "")).strip()
    if domain and not domain.startswith("http"):
        domain = f"https://{domain}"
    return domain.rstrip("/")

async def _save_image_from_url(image_url: str) -> str | None:
    """Download image from Pollinations and save it to static/tmp_pins."""
    base = _app_base_url()
    if not base: return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url, follow_redirects=True)
            resp.raise_for_status()
            image_bytes = resp.content
            
        filename = f"{uuid.uuid4().hex}.jpg"
        (_TMP_DIR / filename).write_bytes(image_bytes)
        return f"{base}/static/tmp_pins/{filename}"
    except Exception as e:
        logger.error(f"❌ Failed to save AI image: {e}")
        return None

def _prune_tmp_images() -> None:
    cutoff = time.time() - _TMP_TTL_SECONDS
    for f in _TMP_DIR.glob("*.jpg"):
        try:
            if f.stat().st_mtime < cutoff: f.unlink()
        except Exception: pass

# ─────────────────────────────────────────────────────────────────────────────
# AI Image Orchestrator (Pollinations Unlimited)
# ─────────────────────────────────────────────────────────────────────────────

async def _generate_ai_image(strategy_name: str, cmo_strategy: dict, account_label: str) -> str | None:
    """Uses Pollinations.ai for zero-quota image generation."""
    _prune_tmp_images()
    
    # Get prompts from CMO Mastermind
    image_prompt_direction = (cmo_strategy.get("image_prompts") or ["aesthetic Pinterest pin"])[0]
    vibe = cmo_strategy.get("vibe", "aspirational")
    
    # Build the Pollinations Prompt
    prompt = f"{image_prompt_direction}, {vibe}, ultra-high-quality, pinterest aesthetic, 8k"
    encoded_prompt = urllib.parse.quote(prompt)
    
    # Pollinations URL (Using FLUX model for best quality)
    pollinations_url = f"https://pollinations.ai/p/{encoded_prompt}?width=1024&height=1792&nologo=true&model=flux"
    
    logger.info(f"🎨 [{account_label}] Generating via Pollinations: {prompt[:50]}...")
    return await _save_image_from_url(pollinations_url)

# ─────────────────────────────────────────────────────────────────────────────
# Per-account publish pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def _execute_for_account(account_key: str, seo_copy: dict, cmo_strategy: dict) -> dict:
    cfg = _ACCOUNT_CONFIG[account_key]
    account_name = cfg["name"]
    strategy_name = cmo_strategy.get("strategy", "")

    # 1. Fetch pending product
    try:
        products = get_pending_products(limit=1, allowed_niches=cfg["niches"])
    except Exception as e:
        return {"success": False, "message": f"Fetch failed: {e}", "account": account_name}

    if not products:
        return {"success": False, "message": "No pending products.", "account": account_name}

    product = products[0]
    niche = product.get("niche") or cfg["niches"][0]
    raw_img_url = product.get("image_url", "")
    product_name = product.get("product_name", "Amazing Find")

    # 2. AI Image Generation (New: Pollinations)
    ai_image_url = await _generate_ai_image(strategy_name, cmo_strategy, account_name)
    final_image_url = ai_image_url if ai_image_url else raw_img_url
    image_source = "pollinations-ai" if ai_image_url else "sheet-fallback"

    # 3. Affiliate link
    affiliate_link = (product.get("affiliate_link") or product.get("product_url", ""))
    if "Viral-Bait" in strategy_name: 
        affiliate_link = ""
        logger.info(f"🎯 [{account_name}] Viral-Bait → Link stripped.")

    # 4. Post Webhook
    try:
        success = await post_to_pinterest(
            image_url=final_image_url,
            title=(seo_copy.get("title") or product_name)[:100],
            description=seo_copy.get("description", ""),
            link=affiliate_link,
            tags=seo_copy.get("tags") or [],
            niche=niche,
            target_account=account_name,
        )
        if success: mark_as_posted(product_name)
    except Exception as e:
        return {"success": False, "message": str(e), "account": account_name}

    return {"success": success, "message": f"Posted: {product_name[:30]}", "account": account_name, "image_source": image_source}

# ─────────────────────────────────────────────────────────────────────────────
# LangGraph Node Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def node_execution_engine(state: MastermindState) -> dict:
    """
    Sequential execution based on trigger to prevent any API crashes.
    """
    trigger = state.get("cycle_trigger", "scheduled")
    logger.info(f"🚀 [Node 4] Execution trigger: {trigger}")

    a1_status = {"success": False, "message": "Skipped (Trigger mismatch)", "account": "Account1_HomeDecor"}
    a2_status = {"success": False, "message": "Skipped (Trigger mismatch)", "account": "Account2_Tech"}

    if trigger == "manual-account1":
        logger.info("🎯 Running Account 1 ONLY.")
        a1_status = await _execute_for_account("account_1", state["a1_final_seo_copy"], state["a1_cmo_strategy"])
    
    elif trigger == "manual-account2":
        logger.info("🎯 Running Account 2 ONLY.")
        a2_status = await _execute_for_account("account_2", state["a2_final_seo_copy"], state["a2_cmo_strategy"])
    
    else:
        # Scheduled: Run sequentially
        logger.info("⏳ Scheduled Run: Processing accounts one by one...")
        a1_status = await _execute_for_account("account_1", state["a1_final_seo_copy"], state["a1_cmo_strategy"])
        
        logger.info("🛌 Delaying 10s between accounts...")
        await asyncio.sleep(10) # Pollinations is fast, 60s not needed
        
        a2_status = await _execute_for_account("account_2", state["a2_final_seo_copy"], state["a2_cmo_strategy"])

    return {"a1_publish_status": a1_status, "a2_publish_status": a2_status}
