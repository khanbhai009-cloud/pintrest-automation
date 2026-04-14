"""
mastermind/node_execute.py — Node 4: Execution Engine (100% AI Image)

PIL/Pillow completely removed. No manual overlays. No text drawing.
Gemini is the sole image engine.

IMAGE MODES (driven by CMO strategy):
  • "Affiliate Strike" / "Visual Pivot" → Image-to-Image
      Fetch product photo bytes from image_url in the Google Sheet.
      Send bytes + CMO image_prompt to gemini image model.
      Gemini natively blends the product into a high-aesthetic Pinterest scene.

  • "Algorithmic Viral-Bait (No links)" → Text-to-Image
      No product source image. Pure CMO prompt → Gemini generates a standalone
      aesthetic visual. Affiliate link is also stripped from the payload.

GENERATED IMAGE DELIVERY:
  Image bytes are saved to static/tmp_pins/ which FastAPI already serves
  at /static/tmp_pins/<uuid>.jpg.  The public HTTPS URL is constructed from
  REPLIT_DEV_DOMAIN (dev) or APP_BASE_URL (production) and passed unchanged
  to the existing make_webhook.post_to_pinterest() function.

RATE LIMITING (10 RPM):
  tenacity exponential backoff: multiplier=2, min=6 s, max=60 s, 4 attempts.

BULLETPROOF FALLBACK:
  If Gemini image generation fails after all retries, the pipeline falls back
  to the raw image_url from the Google Sheet.  The pin is still published.
  Pipeline NEVER stops.
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

# ── Temp image directory (served via FastAPI's existing /static/ mount) ───────
_TMP_DIR = Path("static/tmp_pins")
_TMP_DIR.mkdir(parents=True, exist_ok=True)
_TMP_TTL_SECONDS = 3600  # Prune files older than 1 h during each cycle

# ── Per-account routing (mirrors PINTEREST_ACCOUNTS in config.py) ─────────────
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
    """Return the public HTTPS base URL for this Replit deployment."""
    domain = (
        os.getenv("REPLIT_DEV_DOMAIN")
        or os.getenv("APP_BASE_URL", "")
    ).strip()
    if domain and not domain.startswith("http"):
        domain = f"https://{domain}"
    return domain.rstrip("/")


def _save_image(image_bytes: bytes) -> str | None:
    """
    Persist raw image bytes to static/tmp_pins/ and return a public URL.
    Returns None if the base URL is unknown or write fails.
    """
    base = _app_base_url()
    if not base:
        logger.warning(
            "⚠️  REPLIT_DEV_DOMAIN / APP_BASE_URL not set — "
            "cannot build a public URL for the generated image."
        )
        return None
    try:
        filename = f"{uuid.uuid4().hex}.jpg"
        (_TMP_DIR / filename).write_bytes(image_bytes)
        public_url = f"{base}/static/tmp_pins/{filename}"
        logger.info(f"🖼️  AI image persisted → {public_url}")
        return public_url
    except Exception as e:
        logger.error(f"❌ Failed to save generated image to disk: {e}")
        return None


def _prune_tmp_images() -> None:
    """Delete files in tmp_pins older than TTL (runs opportunistically)."""
    cutoff = time.time() - _TMP_TTL_SECONDS
    for f in _TMP_DIR.glob("*.jpg"):
        try:
            if f.stat().st_mtime < cutoff:
                f.unlink()
                logger.debug(f"🗑️  Pruned stale temp image: {f.name}")
        except Exception:
            pass


def _extract_image_bytes(response) -> bytes:
    """Pull the first IMAGE part out of a Gemini generate_content response."""
    for part in response.candidates[0].content.parts:
        if part.inline_data and part.inline_data.data:
            return part.inline_data.data
    raise ValueError("Gemini response contained no image data in any part.")


# ─────────────────────────────────────────────────────────────────────────────
# Gemini image generators — sync, tenacity-decorated, run via asyncio.to_thread
# ─────────────────────────────────────────────────────────────────────────────

@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=2, min=6, max=60),  # 10 RPM → 6 s minimum
    stop=stop_after_attempt(4),
    reraise=True,
)
def _img2img_sync(source_bytes: bytes, prompt: str) -> bytes:
    """
    Image-to-Image generation.
    Sends the product photo + CMO aesthetic direction to Gemini.
    Gemini natively blends the product into a high-end Pinterest scene,
    adding any requested text as native image elements.
    """
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY is not configured.")

    image_part = genai_types.Part.from_bytes(
        data=source_bytes,
        mime_type="image/jpeg",
    )
    response = _gemini_client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=[image_part, prompt],
        config=genai_types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    return _extract_image_bytes(response)


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=2, min=6, max=60),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _txt2img_sync(prompt: str) -> bytes:
    """
    Text-to-Image generation.
    Pure CMO prompt → Gemini standalone aesthetic visual (no source product).
    Used for "Algorithmic Viral-Bait" strategy.
    """
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY is not configured.")

    response = _gemini_client.models.generate_content(
        model=GEMINI_IMAGE_MODEL,
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
        ),
    )
    return _extract_image_bytes(response)


# ─────────────────────────────────────────────────────────────────────────────
# Async image orchestrator
# ─────────────────────────────────────────────────────────────────────────────

async def _generate_ai_image(
    strategy_name: str,
    cmo_strategy: dict,
    raw_image_url: str,
    account_label: str,
) -> str | None:
    """
    Orchestrate the correct Gemini image mode based on CMO strategy.
    Returns a public URL to the generated image, or None on total failure.
    The caller falls back to raw_image_url when None is returned.
    """
    _prune_tmp_images()

    # Pull the first image_prompt the CMO produced for this account
    image_prompt_direction = (
        cmo_strategy.get("image_prompts") or ["aesthetic Pinterest pin"]
    )[0]
    vibe = cmo_strategy.get("vibe", "aspirational and aesthetic")
    is_viral_bait = "Viral-Bait" in strategy_name

    if is_viral_bait:
        # ── Mode: Text-to-Image ───────────────────────────────────────────────
        full_prompt = (
            f"Create a stunning, scroll-stopping Pinterest pin image. "
            f"Brand vibe: {vibe}. "
            f"Visual concept: {image_prompt_direction}. "
            f"Style: ultra-high-quality, aspirational, Pinterest-aesthetic. "
            f"No product, no affiliate elements — pure visual appeal."
        )
        logger.info(
            f"🎨 [{account_label}] Viral-Bait → Text-to-Image | "
            f"prompt: '{full_prompt[:80]}...'"
        )
        try:
            image_bytes = await asyncio.to_thread(_txt2img_sync, full_prompt)
            return _save_image(image_bytes)
        except Exception as e:
            logger.error(f"❌ [{account_label}] Text-to-Image failed after all retries: {e}")
            return None

    else:
        # ── Mode: Image-to-Image (Affiliate Strike / Visual Pivot) ────────────
        # Step A: Fetch the product image bytes from the Sheet's image_url
        source_bytes: bytes | None = None
        if raw_image_url:
            try:
                async with httpx.AsyncClient(timeout=25) as client:
                    resp = await client.get(raw_image_url, follow_redirects=True)
                    resp.raise_for_status()
                    source_bytes = resp.content
                logger.info(
                    f"📥 [{account_label}] Source product image fetched "
                    f"({len(source_bytes):,} bytes)"
                )
            except Exception as e:
                logger.warning(
                    f"⚠️  [{account_label}] Could not download source image "
                    f"({e}) — will attempt Text-to-Image fallback."
                )

        if source_bytes:
            # Step B: Image-to-Image — blend product into aesthetic environment
            full_prompt = (
                f"You are a world-class Pinterest visual designer. "
                f"Edit this product image to create a premium, high-aesthetic Pinterest pin. "
                f"Brand vibe: {vibe}. "
                f"Visual direction: {image_prompt_direction}. "
                f"Keep the product clearly visible, centred, and flattering. "
                f"Make the result look aspirational, scroll-stopping, and magazine-quality. "
                f"If the direction requests text in the image, render it natively with elegant typography."
            )
            logger.info(
                f"🖼️  [{account_label}] Affiliate/Visual → Image-to-Image | "
                f"direction: '{image_prompt_direction[:60]}'"
            )
            try:
                image_bytes = await asyncio.to_thread(
                    _img2img_sync, source_bytes, full_prompt
                )
                return _save_image(image_bytes)
            except Exception as e:
                logger.error(
                    f"❌ [{account_label}] Image-to-Image failed after all retries: {e}. "
                    f"Trying Text-to-Image as inner fallback."
                )

        # Step C: Inner fallback — Text-to-Image if source fetch or i2i failed
        txt_prompt = (
            f"Create a stunning Pinterest product-showcase pin. "
            f"Brand vibe: {vibe}. "
            f"Visual concept: {image_prompt_direction}. "
            f"Style: aspirational, high-end, scroll-stopping."
        )
        try:
            image_bytes = await asyncio.to_thread(_txt2img_sync, txt_prompt)
            logger.info(f"🎨 [{account_label}] Inner Text-to-Image fallback succeeded.")
            return _save_image(image_bytes)
        except Exception as e:
            logger.error(
                f"❌ [{account_label}] Text-to-Image inner fallback also failed: {e}. "
                f"Will use raw sheet image_url."
            )
            return None


# ─────────────────────────────────────────────────────────────────────────────
# Per-account publish pipeline
# ─────────────────────────────────────────────────────────────────────────────

async def _execute_for_account(
    account_key: str,
    seo_copy: dict,
    cmo_strategy: dict,
) -> dict:
    """
    Full publish pipeline for one account. Steps:
      1. Fetch next PENDING product from the correct niche pool (from Sheet).
      2. Build SEO copy fields from Node 3 output.
      3. Generate AI image via Gemini → save → get public URL.
         Fallback: use raw image_url from the Sheet if Gemini completely fails.
      4. Determine affiliate link (stripped for Viral-Bait strategy).
      5. Fire existing post_to_pinterest() webhook — untouched.
      6. Mark product as POSTED in the Sheet.

    Returns a status dict. Never raises.
    """
    cfg = _ACCOUNT_CONFIG[account_key]
    account_name = cfg["name"]
    strategy_name = cmo_strategy.get("strategy", "")

    # ── 1. Fetch next pending product ─────────────────────────────────────────
    try:
        products = get_pending_products(limit=1, allowed_niches=cfg["niches"])
    except Exception as e:
        logger.error(f"❌ [{account_name}] get_pending_products failed: {e}")
        return {
            "success": False,
            "message": f"Product fetch failed: {e}",
            "account": account_name,
        }

    if not products:
        logger.warning(
            f"⚠️  [{account_name}] No pending products in niches "
            f"{cfg['niches']}. Skipping."
        )
        return {
            "success": False,
            "message": "No pending products available.",
            "account": account_name,
        }

    product      = products[0]
    niche        = product.get("niche") or cfg["niches"][0]
    raw_img_url  = product.get("image_url", "")
    product_name = product.get("product_name", "Amazing Find")

    # ── 2. Resolve SEO copy ───────────────────────────────────────────────────
    title       = (seo_copy.get("title") or product_name)[:100]
    description = seo_copy.get("description", "")
    tags        = seo_copy.get("tags") or []

    # ── 3. Generate AI image (Gemini) ─────────────────────────────────────────
    ai_image_url = await _generate_ai_image(
        strategy_name=strategy_name,
        cmo_strategy=cmo_strategy,
        raw_image_url=raw_img_url,
        account_label=account_name,
    )

    if ai_image_url:
        final_image_url = ai_image_url
        image_source    = f"gemini [{GEMINI_IMAGE_MODEL}]"
        logger.info(f"✨ [{account_name}] Using Gemini-generated image.")
    else:
        # ── Bulletproof outer fallback: raw Sheet image_url ───────────────────
        logger.warning(
            f"⚠️  [{account_name}] All Gemini attempts exhausted — "
            f"using raw Sheet image_url as final fallback."
        )
        final_image_url = raw_img_url
        image_source    = "sheet-fallback"

    # ── 4. Affiliate link (stripped for Viral-Bait) ───────────────────────────
    affiliate_link = (
        product.get("affiliate_link") or product.get("product_url", "")
    )
    if "Viral-Bait" in strategy_name:
        affiliate_link = ""
        logger.info(f"🎯  [{account_name}] Viral-Bait → affiliate link stripped.")

    # ── 5. Fire existing webhook (untouched) ──────────────────────────────────
    try:
        success = await post_to_pinterest(
            image_url=final_image_url,
            title=title,
            description=description,
            link=affiliate_link,
            tags=tags,
            niche=niche,
            target_account=account_name,
        )
    except Exception as e:
        logger.error(f"❌ [{account_name}] Webhook exception: {e}")
        return {
            "success": False,
            "message": f"Webhook exception: {e}",
            "account": account_name,
        }

    if not success:
        logger.error(f"❌ [{account_name}] Webhook returned a failure status.")
        return {
            "success": False,
            "message": "Webhook returned failure.",
            "account": account_name,
        }

    # ── 6. Mark as POSTED in Sheet ────────────────────────────────────────────
    try:
        mark_as_posted(product_name)
    except Exception as e:
        logger.warning(
            f"⚠️  [{account_name}] mark_as_posted failed ({e}) — "
            f"pin published but Sheet status not updated."
        )

    logger.info(
        f"✅ [{account_name}] POSTED — '{title[:60]}' | "
        f"niche={niche} | strategy={strategy_name} | image={image_source}"
    )
    return {
        "success":      True,
        "message":      f"Posted: {title[:60]}",
        "account":      account_name,
        "niche":        niche,
        "strategy":     strategy_name,
        "image_source": image_source,
        "product":      product_name,
    }


# ─────────────────────────────────────────────────────────────────────────────
# LangGraph node entry point
# ─────────────────────────────────────────────────────────────────────────────

async def node_execution_engine(state: MastermindState) -> dict:
    """
    Node 4 — Execution Engine.
    Runs Account 1 and Account 2 in parallel (asyncio.gather).
    Any unhandled exception is normalised to a failure status dict.
    The graph loop never crashes here.
    """
    logger.info(
        "🚀 [Node 4 — Execution Engine] "
        "Generating AI images & publishing pins for both accounts in parallel..."
    )

    results = await asyncio.gather(
        _execute_for_account(
            "account_1",
            state["a1_final_seo_copy"],
            state["a1_cmo_strategy"],
        ),
        _execute_for_account(
            "account_2",
            state["a2_final_seo_copy"],
            state["a2_cmo_strategy"],
        ),
        return_exceptions=True,
    )

    a1_status, a2_status = results

    if isinstance(a1_status, Exception):
        logger.error(f"❌ [Account 1] Uncaught gather exception: {a1_status}")
        a1_status = {
            "success": False,
            "message": str(a1_status),
            "account": "Account1_HomeDecor",
        }
    if isinstance(a2_status, Exception):
        logger.error(f"❌ [Account 2] Uncaught gather exception: {a2_status}")
        a2_status = {
            "success": False,
            "message": str(a2_status),
            "account": "Account2_Tech",
        }

    a1_icon = "✅" if a1_status["success"] else "❌"
    a2_icon = "✅" if a2_status["success"] else "❌"
    logger.info(
        f"📊 [Node 4 — Done] "
        f"A1 {a1_icon} {a1_status.get('message', '')} "
        f"[{a1_status.get('image_source', '')}] | "
        f"A2 {a2_icon} {a2_status.get('message', '')} "
        f"[{a2_status.get('image_source', '')}]"
    )

    return {
        "a1_publish_status": a1_status,
        "a2_publish_status": a2_status,
    }
