"""
tools/image_creator.py — Dual-Layer T2I Image Pipeline

MODELS (in order):
  1. Cloudflare   — @cf/black-forest-labs/flux-1-schnell (Primary, Fast & High Quality)
  2. Pollinations — free, URL-based, 4K quality (Fallback)

RATIO SUPPORT:
  • 9:16 portrait → 1080x1920  (primary, Pinterest-native)
  • 1:1 square    → 1080x1080  (alternate, carousel-friendly)

QUALITY:
  • All prompts auto-enriched with "4K ultra HD, photorealistic"
  • ImgBB: permanent hosting (no expiration)
"""

import asyncio
import base64
import logging
import urllib.parse
from typing import Optional

import httpx

from config import (
    IMGBB_API_KEY, 
    CLOUDFLARE_ACCOUNT_ID, 
    CLOUDFLARE_API_TOKEN, 
    CLOUDFLARE_IMAGE_MODEL, 
    POLLINATIONS_MODEL
)

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_CALL_TIMEOUT    = 180
_RETRY_DELAY     = 3
_MIN_VALID_BYTES = 5_000
_MAX_RETRIES     = 2

_RATIO_DIMS = {
    "9:16": (1080, 1920),
    "1:1":  (1080, 1080),
}

_POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _enrich_prompt(prompt: str, max_chars: int = 480) -> str:
    """Append 4K quality tag if not already present, then truncate."""
    base = prompt.strip()
    if "4K" not in base and "4k" not in base:
        base += ", 4K ultra HD, photorealistic"
    return base[:max_chars]


def _get_dims(ratio: str) -> tuple[int, int]:
    return _RATIO_DIMS.get(ratio, _RATIO_DIMS["9:16"])


async def _download_bytes(url: str, timeout: int = _CALL_TIMEOUT) -> Optional[bytes]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.error(f"❌ Download failed [{url[:60]}]: {e}")
        return None


async def _upload_to_imgbb(image_bytes: bytes) -> Optional[str]:
    if not IMGBB_API_KEY:
        logger.error("❌ [ImgBB] IMGBB_API_KEY not set.")
        return None
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    logger.info(f"⬆️  [ImgBB] Uploading {len(image_bytes):,} bytes (permanent)...")
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.imgbb.com/1/upload",
                data={"key": IMGBB_API_KEY, "image": encoded},
            )
            resp.raise_for_status()
            url = resp.json()["data"]["url"]
        logger.info(f"✅ [ImgBB] Hosted: {url}")
        return url
    except Exception as e:
        logger.error(f"❌ [ImgBB] Upload failed: {e}")
        return None


def _is_valid(image_bytes: Optional[bytes]) -> bool:
    return bool(image_bytes) and len(image_bytes) >= _MIN_VALID_BYTES


# ── Model 1: Cloudflare Workers AI ─────────────────────────────────────────────

async def _cloudflare_once(prompt: str, ratio: str) -> Optional[bytes]:
    if not CLOUDFLARE_ACCOUNT_ID or not CLOUDFLARE_API_TOKEN:
        raise RuntimeError("CLOUDFLARE_ACCOUNT_ID or CLOUDFLARE_API_TOKEN not configured.")

    w, h     = _get_dims(ratio)
    # Flux-1-schnell needs resolution context in prompt
    enriched = _enrich_prompt(f"{prompt}, portrait {w}x{h} size")

    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}/ai/run/{CLOUDFLARE_IMAGE_MODEL}"
    
    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type":  "application/json"
    }
    
    payload = {
        "prompt": enriched,
        "num_steps": 8  # Higher steps = better quality for Flux Schnell
    }

    async with httpx.AsyncClient(timeout=_CALL_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        
        # FIX: Extract base64 image string from Cloudflare's JSON response
        if "application/json" in resp.headers.get("content-type", "").lower():
            data = resp.json()
            b64_str = data.get("result", {}).get("image", "")
            if b64_str:
                return base64.b64decode(b64_str)
            else:
                logger.error(f"❌ [Cloudflare] No image data found in JSON response: {str(data)[:200]}")
                return None
        else:
            # Fallback if it returns direct bytes (unlikely but safe)
            return resp.content


async def _t2i_cloudflare(prompt: str, ratio: str) -> Optional[bytes]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [Cloudflare] Attempt {attempt}/{_MAX_RETRIES} | ratio={ratio}")
            img = await _cloudflare_once(prompt, ratio)
            if _is_valid(img):
                logger.info(f"✅ [Cloudflare] {len(img):,} bytes on attempt {attempt}")
                return img
            logger.warning(f"⚠️ [Cloudflare] Attempt {attempt}: image too small or invalid")
        except Exception as e:
            logger.warning(f"⚠️ [Cloudflare] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAY)

    logger.error("❌ [Cloudflare] All attempts failed — moving to Pollinations.")
    return None


# ── Model 2: Pollinations.ai (Fallback) ────────────────────────────────────────

async def _pollinations_once(prompt: str, ratio: str) -> Optional[bytes]:
    w, h     = _get_dims(ratio)
    enriched = _enrich_prompt(prompt, max_chars=400)
    encoded  = urllib.parse.quote(enriched)
    url      = (
        f"{_POLLINATIONS_BASE}/{encoded}"
        f"?width={w}&height={h}&nologo=true&enhance=true&model={POLLINATIONS_MODEL}&quality=high"
    )
    logger.info(f"🎨 [Pollinations] {w}x{h} | ratio={ratio}")
    img = await _download_bytes(url, timeout=_CALL_TIMEOUT)
    if img is None:
        raise RuntimeError("Pollinations download returned None.")
    return img


async def _t2i_pollinations(prompt: str, ratio: str) -> Optional[bytes]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [Pollinations] Attempt {attempt}/{_MAX_RETRIES}")
            img = await _pollinations_once(prompt, ratio)
            if _is_valid(img):
                logger.info(f"✅ [Pollinations] {len(img):,} bytes on attempt {attempt}")
                return img
            logger.warning(f"⚠️ [Pollinations] Attempt {attempt}: image too small")
        except Exception as e:
            logger.warning(f"⚠️ [Pollinations] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAY)

    logger.error("❌ [Pollinations] All attempts failed.")
    return None


# ── Public API ─────────────────────────────────────────────────────────────────

async def generate_pin_image(visual_prompt: str, ratio: str = "9:16") -> Optional[str]:
    """Generate a VIRAL_PIN image using the T2I pipeline and upload to ImgBB."""
    w, h = _get_dims(ratio)
    logger.info(f"🎨 [Image Pipeline] VIRAL_PIN | ratio={ratio} ({w}x{h}) | 4K quality")

    # PRIMARY: Cloudflare
    image_bytes = await _t2i_cloudflare(visual_prompt, ratio)

    # FALLBACK: Pollinations
    if not image_bytes:
        logger.info("🔄 [Image Pipeline] Cloudflare exhausted — trying Pollinations...")
        image_bytes = await _t2i_pollinations(visual_prompt, ratio)

    if not image_bytes:
        logger.error("❌ [Image Pipeline] All models exhausted — no image generated.")
        return None

    return await _upload_to_imgbb(image_bytes)


async def upload_raw_image(image_url: str) -> Optional[str]:
    """Download an affiliate product image and re-host on ImgBB."""
    logger.info(f"⬇️  [Image Pipeline] AFFILIATE_PIN — downloading: {image_url[:60]}...")
    image_bytes = await _download_bytes(image_url)
    if not image_bytes:
        logger.error("❌ [Image Pipeline] Product image download failed.")
        return None
    return await _upload_to_imgbb(image_bytes)
