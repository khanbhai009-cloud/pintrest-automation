"""
tools/image_creator.py — Dual-Layer T2I Image Pipeline  [VARIETY ENGINE v2]

MODELS (in order):
  1. Cloudflare   — @cf/black-forest-labs/flux-1-schnell (Primary, Fast & High Quality)
  2. Pollinations — free, URL-based, 4K quality (Fallback)

VARIETY ENGINE:
  • Random seed injected every call → different output from same prompt
  • Rotation pools: camera angle, lighting mood, time of day, color temperature,
    season/weather, compositional style — auto-injected into every prompt
  • Negative prompt suffix blocks: blur, text, watermark, plastic, fake, overexposed
  • Result: same visual style, completely fresh image every single pin

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
    "distorted, deformed, duplicate, cropped, frame, border"
)

# ══════════════════════════════════════════════════════════════════════════════
# VARIETY ENGINE — Rotation pools for infinite visual freshness
# Each pin call randomly picks one from each pool and injects into prompt
# ══════════════════════════════════════════════════════════════════════════════

_CAMERA_ANGLES = [
    "eye-level shot",
    "low angle looking up",
    "high angle bird's eye overview",
    "dutch angle tilt",
    "straight-on symmetrical shot",
    "diagonal foreground frame",
    "over-the-shoulder perspective",
    "wide establishing shot",
    "intimate close-up detail shot",
    "three-quarter angle",
]

_LIGHTING_MOODS = [
    "soft diffused morning light",
    "dramatic golden hour backlight",
    "moody overcast grey diffused light",
    "warm candlelight and fairy lights only",
    "cool blue-toned twilight ambient light",
    "harsh midday sun with deep shadows",
    "window light with dramatic shadow patterns",
    "neon glow accent lighting in dark room",
    "misty fog-filtered soft light",
    "stormy dramatic sidelight",
]

_TIME_OF_DAY = [
    "early morning fog, 6AM",
    "golden hour sunrise, 7AM",
    "bright mid-morning, 10AM",
    "warm afternoon, 3PM",
    "magic hour sunset, 6PM",
    "blue hour dusk, 7PM",
    "dark evening, 9PM with interior lights",
    "deep night, artificial light only",
    "overcast midday, flat diffused",
    "stormy afternoon with rain",
]

_COLOR_TEMPERATURE = [
    "ultra-warm 2400K amber glow",
    "warm 3200K tungsten tones",
    "neutral 4000K balanced light",
    "cool 6500K daylight white",
    "teal-orange cinematic split-tone",
    "desaturated moody film-grade",
    "warm sepia-tinted vintage grade",
    "cool blue-steel night grade",
    "vibrant high-saturation pop grade",
    "muted earth-tone low saturation",
]

_SEASONS_WEATHER = [
    "lush spring green, cherry blossoms visible",
    "hot dry summer, golden light",
    "autumn fall, orange and red leaves",
    "winter frost, bare branches, snow trace",
    "heavy rain, wet surfaces reflecting light",
    "fresh after-rain, everything glistening",
    "misty foggy morning",
    "clear crisp blue-sky day",
    "dramatic stormy clouds",
    "soft overcast, diffused neutral light",
]

_COMP_STYLES = [
    "rule of thirds composition",
    "perfect centered symmetry",
    "leading lines drawing eye to subject",
    "foreground bokeh framing subject",
    "negative space minimalist composition",
    "layered depth: foreground, midground, background",
    "tight crop isolating single detail",
    "wide establishing context shot",
    "s-curve natural flow composition",
    "framed within architectural element",
]

_CAMERA_LENSES = [
    "Canon 35mm f/1.4 L lens, shallow depth of field",
    "Sony 85mm f/1.8 portrait lens, creamy bokeh",
    "Nikon 50mm f/1.2 standard lens",
    "Canon 24mm f/2.8 wide angle",
    "Hasselblad medium format, extreme detail",
    "Leica M11 35mm Summilux, film character",
    "Sony A7R V 16mm ultra-wide, expansive",
    "Canon TS-E 24mm tilt-shift, selective focus plane",
    "DJI aerial drone shot, overhead perspective",
    "Fujifilm GFX100 medium format, rich tones",
]

_EDITORIAL_STYLE = [
    "Architectural Digest editorial style",
    "Kinfolk magazine lifestyle aesthetic",
    "Vogue Living interior spread",
    "Dwell magazine modern architecture",
    "Elle Decor maximalist editorial",
    "VSCO film photography aesthetic",
    "Monocle magazine travel editorial",
    "Dezeen architectural photography",
    "Pinterest viral save-worthy aesthetic",
    "Instagram editorial flat lay",
]


def _pick_variety_modifiers() -> dict:
    """Pick one random modifier from each pool. Called fresh every pin generation."""
    return {
        "angle":       random.choice(_CAMERA_ANGLES),
        "lighting":    random.choice(_LIGHTING_MOODS),
        "time":        random.choice(_TIME_OF_DAY),
        "color_grade": random.choice(_COLOR_TEMPERATURE),
        "season":      random.choice(_SEASONS_WEATHER),
        "comp":        random.choice(_COMP_STYLES),
        "lens":        random.choice(_CAMERA_LENSES),
        "editorial":   random.choice(_EDITORIAL_STYLE),
    }


def _inject_variety(base_prompt: str) -> tuple[str, dict]:
    """
    Inject random variety modifiers into the base CMO visual_prompt.
    Returns (enriched_prompt, modifiers_used) — modifiers logged for debugging.
    """
    mods = _pick_variety_modifiers()

    variety_block = (
        f"{mods['angle']}, {mods['lighting']}, {mods['time']}, "
        f"{mods['color_grade']}, {mods['season']}, {mods['comp']}, "
        f"{mods['lens']}, {mods['editorial']}"
    )

    # Insert variety before the quality tail (which is always at the end)
    # Strip existing quality tail if present, re-add cleanly at the end
    quality_tail = "4K ultra HD, photorealistic, highly detailed, award-winning photography"
    base_clean   = base_prompt.replace(quality_tail, "").rstrip(", ").strip()

    enriched = f"{base_clean}, {variety_block}, {quality_tail}"
    return enriched, mods


# ── Helpers ────────────────────────────────────────────────────────────────────

def _enrich_prompt(prompt: str, max_chars: int = 900) -> str:
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
    # Log me bhi update kar diya ki ye temporary upload hai
    logger.info(f"⬆️  [ImgBB] Uploading {len(image_bytes):,} bytes (Temp: 30 mins)...")
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.imgbb.com/1/upload",
                data={
                    "key": IMGBB_API_KEY, 
                    "image": encoded,
                    "expiration": 1800  # 1800 seconds = 30 minutes me auto-delete
                },
            )
            resp.raise_for_status()
            url = resp.json()["data"]["url"]
        logger.info(f"✅ [ImgBB] Hosted temporarily: {url}")
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
        "negative_prompt": _NEGATIVE_PROMPT,   # blocks garbage outputs
        "num_steps":       8,                   # max for Flux Schnell quality
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
    enriched = _enrich_prompt(prompt, max_chars=600)
    seed     = random.randint(1, 999_999)       # random seed for variety
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
    Generate a VIRAL_PIN image using the T2I pipeline.
    - Injects random variety modifiers (angle, lighting, color grade, etc.)
    - Uses random seed on every call for visual freshness
    - Blocks garbage outputs via negative prompt
    - Uploads result to ImgBB for permanent hosting
    Returns: ImgBB URL or None
    """
    w, h = _get_dims(ratio)
    logger.info(f"🎨 [Image Pipeline] VIRAL_PIN | ratio={ratio} ({w}x{h})")

    # Inject variety — fresh modifiers every single call
    enriched_prompt, mods = _inject_variety(visual_prompt)
    logger.info(
        f"🎲 [Variety Engine] "
        f"angle={mods['angle'][:30]} | "
        f"light={mods['lighting'][:30]} | "
        f"grade={mods['color_grade'][:25]} | "
        f"lens={mods['lens'][:30]}"
    )

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
