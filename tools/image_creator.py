"""
tools/image_creator.py — Dual-Layer T2I Image Pipeline  [VARIETY ENGINE v4 — CLEAN & OPTIMIZED]

MODELS (in order):
  1. Cloudflare   — @cf/black-forest-labs/flux-1-schnell (Primary, Fast & High Quality)
  2. Pollinations — free, URL-based, 4K quality (Fallback)

VARIETY ENGINE v4 — What changed from v3:
  REMOVED (were hurting quality):
    ✗ _CAMERA_LENSES    — Flux Schnell ignores real camera specs, produces garbage
    ✗ _EDITORIAL_STYLE  — "Architectural Digest editorial" has zero effect on model
    ✗ _COLOR_ACCENTS    — Conflicts with prompts master which already sets colors
    ✗ _TEXTURE_DETAILS  — Over-specification overwhelms the model
    ✗ _TIME_OF_DAY      — Redundant, already covered by _LIGHTING_MOODS

  KEPT (genuinely useful):
    ✓ _CAMERA_ANGLES    — Fresh perspective every pin
    ✓ _LIGHTING_MOODS   — Controls brightness & mood well
    ✓ _COMP_STYLES      — Gives composition variety
    ✓ _SEASONS_WEATHER  — Background context variety

  RESULT: Prompt stays ~350-450 chars (was bloating to 900).
          Model gets clear signal → sharper, cleaner, on-theme output.

RATIO SUPPORT:
  • 9:16 portrait → 1080x1920  (primary, Pinterest-native)
  • 1:1 square    → 1080x1080  (alternate, carousel-friendly)
"""

import asyncio
import base64
import logging
import random
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

# ── Negative prompt — always appended to block garbage outputs ─────────────────
_NEGATIVE_PROMPT = (
    "ugly, blurry, watermark, text overlay, logo, signature, "
    "cartoon, anime, illustration, drawing, painting, CGI plastic, "
    "overexposed, underexposed, low quality, jpeg artifacts, "
    "distorted, deformed, duplicate, cropped, frame, border, "
    "dark, moody, noir, desaturated, gloomy, depressing"
)

# ══════════════════════════════════════════════════════════════════════════════
# VARIETY ENGINE v4 — 4 focused pools only
# Prompts master already handles: subject, colors, props, style details
# These pools only add: angle, light, composition, season — nothing more
# ══════════════════════════════════════════════════════════════════════════════

_CAMERA_ANGLES = [
    "eye-level lifestyle shot",
    "slight high angle looking into room",
    "low angle emphasizing height of space",
    "straight-on symmetrical architectural shot",
    "three-quarter angle showing room depth",
    "diagonal foreground prop framing shot",
    "wide establishing interior shot",
    "intimate close-up detail and texture shot",
    "over-the-shoulder lifestyle perspective",
    "corner angle showing two walls for depth",
]

_LIGHTING_MOODS = [
    "bright soft morning window light",
    "warm golden hour afternoon sunlight streaming in",
    "diffused bright daylight, zero harsh shadows",
    "gentle dappled sunlight through sheer curtains",
    "crisp clean mid-morning bright light",
    "warm ambient with soft window fill",
    "bright airy spring daylight, high key",
    "soft side window light with gentle fill",
    "cheerful sunny afternoon interior light",
    "warm cozy lamp light complementing daylight",
]

_COMP_STYLES = [
    "rule of thirds with strong foreground prop",
    "perfect centered symmetry, interior architecture",
    "leading lines drawing eye through room depth",
    "layered depth: close props, mid furniture, background wall",
    "foreground bokeh flower or plant framing subject",
    "wide establishing room context shot",
    "tight detail crop isolating single beautiful prop",
    "s-curve natural flow composition",
    "framed within doorway or window arch",
    "negative space minimalism with single hero prop",
]

_SEASONS_WEATHER = [
    "lush bright spring, cherry blossoms visible through window",
    "warm golden summer, vibrant greenery outside",
    "fresh spring morning, soft green buds on trees",
    "bright clear summer day, blue sky outside",
    "warm late spring afternoon, flowers in full bloom",
    "sunny golden autumn, warm amber light",
    "fresh spring after rain, everything glistening green",
    "clear crisp summer blue-sky day",
    "warm mid-spring garden visible through window",
    "bright cheerful overcast spring diffused light",
]


def _pick_variety_modifiers() -> dict:
    """Pick one random modifier from each of the 4 focused pools."""
    return {
        "angle":    random.choice(_CAMERA_ANGLES),
        "lighting": random.choice(_LIGHTING_MOODS),
        "comp":     random.choice(_COMP_STYLES),
        "season":   random.choice(_SEASONS_WEATHER),
    }


def _inject_variety(base_prompt: str) -> tuple[str, dict]:
    """
    Inject 4 focused variety modifiers into the base prompts-master visual_prompt.
    Keeps total prompt lean (~350-450 chars) so the model stays on-theme.
    Returns (enriched_prompt, modifiers_used) — modifiers logged for debugging.
    """
    mods = _pick_variety_modifiers()

    variety_block = (
        f"{mods['angle']}, {mods['lighting']}, "
        f"{mods['comp']}, {mods['season']}"
    )

    quality_tail = "4K ultra HD, photorealistic, highly detailed, award-winning photography"

    # Strip existing quality tail if prompts master already added it, re-add cleanly
    base_clean = base_prompt.replace(quality_tail, "").rstrip(", ").strip()

    enriched = f"{base_clean}, {variety_block}, {quality_tail}"
    return enriched, mods


# ── Helpers ────────────────────────────────────────────────────────────────────

def _enrich_prompt(prompt: str, max_chars: int = 600) -> str:
    """Ensure quality tail present, then truncate. Variety already injected upstream."""
    base = prompt.strip()
    if "4K" not in base and "4k" not in base:
        base += ", 4K ultra HD, photorealistic, highly detailed, award-winning photography"
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
    enriched = _enrich_prompt(f"{prompt}, portrait orientation {w}x{h}")

    url = (
        f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
        f"/ai/run/{CLOUDFLARE_IMAGE_MODEL}"
    )

    headers = {
        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
        "Content-Type":  "application/json",
    }

    payload = {
        "prompt":          enriched,
        "negative_prompt": _NEGATIVE_PROMPT,
        "num_steps":       8,                          # max for Flux Schnell quality
        "seed":            random.randint(1, 2_147_483_647),  # fresh every call
        "width":           w,
        "height":          h,
    }

    async with httpx.AsyncClient(timeout=_CALL_TIMEOUT) as client:
        resp = await client.post(url, headers=headers, json=payload)
        resp.raise_for_status()

        if "application/json" in resp.headers.get("content-type", "").lower():
            data    = resp.json()
            b64_str = data.get("result", {}).get("image", "")
            if b64_str:
                return base64.b64decode(b64_str)
            logger.error(f"❌ [Cloudflare] No image in response: {str(data)[:200]}")
            return None
        else:
            return resp.content


async def _t2i_cloudflare(prompt: str, ratio: str) -> Optional[bytes]:
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(f"🎨 [Cloudflare] Attempt {attempt}/{_MAX_RETRIES} | ratio={ratio}")
            img = await _cloudflare_once(prompt, ratio)
            if _is_valid(img):
                logger.info(f"✅ [Cloudflare] {len(img):,} bytes on attempt {attempt}")
                return img
            logger.warning(f"⚠️ [Cloudflare] Attempt {attempt}: invalid/too small")
        except Exception as e:
            logger.warning(f"⚠️ [Cloudflare] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAY)

    logger.error("❌ [Cloudflare] All attempts failed — moving to Pollinations.")
    return None


# ── Model 2: Pollinations.ai (Fallback) ────────────────────────────────────────

async def _pollinations_once(prompt: str, ratio: str) -> Optional[bytes]:
    w, h     = _get_dims(ratio)
    enriched = _enrich_prompt(prompt, max_chars=500)
    seed     = random.randint(1, 999_999)
    encoded  = urllib.parse.quote(enriched)
    url      = (
        f"{_POLLINATIONS_BASE}/{encoded}"
        f"?width={w}&height={h}&nologo=true&enhance=true"
        f"&model={POLLINATIONS_MODEL}&quality=high&seed={seed}"
    )
    logger.info(f"🎨 [Pollinations] {w}x{h} | seed={seed} | ratio={ratio}")
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
            logger.warning(f"⚠️ [Pollinations] Attempt {attempt}: too small")
        except Exception as e:
            logger.warning(f"⚠️ [Pollinations] Attempt {attempt} error: {e}")

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(_RETRY_DELAY)

    logger.error("❌ [Pollinations] All attempts failed.")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

async def generate_pin_image(visual_prompt: str, ratio: str = "9:16") -> Optional[str]:
    """
    Generate a Pinterest image using the T2I pipeline.

    Flow:
      1. Inject 4 focused variety modifiers (angle, lighting, comp, season)
      2. Random seed every call for visual freshness
      3. Try Cloudflare (primary) → Pollinations (fallback)
      4. Upload result to ImgBB for permanent hosting

    Args:
        visual_prompt: The detailed visual prompt from prompts master
        ratio: "9:16" (Pinterest portrait) or "1:1" (square)

    Returns:
        ImgBB hosted URL or None if all models fail
    """
    w, h = _get_dims(ratio)
    logger.info(f"🎨 [Image Pipeline] PIN | ratio={ratio} ({w}x{h})")

    # Inject variety — 4 focused modifiers, lean prompt
    enriched_prompt, mods = _inject_variety(visual_prompt)
    logger.info(
        f"🎲 [Variety Engine v4] "
        f"angle={mods['angle'][:35]} | "
        f"light={mods['lighting'][:35]} | "
        f"comp={mods['comp'][:35]} | "
        f"season={mods['season'][:35]}"
    )
    logger.info(f"📝 [Prompt] {len(enriched_prompt)} chars: {enriched_prompt[:120]}...")

    # PRIMARY: Cloudflare
    image_bytes = await _t2i_cloudflare(enriched_prompt, ratio)

    # FALLBACK: Pollinations
    if not image_bytes:
        logger.info("🔄 [Image Pipeline] Cloudflare exhausted — trying Pollinations...")
        image_bytes = await _t2i_pollinations(enriched_prompt, ratio)

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
