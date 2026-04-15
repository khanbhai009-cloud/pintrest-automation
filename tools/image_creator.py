"""
tools/image_creator.py — Text-to-Image Generation & ImgBB Hosting

Handles:
- Text-to-Image: Pollinations (primary) → Puter free (fallback)
- ImgBB mandatory upload gateway

Image-to-Image (I2I) has been removed. AFFILIATE_PIN uses the raw product
image URL directly — no AI image processing required.

Usage:
    from tools.image_creator import generate_pin_image

    imgbb_url = await generate_pin_image(visual_prompt="coffee pour ceramic mug")
"""

import base64
import logging
import os
import re
import urllib.parse
import uuid
from typing import Optional

import httpx
from putergenai import PuterClient

logger = logging.getLogger(__name__)

IMGBB_API_KEY  = os.getenv("IMGBB_API_KEY")
PUTER_USERNAME = os.getenv("PUTER_USERNAME")
PUTER_PASSWORD = os.getenv("PUTER_PASSWORD")


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
    """Upload bytes to ImgBB (mandatory gateway before Pinterest webhook)."""
    if not IMGBB_API_KEY:
        logger.error("❌ [ImgBB] IMGBB_API_KEY not set.")
        return None

    encoded = base64.b64encode(image_bytes).decode("utf-8")
    logger.info(f"⬆️  [ImgBB] Uploading {len(image_bytes)} bytes...")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.imgbb.com/1/upload",
                data={"key": IMGBB_API_KEY, "image": encoded, "expiration": "1800"},
            )
            resp.raise_for_status()
            data = resp.json()
        url = data["data"]["url"]
        logger.info(f"✅ [ImgBB] Hosted: {url}")
        return url
    except Exception as e:
        logger.error(f"❌ [ImgBB] Upload failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Text-to-Image paths
# ─────────────────────────────────────────────────────────────────────────────

async def _t2i_pollinations(prompt: str) -> Optional[bytes]:
    """Primary T2I: Pollinations.ai (free, no key required)."""
    short_prompt = prompt[:200]
    clean_prompt = re.sub(r'[^\w\s,]', '', short_prompt)
    encoded = urllib.parse.quote(f"{clean_prompt}, ultra-realistic, 8k")
    seed = uuid.uuid4().int % 99999
    url = (
        f"https://pollinations.ai/p/{encoded}"
        f"?width=1024&height=1792&nologo=true&model=flux&seed={seed}"
    )
    logger.info("🎨 [T2I-Pollinations] Requesting image...")
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
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


async def _t2i_puter_free(prompt: str) -> Optional[bytes]:
    """Fallback T2I: Puter.js free tier (username/password auth)."""
    if not PUTER_USERNAME or not PUTER_PASSWORD:
        logger.warning("⚠️ [T2I-Puter-Free] Puter credentials not set.")
        return None
    try:
        async with PuterClient() as client:
            await client.login(PUTER_USERNAME, PUTER_PASSWORD)
            image_url = await client.ai_txt2img(
                f"{prompt}, ultra-realistic, 8k, Pinterest portrait",
                model="pollinations-image",
            )
            logger.info(f"✅ [T2I-Puter-Free] Generated: {image_url[:60]}...")
            return await _download_bytes(image_url)
    except Exception as e:
        logger.error(f"❌ [T2I-Puter-Free] Failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public function
# ─────────────────────────────────────────────────────────────────────────────

async def generate_pin_image(visual_prompt: str) -> Optional[str]:
    """
    Generate a VIRAL_PIN image from a text prompt and return an ImgBB URL.

    Args:
        visual_prompt: Detailed aesthetic prompt for the T2I generator.

    Returns:
        ImgBB hosted URL string, or None if all paths fail.

    Note:
        AFFILIATE_PIN does not call this function — it uses the raw product
        image_url directly (no AI generation needed).
    """
    logger.info("🎨 [Image] TEXT-TO-IMAGE pipeline starting...")

    image_bytes = await _t2i_pollinations(visual_prompt)
    if not image_bytes:
        logger.warning("⚠️ [Image] Pollinations failed — trying Puter free fallback...")
        image_bytes = await _t2i_puter_free(visual_prompt)

    if not image_bytes:
        logger.error("❌ [Image] All T2I generation paths failed.")
        return None

    return await _upload_to_imgbb(image_bytes)


async def upload_raw_image(image_url: str) -> Optional[str]:
    """
    Download a raw product image URL and re-host it on ImgBB.
    Used by AFFILIATE_PIN to ensure Pinterest gets a stable hosted URL.

    Args:
        image_url: Direct product image URL (e.g. from Amazon/AliExpress).

    Returns:
        ImgBB hosted URL string, or None on failure.
    """
    logger.info(f"⬇️  [Image] Downloading raw product image: {image_url[:60]}...")
    image_bytes = await _download_bytes(image_url)
    if not image_bytes:
        logger.error("❌ [Image] Failed to download raw product image.")
        return None
    return await _upload_to_imgbb(image_bytes)
