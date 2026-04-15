"""
tools/image_creator.py — Centralized Image Generation & Hosting

Handles:
- Text-to-Image: Pollinations (primary) → Puter free (fallback)
- Image-to-Image: Puter (edit API) for Aggressive Affiliate Strike
- ImgBB mandatory upload

Usage:
    from tools.image_creator import generate_pin_image

    imgbb_url = await generate_pin_image(
        strategy="Viral-Bait",
        vibe="cozy warm light",
        image_prompt="coffee pour ceramic mug",
        raw_product_image_url="https://amazon.com/product.jpg"
    )
"""

import asyncio
import base64
import logging
import os
import re
import urllib.parse
import uuid
from typing import Optional

import httpx
from putergenai import PuterClient  # free Puter.js SDK

logger = logging.getLogger(__name__)

# ── Environment keys ─────────────────────────────────────────────────────────
IMGBB_API_KEY = os.getenv("IMGBB_API_KEY")
PUTER_API_KEY = os.getenv("PUTER_API_KEY")   # Optional, free mode works without it

# Puter login credentials (free tier)
PUTER_USERNAME = os.getenv("PUTER_USERNAME")      # अपना यूज़रनेम डालें
PUTER_PASSWORD = os.getenv("PUTER_PASSWORD")      # अपना पासवर्ड डालें


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
    """Upload bytes to ImgBB (mandatory gateway)."""
    if not IMGBB_API_KEY:
        logger.error("❌ [ImgBB] IMGBB_API_KEY not set.")
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
    """Primary T2I: Pollinations.ai (free, no key)."""
    # Shorten & clean prompt to avoid filter issues
    short_prompt = prompt[:200]
    clean_prompt = re.sub(r'[^\w\s,]', '', short_prompt)
    encoded = urllib.parse.quote(f"{clean_prompt}, ultra-realistic, 8k")
    seed = uuid.uuid4().int % 99999
    url = (
        f"https://pollinations.ai/p/{encoded}"
        f"?width=1024&height=1792&nologo=true&model=flux&seed={seed}"
    )
    logger.info(f"🎨 [T2I-Pollinations] Requesting...")
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
    """Free Puter.js T2I using username/password (no API key)."""
    if not PUTER_USERNAME or not PUTER_PASSWORD:
        logger.warning("⚠️ [T2I-Puter-Free] Puter credentials not set.")
        return None

    try:
        async with PuterClient() as client:
            await client.login(PUTER_USERNAME, PUTER_PASSWORD)
            # Use a high-quality model (free tier allows many)
            image_url = await client.ai_txt2img(
                f"{prompt}, ultra-realistic, 8k, Pinterest portrait",
                model="pollinations-image"   # or "gpt-image-1.5", "imagen-4-ultra"
            )
            logger.info(f"✅ [T2I-Puter-Free] Generated URL: {image_url[:60]}...")
            return await _download_bytes(image_url)
    except Exception as e:
        logger.error(f"❌ [T2I-Puter-Free] Failed: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Image-to-Image path (Aggressive Affiliate Strike)
# ─────────────────────────────────────────────────────────────────────────────

async def _i2i_puter(product_image_url: str, aesthetic_prompt: str) -> Optional[bytes]:
    """I2I using Puter's edit API (needs PUTER_API_KEY). Falls back to T2I."""
    if not PUTER_API_KEY:
        logger.warning("⚠️ [I2I-Puter] PUTER_API_KEY not set — falling back to T2I.")
        return await _t2i_pollinations(aesthetic_prompt)

    full_prompt = (
        f"Product photograph of item shown in the reference image, "
        f"placed in this environment: {aesthetic_prompt}. "
        f"Ultra-realistic, 8k, Pinterest aesthetic."
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
    logger.info(f"🖼️  [I2I-Puter] Compositing...")
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
            raise ValueError("No image URL in Puter I2I response.")
        logger.info("✅ [I2I-Puter] Composite generated.")
        return await _download_bytes(img_url)
    except Exception as e:
        logger.error(f"❌ [I2I-Puter] Failed: {e}. Falling back to T2I-Pollinations.")
        return await _t2i_pollinations(aesthetic_prompt)


# ─────────────────────────────────────────────────────────────────────────────
# Main orchestrator — public function for agent.py
# ─────────────────────────────────────────────────────────────────────────────

async def generate_pin_image(
    strategy: str,
    vibe: str,
    image_prompt: str,
    raw_product_image_url: str,
) -> Optional[str]:
    """
    Generate an image according to CMO strategy and return an ImgBB URL.

    Args:
        strategy: "Visual Pivot", "Viral-Bait", or "Aggressive Affiliate Strike"
        vibe: CMO's aesthetic command
        image_prompt: CMO's image generation direction
        raw_product_image_url: Original Amazon product image URL

    Returns:
        ImgBB hosted URL, or None if all paths fail.
    """
    composite_prompt = f"{image_prompt}, {vibe}" if image_prompt else vibe
    image_bytes: Optional[bytes] = None

    if "Aggressive Affiliate Strike" in strategy:
        logger.info("🎯 [Image] PATH B — Image-to-Image (Affiliate Strike)")
        image_bytes = await _i2i_puter(raw_product_image_url, composite_prompt)
    else:
        logger.info("🎨 [Image] PATH A — Text-to-Image (Visual Pivot / Viral-Bait)")
        # Try Pollinations first
        image_bytes = await _t2i_pollinations(composite_prompt)
        if not image_bytes:
            logger.warning("⚠️ [Image] Pollinations failed — trying Puter free fallback...")
            image_bytes = await _t2i_puter_free(composite_prompt)

    if not image_bytes:
        logger.error("❌ [Image] All generation paths failed.")
        return None

    # Upload to ImgBB
    return await _upload_to_imgbb(image_bytes)