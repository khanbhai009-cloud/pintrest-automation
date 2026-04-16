"""
tools/image_creator.py — Triple-Layer T2I with Retry Logic

PIPELINE (in order):
  1. PRIMARY   — Google Gemini      (gemini-2.5-flash-preview-image-generation)
  2. SECONDARY — OpenRouter         (black-forest-labs/flux-1.1-pro)
  3. TERTIARY  — Pollinations.ai    (free URL-based, no API key)

RULES per model:
  • Each model gets exactly 2 chances  (1st try + 1 retry).
  • Timeout per API call = 180 seconds (3 minutes).
  • A 3-second delay fires ONLY when a call fails (exception OR image < 5 000 bytes).
  • If both tries of a model fail → move to the next model immediately.
  • No unconditional sleep between models or at startup.

Public API:
    generate_pin_image(visual_prompt)  → ImgBB URL  (VIRAL_PIN)
    upload_raw_image(image_url)        → ImgBB URL  (AFFILIATE_PIN)
"""

import asyncio
import base64
import logging
import os
import urllib.parse
from typing import Optional

import httpx
from google import genai
from google.genai import types as genai_types

from config import GEMINI_API_KEY, GEMINI_IMAGE_MODEL, IMGBB_API_KEY, OPENROUTER_API_KEY

logger = logging.getLogger(__name__)

# ── Clients ───────────────────────────────────────────────────────────────────
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── Constants ─────────────────────────────────────────────────────────────────
_CALL_TIMEOUT    = 180    # seconds per API call
_RETRY_DELAY     = 3      # seconds — only on failure or bad image
_MIN_VALID_BYTES = 5_000  # images smaller than this are treated as failures
_MAX_RETRIES     = 2      # total attempts per model (1 try + 1 retry)

_OPENROUTER_IMAGE_URL  = "https://openrouter.ai/api/v1/images/generations"
_OPENROUTER_IMAGE_MODEL = "black-forest-labs/flux-1.1-pro"

_POLLINATIONS_BASE = "https://image.pollinations.ai/prompt"


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _download_bytes(url: str, timeout: int = _CALL_TIMEOUT) -> Optional[bytes]:
    """Download raw bytes from any public URL."""
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


def _is_valid(image_bytes: Optional[bytes]) -> bool:
    """Return True only when bytes exist and meet the minimum size threshold."""
    return bool(image_bytes) and len(image_bytes) >= _MIN_VALID_BYTES


# ─────────────────────────────────────────────────────────────────────────────
# Model 1 — Google Gemini
# ─────────────────────────────────────────────────────────────────────────────

async def _gemini_once(prompt: str) -> Optional[bytes]:
    """Single Gemini call — returns image bytes or None."""
    if not _gemini_client:
        raise RuntimeError("GEMINI_API_KEY not configured.")

    enhanced = (
        f"{prompt[:400]}, ultra-realistic, high quality, Pinterest aesthetic, "
        "9:16 portrait aspect ratio, vibrant colors, professional photography style"
    )

    def _sync_call():
        return _gemini_client.models.generate_content(
            model=GEMINI_IMAGE_MODEL,
            contents=enhanced,
            config=genai_types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

    # Run blocking SDK call in thread pool; asyncio timeout wraps the await
    response = await asyncio.wait_for(
        asyncio.to_thread(_sync_call),
        timeout=_CALL_TIMEOUT,
    )

    for part in response.candidates[0].content.parts:
        if part.inline_data is not None:
            raw = part.inline_data.data
            return bytes(raw) if isinstance(raw, (bytes, bytearray)) else base64.b64decode(raw)

    raise ValueError("Gemini response contained no IMAGE part.")


async def _t2i_gemini(prompt: str) -> Optional[bytes]:
    """
    Primary model — Gemini.
    2 attempts max. 3-second delay only on failure or invalid image.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [Gemini] Attempt {attempt}/{_MAX_RETRIES} | model={GEMINI_IMAGE_MODEL}")
            img = await _gemini_once(prompt)
            if _is_valid(img):
                logger.info(f"✅ [Gemini] Success ({len(img):,} bytes) on attempt {attempt}")
                return img
            logger.warning(
                f"⚠️ [Gemini] Attempt {attempt}: image too small "
                f"({len(img) if img else 0} bytes < {_MIN_VALID_BYTES})"
            )
        except Exception as e:
            logger.warning(f"⚠️ [Gemini] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            logger.info(f"⏳ [Gemini] Waiting {_RETRY_DELAY}s before retry...")
            await asyncio.sleep(_RETRY_DELAY)

    logger.error(f"❌ [Gemini] All {_MAX_RETRIES} attempts failed — moving to fallback.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Model 2 — OpenRouter (black-forest-labs/flux-1.1-pro)
# ─────────────────────────────────────────────────────────────────────────────

async def _openrouter_once(prompt: str) -> Optional[bytes]:
    """Single OpenRouter image-generation call — returns image bytes or None."""
    if not OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY not configured.")

    headers = {
        "Authorization":  f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type":   "application/json",
        "HTTP-Referer":   "https://pinteresto.app",
        "X-Title":        "Pinteresto AI",
    }
    payload = {
        "model":  _OPENROUTER_IMAGE_MODEL,
        "prompt": f"{prompt[:500]}, ultra-realistic, Pinterest portrait 9:16, 8k",
        "n":      1,
        "size":   "1024x1792",
    }

    async with httpx.AsyncClient(timeout=_CALL_TIMEOUT) as client:
        resp = await client.post(_OPENROUTER_IMAGE_URL, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # OpenAI-compatible response: data[0].url  OR  data[0].b64_json
    item = data["data"][0]
    if "b64_json" in item and item["b64_json"]:
        return base64.b64decode(item["b64_json"])
    if "url" in item and item["url"]:
        return await _download_bytes(item["url"])

    raise ValueError("OpenRouter response has no usable image data.")


async def _t2i_openrouter(prompt: str) -> Optional[bytes]:
    """
    Secondary model — OpenRouter FLUX.
    2 attempts max. 3-second delay only on failure or invalid image.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(
                f"🎨 [OpenRouter] Attempt {attempt}/{_MAX_RETRIES} "
                f"| model={_OPENROUTER_IMAGE_MODEL}"
            )
            img = await _openrouter_once(prompt)
            if _is_valid(img):
                logger.info(f"✅ [OpenRouter] Success ({len(img):,} bytes) on attempt {attempt}")
                return img
            logger.warning(
                f"⚠️ [OpenRouter] Attempt {attempt}: image too small "
                f"({len(img) if img else 0} bytes < {_MIN_VALID_BYTES})"
            )
        except Exception as e:
            logger.warning(f"⚠️ [OpenRouter] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            logger.info(f"⏳ [OpenRouter] Waiting {_RETRY_DELAY}s before retry...")
            await asyncio.sleep(_RETRY_DELAY)

    logger.error(f"❌ [OpenRouter] All {_MAX_RETRIES} attempts failed — moving to fallback.")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Model 3 — Pollinations.ai (free, no API key)
# ─────────────────────────────────────────────────────────────────────────────

async def _pollinations_once(prompt: str) -> Optional[bytes]:
    """Single Pollinations.ai URL call — returns image bytes or None."""
    full_prompt = f"{prompt[:400]}, ultra-realistic, 8k, Pinterest portrait 9:16"
    encoded = urllib.parse.quote(full_prompt)
    url = (
        f"{_POLLINATIONS_BASE}/{encoded}"
        "?width=768&height=1365&nologo=true&enhance=true&model=flux"
    )
    img = await _download_bytes(url, timeout=_CALL_TIMEOUT)
    if img is None:
        raise RuntimeError("Pollinations.ai download returned None.")
    return img


async def _t2i_pollinations(prompt: str) -> Optional[bytes]:
    """
    Tertiary model — Pollinations.ai.
    2 attempts max. 3-second delay only on failure or invalid image.
    """
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [Pollinations] Attempt {attempt}/{_MAX_RETRIES}")
            img = await _pollinations_once(prompt)
            if _is_valid(img):
                logger.info(f"✅ [Pollinations] Success ({len(img):,} bytes) on attempt {attempt}")
                return img
            logger.warning(
                f"⚠️ [Pollinations] Attempt {attempt}: image too small "
                f"({len(img) if img else 0} bytes < {_MIN_VALID_BYTES})"
            )
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
    """
    Generate a VIRAL_PIN image and return an ImgBB-hosted URL.

    Triple-layer fallback:
        Layer 1 — Gemini       (2 tries, 3s delay on fail)
        Layer 2 — OpenRouter   (2 tries, 3s delay on fail)
        Layer 3 — Pollinations (2 tries, 3s delay on fail)

    Each model completes before the next is tried.
    No delay between models (we move immediately after all retries exhaust).
    Returns ImgBB URL on success, None if all 6 total attempts fail.
    """
    logger.info("🎨 [Image Pipeline] VIRAL_PIN — starting triple-layer T2I...")

    # ── Layer 1: Gemini ──────────────────────────────────────────────────────
    image_bytes = await _t2i_gemini(visual_prompt)

    # ── Layer 2: OpenRouter ──────────────────────────────────────────────────
    if not image_bytes:
        logger.info("🔄 [Image Pipeline] Gemini exhausted — trying OpenRouter FLUX...")
        image_bytes = await _t2i_openrouter(visual_prompt)

    # ── Layer 3: Pollinations ────────────────────────────────────────────────
    if not image_bytes:
        logger.info("🔄 [Image Pipeline] OpenRouter exhausted — trying Pollinations.ai...")
        image_bytes = await _t2i_pollinations(visual_prompt)

    if not image_bytes:
        logger.error("❌ [Image Pipeline] All 3 models × 2 attempts exhausted. Cannot generate image.")
        return None

    return await _upload_to_imgbb(image_bytes)


async def upload_raw_image(image_url: str) -> Optional[str]:
    """
    Download a raw product image and re-host it on ImgBB.

    Used by AFFILIATE_PIN — no AI generation involved.
    Ensures Pinterest receives a stable hosted URL instead of
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
