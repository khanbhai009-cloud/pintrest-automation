"""
mastermind/node_product_researcher.py — Node 5: Product Researcher

Uses Gemini Vision to identify products from the posted Pinterest image,
then fetches real Amazon products for each one via tools/aliexpress.py.

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

from config import GEMINI_API_KEY

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


async def _download_image_b64(url: str) -> Optional[str]:
    """Download image from URL and return base64-encoded string."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return base64.b64encode(resp.content).decode("utf-8")
    except Exception as e:
        logger.error(f"❌ [ProductResearcher] Image download failed: {e}")
        return None


def _parse_gemini_json(raw: str) -> list:
    """Strip markdown fences and parse JSON array from Gemini response."""
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("[")
    end   = cleaned.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    return json.loads(cleaned[start:end])


async def _identify_products_from_image(image_b64: str) -> list:
    """Call Gemini Vision to identify products in the image."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY not configured.")

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=GEMINI_API_KEY)

    def _sync_call():
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

    response = await asyncio.wait_for(
        asyncio.to_thread(_sync_call),
        timeout=60,
    )
    return _parse_gemini_json(response.text)


async def node_product_researcher(state: dict) -> dict:
    """
    Node 5 — Product Researcher.
    Skips if should_create_blog is False.
    Uses Gemini Vision → finds products → fetches Amazon results.
    """
    if not state.get("should_create_blog"):
        logger.info("🛍️ [ProductResearcher] Skipping — should_create_blog=False")
        return {**state, "blog_products": []}

    image_url = state.get("last_posted_image_url", "")
    if not image_url:
        logger.warning("🛍️ [ProductResearcher] No image URL — returning empty products")
        return {**state, "blog_products": []}

    # ── Step 1: Download image ────────────────────────────────────────────────
    image_b64 = await _download_image_b64(image_url)
    if not image_b64:
        return {**state, "blog_products": []}

    # ── Step 2: Gemini Vision identifies products ─────────────────────────────
    try:
        identified = await _identify_products_from_image(image_b64)
        logger.info(f"🔍 [ProductResearcher] Gemini identified {len(identified)} products")
    except Exception as e:
        logger.error(f"❌ [ProductResearcher] Vision failed: {e}")
        return {**state, "blog_products": []}

    if not identified:
        return {**state, "blog_products": []}

    # ── Step 3: Fetch real Amazon products ────────────────────────────────────
    from tools.aliexpress import search_products
    from tools.admitad import make_affiliate_link

    trigger = state.get("cycle_trigger", "")
    niche   = "tech" if ("account2" in trigger and "account1" not in trigger) else "home"

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
                "name":             product.get("product_name", item["product_name"]),
                "price":            product.get("sale_price", item.get("price_range", "")),
                "affiliate_url":    affiliate_url,
                "insert_after_para": int(item.get("suggested_para", len(blog_products) * 2 + 1)),
                "why_fits":         item.get("why_fits", ""),
            })
        except Exception as e:
            logger.warning(f"⚠️ [ProductResearcher] Product lookup failed for '{keyword}': {e}")
            continue

    logger.info(f"🛍️ Products researched: {len(blog_products)} found")
    return {**state, "blog_products": blog_products}
