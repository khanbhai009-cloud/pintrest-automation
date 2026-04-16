"""
tools/image_creator.py — Dual-Layer T2I Image Pipeline

MODELS (in order):
  1. OpenRouter   — black-forest-labs/flux.2-pro
  2. Pollinations — free, URL-based, 4K quality

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

from config import IMGBB_API_KEY, OPENROUTER_API_KEY, OPENROUTER_IMAGE_MODEL, POLLINATIONS_MODEL

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

_OPENROUTER_URL   = "https://openrouter.ai/api/v1/chat/completions"
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


# ── Model 1: OpenRouter ────────────────────────────────────────────────────────

async def _openrouter_once(prompt: str, ratio: str) -> Optional[bytes]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured.")

    w, h      = _get_dims(ratio)
    enriched  = _enrich_prompt(f"{prompt}, {w}x{h}")

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":  "application/json",
        "HTTP-Referer":  "https://pinteresto.app",
        "X-Title":       "Pinteresto AI",
    }
    payload = {
        "model":      OPENROUTER_IMAGE_MODEL,
        "messages":   [{"role": "user", "content": enriched}],
        "modalities": ["image"],
    }

    async with httpx.AsyncClient(timeout=_CALL_TIMEOUT) as client:
        resp = await client.post(_OPENROUTER_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    try:
        message = data["choices"][0]["message"]
        images  = message.get("images", [])
        if images:
            img_url = images[0]["image_url"]["url"]
            if "base64," in img_url:
                return base64.b64decode(img_url.split("base64,")[1])
            return await _download_bytes(img_url)
    except (KeyError, IndexError) as e:
        logger.error(f"❌ [OpenRouter] Parse error: {e} | {str(data)[:200]}")
        raise ValueError("OpenRouter response had no image data.")

    raise ValueError("OpenRouter response had no usable image.")


async def _t2i_openrouter(prompt: str, ratio: str) -> Optional[bytes]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [OpenRouter] Attempt {attempt}/{_MAX_RETRIES} | ratio={ratio}")
            img = await _openrouter_once(prompt, ratio)
            if _is_valid(img):
                logger.info(f"✅ [OpenRouter] {len(img):,} bytes on attempt {attempt}")
                return img
            logger.warning(f"⚠️ [OpenRouter] Attempt {attempt}: image too small")
        except Exception as e:
            logger.warning(f"⚠️ [OpenRouter] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAY)

    logger.error("❌ [OpenRouter] All attempts failed — moving to Pollinations.")
    return None


# ── Model 2: Pollinations.ai ───────────────────────────────────────────────────

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

    image_bytes = await _t2i_openrouter(visual_prompt, ratio)

    if not image_bytes:
        logger.info("🔄 [Image Pipeline] OpenRouter exhausted — trying Pollinations...")
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
