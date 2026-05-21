"""
pipeline/product_extractor.py — Generated Image se Physical Products Extract karo

NOTE: Ye Vision FEEDER se ALAG hai.
  - Vision Feeder (tools/visions_ai.py) → Image ka aesthetic DNA extract karta hai (style, prompt, etc.)
  - Product Extractor (ye file)          → Image me dikhne wale PURCHASABLE products ki list extract karta hai
                                           (e.g., "wall clock", "throw pillow", "desk lamp", "flower vase")

AI CHAIN:
  Primary:  Gemini 2.5 Flash  (GEMINI_API_KEY)
  Fallback: Gemini Flash Lite (GEMINI_API_KEY_2)
  Last:     Groq llama-4-scout vision model

RATE LIMITING: 429 → 30s sleep → retry → switch model
"""

import base64
import io
import json
import logging
import time
from typing import List, Optional
import httpx

logger = logging.getLogger(__name__)

# ── Max retries per model ──────────────────────────────────────────────────
_MAX_RETRIES = 3
_RETRY_SLEEP = 30   # seconds on 429

# ── Groq vision model ──────────────────────────────────────────────────────
_GROQ_VISION_MODEL = "meta-llama/llama-4-scout-17b-16e-instruct"


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT
# ══════════════════════════════════════════════════════════════════════════════

_EXTRACTION_PROMPT = """You are an expert product identification AI specializing in e-commerce.

Analyze this image and identify ALL physical, purchasable products you can see.

EXTRACT:
- Every distinct product category visible (even if partially shown)
- Include: furniture, decor, electronics, clothing, plants, kitchen items, accessories, clocks, 
  wall art, lamps, rugs, pillows, bedding, books, stationery, gadgets, bags, organizers, etc.
- Be SPECIFIC: "geometric wall clock" not just "clock", "woven throw blanket" not just "blanket"
- Only real, purchasable products — NOT abstract concepts, colors, lighting, or architectural elements

OUTPUT FORMAT (strict JSON array, no extra text):
{
  "products": [
    {"name": "geometric wall clock", "category": "home decor", "confidence": "high"},
    {"name": "woven throw pillow", "category": "bedding", "confidence": "high"},
    {"name": "indoor potted plant", "category": "garden", "confidence": "medium"}
  ]
}

Include products with confidence "high" or "medium" only. 
Max 10 products per image. If no products found, return {"products": []}.
"""


# ══════════════════════════════════════════════════════════════════════════════
# IMAGE LOADER
# ══════════════════════════════════════════════════════════════════════════════

def _load_image_bytes(image_source: str) -> Optional[bytes]:
    """
    Local path ya URL se image bytes load karo.
    """
    if image_source.startswith("http://") or image_source.startswith("https://"):
        try:
            resp = httpx.get(image_source, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            return resp.content
        except Exception as e:
            logger.error(f"❌ [ProductExtractor] Image download failed: {e}")
            return None
    else:
        try:
            with open(image_source, "rb") as f:
                return f.read()
        except Exception as e:
            logger.error(f"❌ [ProductExtractor] File read failed: {e}")
            return None


def _detect_mime(image_bytes: bytes) -> str:
    if image_bytes[:4] == b'\x89PNG':
        return "image/png"
    if image_bytes[:3] == b'\xff\xd8\xff':
        return "image/jpeg"
    if image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"


# ══════════════════════════════════════════════════════════════════════════════
# GEMINI CALLER
# ══════════════════════════════════════════════════════════════════════════════

def _call_gemini(api_key: str, model: str, image_bytes: bytes, mime: str) -> Optional[str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model    = model,
                contents = [
                    types.Part.from_bytes(data=image_bytes, mime_type=mime),
                    _EXTRACTION_PROMPT,
                ],
                config = types.GenerateContentConfig(temperature=0.1),
            )
            text = resp.text.strip()
            if text:
                return text
        except Exception as e:
            err = str(e)
            logger.warning(f"⚠️ [ProductExtractor] Gemini [{model}] attempt {attempt}: {err[:80]}")
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                logger.info(f"⏳ Rate limit hit — sleeping {_RETRY_SLEEP}s...")
                time.sleep(_RETRY_SLEEP)
            elif attempt < _MAX_RETRIES:
                time.sleep(5)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# GROQ VISION CALLER
# ══════════════════════════════════════════════════════════════════════════════

def _call_groq_vision(image_bytes: bytes, mime: str) -> Optional[str]:
    from config import GROQ_API_KEY
    if not GROQ_API_KEY:
        return None

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime};base64,{b64}"

    payload = {
        "model": _GROQ_VISION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": data_url}},
                {"type": "text",      "text": _EXTRACTION_PROMPT},
            ]
        }],
        "temperature": 0.1,
    }

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            text = resp.json()["choices"][0]["message"]["content"].strip()
            if text:
                return text
        except Exception as e:
            err = str(e)
            logger.warning(f"⚠️ [ProductExtractor] Groq attempt {attempt}: {err[:80]}")
            if "429" in err:
                logger.info(f"⏳ Groq rate limit — sleeping {_RETRY_SLEEP}s...")
                time.sleep(_RETRY_SLEEP)
            elif attempt < _MAX_RETRIES:
                time.sleep(5)

    return None


# ══════════════════════════════════════════════════════════════════════════════
# JSON PARSER
# ══════════════════════════════════════════════════════════════════════════════

def _parse_products(raw: str) -> List[dict]:
    try:
        cleaned = raw.strip()
        if "```" in cleaned:
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        data = json.loads(cleaned.strip())
        return data.get("products", [])
    except Exception:
        try:
            start = raw.index("{")
            end   = raw.rindex("}") + 1
            data  = json.loads(raw[start:end])
            return data.get("products", [])
        except Exception:
            return []


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def extract_products_from_image(image_source: str) -> List[dict]:
    """
    Image se purchasable products extract karo.

    Args:
        image_source : Local file path ya public image URL

    Returns:
        List of product dicts:
        [
            {"name": "geometric wall clock", "category": "home decor", "confidence": "high"},
            ...
        ]
        Empty list on failure.
    """
    from config import GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_CMO_MODEL, GEMINI_CHAT_MODEL

    logger.info(f"🔍 [ProductExtractor] Analyzing: {image_source[:60]}")

    # Load image
    image_bytes = _load_image_bytes(image_source)
    if not image_bytes:
        logger.error("❌ [ProductExtractor] Could not load image.")
        return []

    mime = _detect_mime(image_bytes)
    raw  = None

    # ── Gemini Primary ──────────────────────────────────────────────────────
    if GEMINI_API_KEY:
        logger.info("🧠 [ProductExtractor] Trying Gemini primary...")
        raw = _call_gemini(GEMINI_API_KEY, GEMINI_CMO_MODEL, image_bytes, mime)

    # ── Gemini Fallback ─────────────────────────────────────────────────────
    if not raw and GEMINI_API_KEY_2:
        logger.info("🔄 [ProductExtractor] Gemini primary failed → fallback...")
        raw = _call_gemini(GEMINI_API_KEY_2, GEMINI_CHAT_MODEL, image_bytes, mime)

    # ── Groq Vision Last Resort ─────────────────────────────────────────────
    if not raw:
        logger.info("🔄 [ProductExtractor] Gemini exhausted → Groq vision...")
        raw = _call_groq_vision(image_bytes, mime)

    if not raw:
        logger.error("❌ [ProductExtractor] All models failed.")
        return []

    products = _parse_products(raw)
    logger.info(f"✅ [ProductExtractor] {len(products)} products found: {[p['name'] for p in products[:5]]}")
    return products
