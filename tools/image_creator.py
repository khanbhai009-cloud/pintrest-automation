"""
tools/image_creator.py — Dual-Layer T2I with Retry Logic

PIPELINE (in order):
  1. PRIMARY   — OpenRouter         (black-forest-labs/flux.2-pro)
  2. SECONDARY — Pollinations.ai    (free URL-based, no API key)

RULES per model:
  • Each model gets exactly 2 chances  (1st try + 1 retry).
  • Timeout per API call = 180 seconds (3 minutes).
  • A 3-second delay fires ONLY when a call fails (exception OR image < 5 000 bytes).
  • If both tries of a model fail → move to the next model immediately.
"""

import asyncio
import base64
import logging
import urllib.parse
from typing import Optional

import httpx

# Gemini imports aur keys hata diye gaye hain
from config import IMGBB_API_KEY, OPENROUTER_API_KEY

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
_CALL_TIMEOUT    = 180    # seconds per API call
_RETRY_DELAY     = 3      # seconds — only on failure or bad image
_MIN_VALID_BYTES = 5_000  # images smaller than this are treated as failures
_MAX_RETRIES     = 2      # total attempts per model (1 try + 1 retry)

# Sahi OpenRouter API Endpoint
_OPENROUTER_IMAGE_URL   = "https://openrouter.ai/api/v1/chat/completions"
_OPENROUTER_IMAGE_MODEL = "black-forest-labs/flux.2-pro"

_POLLINATIONS_BASE      = "https://image.pollinations.ai/prompt"


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _download_bytes(url: str, timeout: int = _CALL_TIMEOUT) -> Optional[bytes]:
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.content
    except Exception as e:
        logger.error(f"❌ _download_bytes failed [{url[:60]}]: {e}")
        return None

async def _upload_to_imgbb(image_bytes: bytes) -> Optional[str]:
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

def _is_valid(image_bytes: Optional[bytes]) -> bool:
    return bool(image_bytes) and len(image_bytes) >= _MIN_VALID_BYTES


# ─────────────────────────────────────────────────────────────────────────────
# Model 1 — OpenRouter (black-forest-labs/flux.2-pro)
# ─────────────────────────────────────────────────────────────────────────────

async def _openrouter_once(prompt: str) -> Optional[bytes]:
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured.")

    headers = {
        "Authorization":  f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":   "application/json",
        "HTTP-Referer":   "https://pinteresto.app",
        "X-Title":        "Pinteresto AI",
    }
    
    # Correct Payload Structure for Image Generation
    payload = {
        "model":  _OPENROUTER_IMAGE_MODEL,
        "messages": [
            {"role": "user", "content": f"{prompt[:500]}, ultra-realistic, Pinterest portrait 9:16, 8k"}
        ],
        "modalities": ["image"]
    }

    async with httpx.AsyncClient(timeout=_CALL_TIMEOUT) as client:
        resp = await client.post(_OPENROUTER_IMAGE_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Image Extraction Logic (Base64 Decoder)
    try:
        message = data["choices"][0]["message"]
        images = message.get("images", [])
        
        if images:
            img_url = images[0]["image_url"]["url"]
            if "base64," in img_url:
                b64_data = img_url.split("base64,")[1]
                return base64.b64decode(b64_data)
            else:
                return await _download_bytes(img_url)
                
    except (KeyError, IndexError) as e:
        logger.error(f"❌ [OpenRouter] Parse Error: {e} | Data: {str(data)[:200]}")
        raise ValueError("Response structure did not contain image data.")

    raise ValueError("OpenRouter response has no usable image data.")

async def _t2i_openrouter(prompt: str) -> Optional[bytes]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [OpenRouter] Attempt {attempt}/{_MAX_RETRIES} | model={_OPENROUTER_IMAGE_MODEL}")
            img = await _openrouter_once(prompt)
            if _is_valid(img):
                logger.info(f"✅ [OpenRouter] Success ({len(img):,} bytes) on attempt {attempt}")
                return img
            logger.warning(f"⚠️ [OpenRouter] Attempt {attempt}: image too small")
        except Exception as e:
            logger.warning(f"⚠️ [OpenRouter] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            logger.info(f"⏳ [OpenRouter] Waiting {_RETRY_DELAY}s before retry...")
            await asyncio.sleep(_RETRY_DELAY)

    logger.error(f"❌ [OpenRouter] All {_MAX_RETRIES} attempts failed — moving to fallback.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Model 2 — Pollinations.ai (free, no API key)
# ─────────────────────────────────────────────────────────────────────────────

async def _pollinations_once(prompt: str) -> Optional[bytes]:
    full_prompt = f"{prompt[:400]}, ultra-realistic, 8k, Pinterest portrait 9:16"
    encoded = urllib.parse.quote(full_prompt)
    url = f"{_POLLINATIONS_BASE}/{encoded}?width=768&height=1365&nologo=true&enhance=true&model=flux"
    img = await _download_bytes(url, timeout=_CALL_TIMEOUT)
    if img is None:
        raise RuntimeError("Pollinations.ai download returned None.")
    return img

async def _t2i_pollinations(prompt: str) -> Optional[bytes]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [Pollinations] Attempt {attempt}/{_MAX_RETRIES}")
            img = await _pollinations_once(prompt)
            if _is_valid(img):
                logger.info(f"✅ [Pollinations] Success ({len(img):,} bytes) on attempt {attempt}")
                return img
            logger.warning(f"⚠️ [Pollinations] Attempt {attempt}: image too small")
        except Exception as e:
            logger.warning(f"⚠️ [Pollinations] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            logger.info(f"⏳ [Pollinations] Waiting {_RETRY_DELAY}s before retry...")
            await asyncio.sleep(_RETRY_DELAY)

    logger.error(f"❌ [Pollinations] All {_MAX_RETRIES} attempts failed.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Public functions
# ─────────────────────────────────────────────────────────────────────────────

async def generate_pin_image(visual_prompt: str) -> Optional[str]:
    logger.info("🎨 [Image Pipeline] VIRAL_PIN — starting dual-layer T2I...")

    # Layer 1: OpenRouter
    image_bytes = await _t2i_openrouter(visual_prompt)

    # Layer 2: Pollinations
    if not image_bytes:
        logger.info("🔄 [Image Pipeline] OpenRouter exhausted — trying Pollinations.ai...")
        image_bytes = await _t2i_pollinations(visual_prompt)

    if not image_bytes:
        logger.error("❌ [Image Pipeline] All models exhausted. Cannot generate image.")
        return None

    return await _upload_to_imgbb(image_bytes)

async def upload_raw_image(image_url: str) -> Optional[str]:
    logger.info(f"⬇️  [Image Pipeline] AFFILIATE_PIN — downloading: {image_url[:60]}...")
    image_bytes = await _download_bytes(image_url)
    if not image_bytes:
        logger.error("❌ [Image Pipeline] Raw product image download failed.")
        return None
    return await _upload_to_imgbb(image_bytes)
