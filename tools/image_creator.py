"""
tools/image_creator.py — Text-to-Image Generation & ImgBB Hosting

PRIMARY:  Google Gemini (gemini-2.5-flash-image)
          Free tier limits: 15 RPM | 1,500 RPD
          Rate limiting:    60-second mandatory delay after EVERY request
                            (success OR failure) to stay well within 15 RPM
                            and prevent spamming / quota exhaustion.

FALLBACK: Puter.js free tier (username/password auth)

Image-to-Image (I2I) has been removed. AFFILIATE_PIN uses the raw product
image URL directly — no AI image processing required.

Public API:
    generate_pin_image(visual_prompt)  → ImgBB URL  (VIRAL_PIN)
    upload_raw_image(image_url)        → ImgBB URL  (AFFILIATE_PIN)
"""

import asyncio
import base64
import logging
import os
from typing import Optional

import httpx
from google import genai
from google.genai import types as genai_types
from putergenai import PuterClient

from config import GEMINI_API_KEY, GEMINI_IMAGE_MODEL

logger = logging.getLogger(__name__)

# ── Environment keys ─────────────────────────────────────────────────────────
IMGBB_API_KEY  = os.getenv("IMGBB_API_KEY")
PUTER_USERNAME = os.getenv("PUTER_USERNAME")
PUTER_PASSWORD = os.getenv("PUTER_PASSWORD")

# ── Gemini client (shared with node_cmo) ─────────────────────────────────────
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── Rate-limit constants ──────────────────────────────────────────────────────
# Gemini free tier: 15 RPM / 1,500 RPD
# We enforce a strict 60s post-request delay so we never exceed 1 req/min.
# This is far more conservative than 15 RPM but guarantees zero rate errors.
_GEMINI_RATE_LIMIT_DELAY = 60   # seconds


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _download_bytes(url: str, timeout: int = 45) -> Optional[bytes]:
    """Download raw bytes from a public URL."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.error(f"❌ _download_bytes failed [{url[:60]}]: {e}")
        return None


async def _upload_to_imgbb(image_bytes: bytes) -> Optional[str]:
    """Upload raw bytes to ImgBB and return a 30-min public URL."""
    if not IMGBB_API_KEY:
        logger.error("❌ [ImgBB] IMGBB_API_KEY not set.")
        return None

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    logger.info(f"⬆️  [ImgBB] Uploading {len(image_bytes):,} bytes...")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.imgbb.com/1/upload",
                data={"key": IMGBB_API_KEY, "image": encoded, "expiration": "1800"},
            )
            resp.raise_for_status()
            url = resp.json()["data"]["url"]
        logger.info(f"✅ [ImgBB] Hosted: {url}")
        return url
    except Exception as e:
        logger.error(f"❌ [ImgBB] Upload failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Primary T2I — Google Gemini Image Generation
# ─────────────────────────────────────────────────────────────────────────────

async def _t2i_gemini(prompt: str) -> Optional[bytes]:
    """
    Primary T2I: Google Gemini image generation model.

    Model : gemini-2.5-flash-image  (configurable via GEMINI_IMAGE_MODEL)
    Ratio : 9:16 portrait (optimal for Pinterest pins)
    Limits: 15 RPM / 1,500 RPD (free tier)

    Rate limiting strategy:
      A mandatory 60-second sleep runs in the `finally` block after EVERY
      call — whether it succeeds or fails. This ensures:
        • Max throughput = 1 request/minute (well under 15 RPM limit)
        • No quota bursts even if multiple pipeline cycles fire close together
        • Simple, auditable — no need for a token-bucket or sliding window
    """
    if not _gemini_client:
        logger.warning("⚠️ [T2I-Gemini] GEMINI_API_KEY not configured — skipping.")
        return None

    enhanced_prompt = (
        f"{prompt[:400]}, "
        "ultra-realistic, high quality, Pinterest aesthetic, "
        "9:16 portrait aspect ratio, vibrant colors, professional photography style"
    )

    logger.info(f"🎨 [T2I-Gemini] Requesting image | model={GEMINI_IMAGE_MODEL}")
    image_bytes: Optional[bytes] = None

    try:
        # Synchronous Gemini SDK call offloaded to a thread
        def _call_sync() -> genai_types.GenerateContentResponse:
            return _gemini_client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=enhanced_prompt,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )

        response = await asyncio.to_thread(_call_sync)

        # Extract image bytes from the inline_data part
        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                raw = part.inline_data.data
                # SDK may return raw bytes or a base64-encoded string
                if isinstance(raw, (bytes, bytearray)):
                    image_bytes = bytes(raw)
                else:
                    image_bytes = base64.b64decode(raw)
                break

        if not image_bytes:
            raise ValueError("Gemini response contained no IMAGE part.")

        logger.info(f"✅ [T2I-Gemini] Success — {len(image_bytes):,} bytes received.")
        return image_bytes

    except Exception as e:
        logger.error(f"❌ [T2I-Gemini] Image generation failed: {e}")
        return None

    finally:
        # ── MANDATORY RATE-LIMIT DELAY ────────────────────────────────────────
        # Always executes regardless of success/failure.
        # 60 seconds = max 1 request/min = stays well within 15 RPM free tier.
        logger.info(
            f"⏳ [T2I-Gemini] Rate-limit delay: {_GEMINI_RATE_LIMIT_DELAY}s "
            f"(free tier = 15 RPM — 1 req/min enforced)..."
        )
        await asyncio.sleep(_GEMINI_RATE_LIMIT_DELAY)


# ─────────────────────────────────────────────────────────────────────────────
# Fallback T2I — Puter.js Free Tier
# ─────────────────────────────────────────────────────────────────────────────

async def _t2i_puter_free(prompt: str) -> Optional[bytes]:
    """
    Fallback T2I: Puter.js free tier (username/password login, no API key).
    Called only when Gemini is unavailable or returns no image data.
    No artificial delay added — Puter has no strict RPM limits.
    """
    if not PUTER_USERNAME or not PUTER_PASSWORD:
        logger.warning("⚠️ [T2I-Puter] PUTER_USERNAME / PUTER_PASSWORD not set.")
        return None
    try:
        logger.info("🎨 [T2I-Puter] Requesting image (fallback)...")
        async with PuterClient() as client:
            await client.login(PUTER_USERNAME, PUTER_PASSWORD)
            image_url = await client.ai_txt2img(
                f"{prompt}, ultra-realistic, 8k, Pinterest portrait 9:16",
                model="pollinations-image",
            )
        logger.info(f"✅ [T2I-Puter] Generated URL: {image_url[:60]}...")
        return await _download_bytes(image_url)
    except Exception as e:
        logger.error(f"❌ [T2I-Puter] Fallback failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public functions
# ─────────────────────────────────────────────────────────────────────────────

async def generate_pin_image(visual_prompt: str) -> Optional[str]:
    """
    Generate a VIRAL_PIN image and return an ImgBB-hosted URL.

    Pipeline:
        1. Gemini (gemini-2.5-flash-image) — primary, 60s rate-limit delay enforced
        2. Puter.js free tier             — fallback, no delay needed

    Args:
        visual_prompt: Detailed aesthetic T2I prompt from the CMO Mastermind.

    Returns:
        ImgBB URL string ("https://i.ibb.co/..."), or None if all paths fail.

    Note:
        AFFILIATE_PIN skips this entirely — it calls upload_raw_image() instead.
    """
    logger.info("🎨 [Image Pipeline] VIRAL_PIN — T2I generation starting...")

    # Step 1 — Primary: Gemini
    image_bytes = await _t2i_gemini(visual_prompt)

    # Step 2 — Fallback: Puter.js
    if not image_bytes:
        logger.warning("⚠️ [Image Pipeline] Gemini failed — trying Puter fallback...")
        image_bytes = await _t2i_puter_free(visual_prompt)

    if not image_bytes:
        logger.error("❌ [Image Pipeline] All T2I paths exhausted. Cannot generate image.")
        return None

    return await _upload_to_imgbb(image_bytes)


async def upload_raw_image(image_url: str) -> Optional[str]:
    """
    Download a raw product image and re-host it on ImgBB.

    Used by AFFILIATE_PIN — no AI generation involved.
    Ensures Pinterest receives a stable, hosted URL instead of
    an unstable Amazon/CDN URL.

    Args:
        image_url: Direct product image URL from Google Sheets.

    Returns:
        ImgBB URL string, or None on download/upload failure.
    """
    logger.info(f"⬇️  [Image Pipeline] AFFILIATE_PIN — downloading: {image_url[:60]}...")
    image_bytes = await _download_bytes(image_url)
    if not image_bytes:
        logger.error("❌ [Image Pipeline] Raw product image download failed.")
        return None
    return await _upload_to_imgbb(image_bytes)
