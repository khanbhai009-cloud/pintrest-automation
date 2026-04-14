"""
mastermind/node_execute.py — Node 4: Execution Engine (Final Fixed Version)
- Manual Trigger Support: Only runs the account requested.
- Sequential Execution: Adds a 60s delay between accounts during scheduled runs to prevent 429 Quota errors.
- Fallback: Uses Sheet image if Gemini fails.
"""
import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

import httpx
from google import genai
from google.genai import types as genai_types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import GEMINI_API_KEY, GEMINI_IMAGE_MODEL
from mastermind.state import MastermindState
from tools.google_drive import get_pending_products, mark_as_posted
from tools.make_webhook import post_to_pinterest

logger = logging.getLogger(__name__)

# ── Gemini client ─────────────────────────────────────────────────────────────
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── Temp image directory ──────────────────────────────────────────────────────
_TMP_DIR = Path("static/tmp_pins")
_TMP_DIR.mkdir(parents=True, exist_ok=True)
_TMP_TTL_SECONDS = 3600  

# ── Per-account routing ───────────────────────────────────────────────────────
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
# Utility helpers (Untouched)
# ─────────────────────────────────────────────────────────────────────────────

def _app_base_url() -> str:
    domain = (os.getenv("REPLIT_DEV_DOMAIN") or os.getenv("APP_BASE_URL", "")).strip()
    if domain and not domain.startswith("http"):
        domain = f"https://{domain}"
    return domain.rstrip("/")

def _save_image(image_bytes: bytes) -> str | None:
    base = _app_base_url()
    if not base: return None
    try:
        filename = f"{uuid.uuid4().hex}.jpg"
        (_TMP_DIR / filename).write_bytes(image_bytes)
        return f"{base}/static/tmp_pins/{filename}"
    except Exception: return None

def _prune_tmp_images() -> None:
    cutoff = time.time() - _TMP_TTL_SECONDS
    for f in _TMP_DIR.glob("*.jpg"):
        try:
            if f.stat().st_mtime < cutoff: f.unlink()
        except Exception: pass

def _extract_image_bytes(response) -> bytes:
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    raise ValueError("Gemini response contained no image data.")

# ─────────────────────────────────────────────────────────────────────────────
# Gemini Generators
# ─────────────────────────────────────────────────────────────────────────────

@retry(retry=retry_if_exception_type(Exception), wait=wait_exponential(multiplier=2, min=6, max=60), stop=stop_after_attempt(4), reraise=True)
def _img2img_sync(source_bytes: bytes, prompt: str) -> bytes:
    response = _gemini_client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=[genai_types.Part.from_bytes(data=source_bytes, mime_type="image/jpeg"), prompt],
        config=genai_types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    return _extract_image_bytes(response)

@retry(retry=retry_if_exception_type(Exception), wait=wait_exponential(multiplier=2, min=6, max=60), stop=stop_after_attempt(4), reraise=True)
def _txt2img_sync(prompt: str) -> bytes:
    response = _gemini_client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(response_modalities=["IMAGE", "TEXT"]),
    )
    return _extract_image_bytes(response)

# ─────────────────────────────────────────────────────────────────────────────
# Core Logic — Image Generation Orchestrator
# ─────────────────────────────────────────────────────────────────────────────

async def _generate_ai_image(strategy_name: str, cmo_strategy: dict, raw_image_url: str, account_label: str) -> str | None:
    _prune_tmp_images()
    image_prompt_direction = (cmo_strategy.get("image_prompts") or ["aesthetic Pinterest pin"])[0]
    vibe = cmo_strategy.get("vibe", "aspirational")
    
    # Mode: Text-to-Image (Viral-Bait)
    if "Viral-Bait" in strategy_name:
        prompt = f"Pinterest aesthetic pin. Vibe: {vibe}. Concept: {image_prompt_direction}. High-end visual."
        try:
            image_bytes = await asyncio.to_thread(_txt2img_sync, prompt)
            return _save_image(image_bytes)
        except Exception as e:
            logger.error(f"❌ [{account_label}] Text-to-Image failed: {e}")
            return None

    # Mode: Image-to-Image (Affiliate/Visual)
    source_bytes = None
    if raw_image_url:
        try:
            async with httpx.AsyncClient(timeout=25) as client:
                resp = await client.get(raw_image_url, follow_redirects=True)
                resp.raise_for_status()
                source_bytes = resp.content
        except Exception: pass

    if source_bytes:
        prompt = f"Pinterest designer pin. Vibe: {vibe}. Direction: {image_prompt_direction}. Keep product centered."
        try:
            image_bytes = await asyncio.to_thread(_img2img_sync, source_bytes, prompt)
            return _save_image(image_bytes)
        except Exception: pass

    return None

# ─────────────────────────────────────────────────────────────────────────────
# Account Publish Pipeline
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

    # 2. AI Image Generation
    ai_image_url = await _generate_ai_image(strategy_name, cmo_strategy, raw_img_url, account_name)
    final_image_url = ai_image_url if ai_image_url else raw_img_url
    image_source = f"gemini" if ai_image_url else "sheet-fallback"

    # 3. Affiliate link
    affiliate_link = (product.get("affiliate_link") or product.get("product_url", ""))
    if "Viral-Bait" in strategy_name: affiliate_link = ""

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
# THE FIX: LangGraph Node Entry Point
# ─────────────────────────────────────────────────────────────────────────────

async def node_execution_engine(state: MastermindState) -> dict:
    """
    Node 4 — Execution Engine.
    Sequential execution based on cycle_trigger to prevent 429 Quota errors.
    """
    trigger = state.get("cycle_trigger", "scheduled")
    logger.info(f"🚀 [Node 4] Execution triggered by: {trigger}")

    # Default Statuses
    a1_status = {"success": False, "message": "Skipped (Trigger mismatch)", "account": "Account1_HomeDecor"}
    a2_status = {"success": False, "message": "Skipped (Trigger mismatch)", "account": "Account2_Tech"}

    # Logic: Filter by Trigger
    if trigger == "manual-account1":
        logger.info("🎯 Processing Account 1 ONLY.")
        a1_status = await _execute_for_account("account_1", state["a1_final_seo_copy"], state["a1_cmo_strategy"])
    
    elif trigger == "manual-account2":
        logger.info("🎯 Processing Account 2 ONLY.")
        a2_status = await _execute_for_account("account_2", state["a2_final_seo_copy"], state["a2_cmo_strategy"])
    
    else:
        # Scheduled: Run sequentially with delay
        logger.info("⏳ Scheduled run: Running accounts sequentially with cooldown...")
        a1_status = await _execute_for_account("account_1", state["a1_final_seo_copy"], state["a1_cmo_strategy"])
        
        logger.info("🛌 Cooling down Gemini (60s)...")
        await asyncio.sleep(60)
        
        a2_status = await _execute_for_account("account_2", state["a2_final_seo_copy"], state["a2_cmo_strategy"])

    return {"a1_publish_status": a1_status, "a2_publish_status": a2_status}
