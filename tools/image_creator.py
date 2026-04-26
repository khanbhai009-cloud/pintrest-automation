"""
tools/image_creator.py — Dual-Layer T2I Image Pipeline  [VARIETY ENGINE v3 — BRIGHT AESTHETIC]

MODELS (in order):
  1. Cloudflare   — @cf/black-forest-labs/flux-1-schnell (Primary, Fast & High Quality)
  2. Pollinations — free, URL-based, 4K quality (Fallback)

VARIETY ENGINE:
  • Random seed injected every call → different output from same prompt
  • Rotation pools: camera angle, lighting mood, time of day, color temperature,
    season/weather, compositional style — auto-injected into every prompt
  • Home-decor optimized pools: bright, warm, colorful, cheerful — not moody/dark
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
    "distorted, deformed, duplicate, cropped, frame, border, "
    "dark, moody, noir, desaturated, gloomy, depressing"
)

# ══════════════════════════════════════════════════════════════════════════════
# VARIETY ENGINE — Rotation pools for infinite visual freshness
# Tuned for BRIGHT, COLORFUL, WARM home decor Pinterest aesthetic
# Each pin call randomly picks one from each pool and injects into prompt
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
    "warm 3200K ambient with soft window fill",
    "bright airy spring daylight, high key",
    "soft side window light with gentle fill",
    "cheerful sunny afternoon interior light",
    "warm cozy lamp light complementing daylight",
]

_TIME_OF_DAY = [
    "bright morning, 9AM fresh light",
    "mid-morning golden light, 10AM",
    "cheerful bright noon, 12PM",
    "warm afternoon sun, 2PM",
    "golden late afternoon, 4PM",
    "soft warm early evening, 6PM with lamps on",
    "cozy early morning, 7AM soft glow",
    "bright spring mid-morning, 11AM",
    "warm sunny mid-afternoon, 3PM",
    "fresh bright overcast soft-light morning",
]

_COLOR_TEMPERATURE = [
    "warm 3200K golden amber glow",
    "balanced warm 3800K natural light",
    "fresh 4500K clean daylight",
    "bright 5500K daylight white, airy",
    "warm-cool 4000K neutral balanced",
    "golden 3400K cozy warm tones",
    "crisp 6000K cool daylight, vibrant",
    "warm 3600K afternoon golden light",
    "soft 4200K natural window fill",
    "bright 5000K spring fresh daylight",
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

_CAMERA_LENSES = [
    "Canon 35mm f/1.4 L lens, shallow depth of field, creamy bokeh",
    "Sony 85mm f/1.8 portrait lens, smooth background separation",
    "Canon 24mm f/2.8 wide angle, expansive interior view",
    "Nikon 50mm f/1.2, balanced perspective, soft bokeh",
    "Sony A7R V 16mm ultra-wide, full room perspective",
    "Fujifilm GFX100 medium format, incredibly rich tones",
    "Canon TS-E 24mm tilt-shift, selective focus plane, no distortion",
    "Sony 35mm f/1.8 compact prime, intimate lifestyle shot",
    "Canon EOS R5 50mm f/1.8, clean natural perspective",
    "Leica M11 28mm, film-like character, natural proportions",
]

_EDITORIAL_STYLE = [
    "Architectural Digest bright spring editorial",
    "Kinfolk magazine warm lifestyle aesthetic",
    "House Beautiful cheerful interior spread",
    "Better Homes and Gardens colorful lifestyle",
    "Pinterest viral save-worthy home aesthetic",
    "Domino Magazine colorful modern interior",
    "Elle Decor bright maximalist editorial",
    "Real Simple magazine clean warm lifestyle",
    "Apartment Therapy bright small-space editorial",
    "Southern Living cheerful cottage editorial",
]

# ══════════════════════════════════════════════════════════════════════════════
# COLOR ACCENT POOLS — Injects fresh color energy per pin
# ══════════════════════════════════════════════════════════════════════════════
_COLOR_ACCENTS = [
    "pops of mustard yellow and terracotta",
    "soft sage green and cream palette",
    "blush pink and mint green pastels",
    "warm honey yellow and white tones",
    "sage green and copper accent palette",
    "dusty pink and natural wood tones",
    "mint green and white fresh palette",
    "warm peach and cream botanical palette",
    "yellow and white cheerful palette",
    "blush and sage boho palette",
]

_TEXTURE_DETAILS = [
    "rattan weave, matte ceramic, rough linen textures",
    "smooth painted plaster, polished brass, ribbed ceramic",
    "natural jute, weathered oak wood grain, cotton knit",
    "glazed ceramic tile, worn terracotta, sheer muslin",
    "soft velvet upholstery, brushed copper, smooth marble",
    "cable-knit throw, rough stone, burnished wood",
    "crisp cotton bed linen, smooth plaster, wicker weave",
    "matte finish walls, polished concrete, soft bouclé",
    "lacquered wood, ribbed glass, hand-thrown ceramic",
    "natural linen drape, hammered brass, smooth tile",
]


def _pick_variety_modifiers() -> dict:
    """Pick one random modifier from each pool. Called fresh every pin generation."""
    return {
        "angle":        random.choice(_CAMERA_ANGLES),
        "lighting":     random.choice(_LIGHTING_MOODS),
        "time":         random.choice(_TIME_OF_DAY),
        "color_grade":  random.choice(_COLOR_TEMPERATURE),
        "season":       random.choice(_SEASONS_WEATHER),
        "comp":         random.choice(_COMP_STYLES),
        "lens":         random.choice(_CAMERA_LENSES),
        "editorial":    random.choice(_EDITORIAL_STYLE),
        "color_accent": random.choice(_COLOR_ACCENTS),
        "texture":      random.choice(_TEXTURE_DETAILS),
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
        f"{mods['lens']}, {mods['editorial']}, "
        f"{mods['color_accent']}, {mods['texture']}"
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
    - Injects random variety modifiers (angle, lighting, color grade, texture, etc.)
    - Uses random seed on every call for visual freshness
    - Blocks garbage outputs via negative prompt (including dark/moody)
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
        f"accent={mods['color_accent'][:30]} | "
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
