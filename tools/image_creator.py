"""
tools/image_creator.py — Text-to-Image Generation & ImgBB Hosting

PRIMARY:  Google Gemini (gemini-2.5-flash-preview-image)
          Free tier limits: 15 RPM | 1,500 RPD
          Rate limiting:    time.sleep(60) runs BEFORE every Gemini call to
                            prevent 429 Too Many Requests on the free tier.
                            A second asyncio.sleep(60) in the finally block
                            provides an additional post-call safety buffer.

FALLBACK: Pollinations.ai (free, no API key required)
          Called automatically whenever Gemini raises any exception.

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
import time
import urllib.parse
from typing import Optional

import httpx
from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GEMINI_IMAGE_MODEL

logger = logging.getLogger(__name__)

# ── Environment keys ─────────────────────────────────────────────────────────
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")

# ── Gemini client ─────────────────────────────────────────────────────────────
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── Rate-limit constants ──────────────────────────────────────────────────────
_GEMINI_PRE_CALL_SLEEP  = 60   # seconds — sleep BEFORE calling Gemini (prevents 429)
_GEMINI_POST_CALL_SLEEP = 60   # seconds — sleep AFTER call in finally block (safety buffer)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _download_bytes(url: str, timeout: int = 90) -> Optional[bytes]:
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

    Model : gemini-2.5-flash-preview-image  (configurable via GEMINI_IMAGE_MODEL)
    Ratio : 9:16 portrait (optimal for Pinterest pins)
    Limits: 15 RPM / 1,500 RPD (free tier)

    Rate limiting strategy:
      1. time.sleep(60) runs BEFORE the API call — stops 429 before it happens.
      2. asyncio.sleep(60) in the finally block — additional post-call buffer.
      Both are mandatory on the free tier.
    """
    if not _gemini_client:
        logger.warning("⚠️ [T2I-Gemini] GEMINI_API_KEY not configured — skipping.")
        return None

    enhanced_prompt = (
        f"{prompt[:400]}, "
        "ultra-realistic, high quality, Pinterest aesthetic, "
        "9:16 portrait aspect ratio, vibrant colors, professional photography style"
    )

    # ── MANDATORY PRE-CALL SLEEP ──────────────────────────────────────────────
    # Runs synchronously (blocks the thread) before the API request.
    # Prevents 429 Too Many Requests on Gemini free tier (15 RPM limit).
    logger.info(
        f"⏳ [T2I-Gemini] Pre-call rate-limit sleep: {_GEMINI_PRE_CALL_SLEEP}s "
        f"(free tier guard — prevents 429)..."
    )
    await asyncio.to_thread(time.sleep, _GEMINI_PRE_CALL_SLEEP)

    logger.info(f"🎨 [T2I-Gemini] Requesting image | model={GEMINI_IMAGE_MODEL}")
    image_bytes: Optional[bytes] = None

    try:
        def _call_sync() -> genai_types.GenerateContentResponse:
            return _gemini_client.models.generate_content(
                model=GEMINI_IMAGE_MODEL,
                contents=enhanced_prompt,
                config=genai_types.GenerateContentConfig(
                    response_modalities=["IMAGE"],
                ),
            )

        response = await asyncio.to_thread(_call_sync)

        for part in response.candidates[0].content.parts:
            if part.inline_data is not None:
                raw = part.inline_data.data
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
        # ── POST-CALL SAFETY BUFFER ───────────────────────────────────────────
        logger.info(
            f"⏳ [T2I-Gemini] Post-call buffer sleep: {_GEMINI_POST_CALL_SLEEP}s..."
        )
        await asyncio.sleep(_GEMINI_POST_CALL_SLEEP)


# ─────────────────────────────────────────────────────────────────────────────
# Fallback T2I — Pollinations.ai (free, no API key required)
# ─────────────────────────────────────────────────────────────────────────────

async def _t2i_pollinations(prompt: str) -> Optional[bytes]:
    """
    Fallback T2I: Pollinations.ai free image generation API.
    Called automatically when Gemini fails for any reason (quota, 429, error).
    No API key required. Returns image bytes on success, None on failure.
    """
    try:
        full_prompt = f"{prompt}, ultra-realistic, 8k, Pinterest portrait 9:16"
        encoded     = urllib.parse.quote(full_prompt)
        url = (
            f"https://image.pollinations.ai/prompt/{encoded}"
            "?width=768&height=1365&nologo=true&enhance=true&model=flux"
        )
        logger.info(f"🎨 [T2I-Pollinations] Requesting fallback image...")
        image_bytes = await _download_bytes(url, timeout=120)
        if image_bytes:
            logger.info(f"✅ [T2I-Pollinations] Success — {len(image_bytes):,} bytes.")
        return image_bytes
    except Exception as e:
        logger.error(f"❌ [T2I-Pollinations] Fallback failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public functions
# ─────────────────────────────────────────────────────────────────────────────

async def generate_pin_image(visual_prompt: str) -> Optional[str]:
    """
    Generate a VIRAL_PIN image and return an ImgBB-hosted URL.

    Pipeline:
        1. Gemini (gemini-2.5-flash-preview-image) — primary
           • time.sleep(60) before call   — prevents 429
           • asyncio.sleep(60) after call — post-call buffer
        2. Pollinations.ai                — fallback, no key needed

    Args:
        visual_prompt: Detailed aesthetic T2I prompt from the CMO Mastermind.

    Returns:
        ImgBB URL string ("https://i.ibb.co/..."), or None if all paths fail.
    """
    logger.info("🎨 [Image Pipeline] VIRAL_PIN — T2I generation starting...")

    # Step 1 — Primary: Gemini
    image_bytes = await _t2i_gemini(visual_prompt)

    # Step 2 — Fallback: Pollinations.ai
    if not image_bytes:
        logger.warning("⚠️ [Image Pipeline] Gemini failed — trying Pollinations.ai fallback...")
        image_bytes = await _t2i_pollinations(visual_prompt)

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
