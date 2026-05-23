"""
mastermind/node_product_researcher.py — Node 5: Product Researcher

4-Model Vision Fallback Chain (10s wait between each, once per model):
  1st → Gemini Key 1   (GEMINI_API_KEY)    — gemini-2.5-flash  [vision]
  2nd → Gemini Key 2   (GEMINI_API_KEY_2)  — gemini-2.5-flash  [vision]
  3rd → Groq           (GROQ_API_KEY)      — llama-4-scout      [vision]
  4th → Cerebras       (CEREBRAS_API_KEY)  — qwen-3-235b        [text-only fallback]

State input:  should_create_blog, last_posted_image_url, cmo_strategy, cycle_trigger
State output: blog_products (list of dicts with insert_after_para)
"""

import asyncio
import base64
import json
import logging
import re
from typing import Optional

import httpx

from config import (
    GEMINI_API_KEY, GEMINI_API_KEY_2,
    GROQ_API_KEY, GROQ_VISION_MODEL,
    CEREBRAS_API_KEY, CEREBRAS_VISION_MODEL,
    VISION_RETRY_DELAY,
)

logger = logging.getLogger(__name__)

_VISION_SYSTEM = (
    "You are a product identification expert. "
    "Analyse the image and identify 4-5 physical products that are visible or implied. "
    "Respond ONLY with a valid JSON array — no markdown, no explanation."
)

_VISION_PROMPT = """Look at this aesthetic Pinterest image carefully.

Identify 4–5 physical products a viewer would want to buy after seeing this image.
Each product should be something actually available on Amazon.

Return ONLY a raw JSON array (no markdown):
[
  {{
    "product_name": "descriptive product name for Amazon search",
    "search_keyword": "short 2-4 word Amazon search term",
    "price_range": "$15-40",
    "why_fits": "one sentence why this fits the aesthetic",
    "suggested_para": 2
  }},
  ...
]

suggested_para should be spread across 1–8 (which paragraph to insert product after).
Keep product_name specific but searchable (e.g. "LED strip lights warm white", not "lights").
"""

_TEXT_FALLBACK_PROMPT = """{system}

You cannot see the image, but based on the style/niche below, identify 4-5 products
a typical buyer would want after seeing an aesthetic Pinterest pin about this topic.

Style : {style}
Niche : {niche}
Tags  : {tags}

Return ONLY a raw JSON array (no markdown):
[
  {{
    "product_name": "descriptive product name for Amazon search",
    "search_keyword": "short 2-4 word Amazon search term",
    "price_range": "$15-40",
    "why_fits": "one sentence why this fits the aesthetic",
    "suggested_para": 2
  }},
  ...
]"""


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _download_image_b64(url: str) -> Optional[str]:
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        logger.error(f"❌ [ProductResearcher] Image download failed: {e}")
        return None


def _parse_json(raw: str) -> list:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("[")
    end   = cleaned.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    return json.loads(cleaned[start:end])


# ── 4-Model Vision Fallback Chain ─────────────────────────────────────────────

async def _try_gemini(api_key: str, image_b64: str, key_label: str) -> list:
    """Gemini vision call (Key 1 or Key 2)."""
    if not api_key:
        raise RuntimeError(f"Gemini {key_label} not configured")

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)

    def _sync():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(text=_VISION_PROMPT),
                        genai_types.Part(
                            inline_data=genai_types.Blob(
                                mime_type="image/jpeg",
                                data=image_b64,
                            )
                        ),
                    ],
                )
            ],
            config=genai_types.GenerateContentConfig(
                system_instruction=_VISION_SYSTEM,
                temperature=0.2,
                max_output_tokens=800,
            ),
        )

    response = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=60)
    return _parse_json(response.text)


async def _try_groq_vision(image_b64: str) -> list:
    """Groq vision call — llama-4-scout with base64 image."""
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not configured")

    from groq import Groq

    def _sync():
        client = Groq(api_key=GROQ_API_KEY)
        return client.chat.completions.create(
            model=GROQ_VISION_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text",      "text": _VISION_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{image_b64}"
                    }},
                ],
            }],
            max_tokens=800,
        )

    response = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=60)
    return _parse_json(response.choices[0].message.content)


async def _try_cerebras_text(style: str, niche: str, tags: list) -> list:
    """Cerebras text-only fallback — no image, uses niche/style context."""
    if not CEREBRAS_API_KEY:
        raise RuntimeError("CEREBRAS_API_KEY not configured")

    from openai import OpenAI

    prompt = _TEXT_FALLBACK_PROMPT.format(
        system=_VISION_SYSTEM,
        style=style or "aesthetic lifestyle",
        niche=niche or "home",
        tags=", ".join(tags[:6]) if tags else "home, aesthetic",
    )

    def _sync():
        client = OpenAI(
            api_key=CEREBRAS_API_KEY,
            base_url="https://api.cerebras.ai/v1",
        )
        return client.chat.completions.create(
            model=CEREBRAS_VISION_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
        )

    response = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=60)
    return _parse_json(response.choices[0].message.content)


async def _identify_products_with_fallback(
    image_b64: str,
    style: str = "",
    niche: str = "home",
    tags: list = None,
) -> list:
    """
    4-model fallback chain — 10s wait between each attempt.
    Returns product list (may be empty if all 4 fail).
    """
    tags = tags or []

    attempts = [
        ("Gemini Key 1",  lambda: _try_gemini(GEMINI_API_KEY,   image_b64, "Key 1")),
        ("Gemini Key 2",  lambda: _try_gemini(GEMINI_API_KEY_2,  image_b64, "Key 2")),
        ("Groq Vision",   lambda: _try_groq_vision(image_b64)),
        ("Cerebras Text", lambda: _try_cerebras_text(style, niche, tags)),
    ]

    for label, fn in attempts:
        try:
            logger.info(f"👁️ [Vision] Trying {label}...")
            result = await fn()
            if result:
                logger.info(f"✅ [Vision] {label} succeeded — {len(result)} products")
                return result
            logger.warning(f"⚠️ [Vision] {label} returned empty list")
        except Exception as e:
            logger.warning(f"⚠️ [Vision] {label} failed: {str(e)[:120]}")

        logger.info(f"⏳ [Vision] Waiting {VISION_RETRY_DELAY}s before next model...")
        await asyncio.sleep(VISION_RETRY_DELAY)

    logger.error("❌ [Vision] All 4 models failed — returning empty product list")
    return []


# ── Node ──────────────────────────────────────────────────────────────────────

async def node_product_researcher(state: dict) -> dict:
    """
    Node 5 — Product Researcher.
    Skips if should_create_blog is False.
    Uses 4-model vision fallback chain → fetches Amazon products.
    """
    if not state.get("should_create_blog"):
        logger.info("🛍️ [ProductResearcher] Skipping — should_create_blog=False")
        return {**state, "blog_products": []}

    image_url = state.get("last_posted_image_url", "")
    if not image_url:
        logger.warning("🛍️ [ProductResearcher] No image URL — returning empty products")
        return {**state, "blog_products": []}

    # ── Pull style/niche for Cerebras text fallback ───────────────────────────
    trigger = state.get("cycle_trigger", "")
    if "account2" in trigger and "account1" not in trigger:
        strategy = state.get("a2_cmo_strategy", {})
        niche    = "tech"
    else:
        strategy = state.get("a1_cmo_strategy", {})
        niche    = "home"

    style = strategy.get("style_name", strategy.get("vibe", "aesthetic"))
    tags  = list(strategy.get("tags", []))

    # ── Step 1: Download image ────────────────────────────────────────────────
    image_b64 = await _download_image_b64(image_url)
    if not image_b64:
        return {**state, "blog_products": []}

    # ── Step 2: Vision AI (4-model fallback) identifies products ─────────────
    identified = await _identify_products_with_fallback(
        image_b64=image_b64,
        style=style,
        niche=niche,
        tags=tags,
    )

    if not identified:
        return {**state, "blog_products": []}

    # ── Step 3: Fetch real Amazon products ────────────────────────────────────
    from tools.aliexpress import search_products
    from tools.admitad import make_affiliate_link

    blog_products = []
    for item in identified[:5]:
        if len(blog_products) >= 4:
            break
        keyword = item.get("search_keyword", item.get("product_name", ""))
        try:
            results = await search_products(keyword=keyword, max_results=1, niche=niche)
            if not results:
                continue
            product = results[0]
            affiliate_url = make_affiliate_link(
                product.get("affiliate_link") or product.get("product_url", "")
            )
            blog_products.append({
                "name":              product.get("product_name", item["product_name"]),
                "price":             product.get("sale_price", item.get("price_range", "")),
                "affiliate_url":     affiliate_url,
                "insert_after_para": int(item.get("suggested_para", len(blog_products) * 2 + 1)),
                "why_fits":          item.get("why_fits", ""),
            })
        except Exception as e:
            logger.warning(f"⚠️ [ProductResearcher] Product lookup failed for '{keyword}': {e}")
            continue

    logger.info(f"🛍️ Products researched: {len(blog_products)} found")
    return {**state, "blog_products": blog_products}
