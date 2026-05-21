"""
pipeline/amazon_fetcher.py — Extracted Products → Amazon Search → Similarity Check → Affiliate Links

FLOW PER PRODUCT:
  1. Product name se Amazon search karo (RapidAPI — same as tools/aliexpress.py)
  2. LLM se verify karo ki result actually similar hai ya nahi
     (clock dhundha toh clock milna chahiye, plate nahi)
  3. Verified products pe affiliate tag lagao (tools/admitad.py)
  4. Final JSON list return karo

RATE LIMITING:
  - RapidAPI: 2s delay between calls
  - Verification LLM: Groq (fast, free tier friendly)
  - 429 → 30s sleep → retry
"""

import asyncio
import json
import logging
import time
from typing import List, Optional
import httpx

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────
_RAPIDAPI_HOST = "realtime-amazon-data.p.rapidapi.com"
_SEARCH_URL    = "https://realtime-amazon-data.p.rapidapi.com/product-search"
_DETAILS_URL   = "https://realtime-amazon-data.p.rapidapi.com/product-details"
_CALL_DELAY    = 2.0    # seconds between RapidAPI calls
_MAX_RETRIES   = 3
_RETRY_SLEEP   = 30


# ══════════════════════════════════════════════════════════════════════════════
# AMAZON SEARCH
# ══════════════════════════════════════════════════════════════════════════════

async def _search_amazon(keyword: str, max_results: int = 5) -> List[dict]:
    from config import RAPIDAPI_KEY
    if not RAPIDAPI_KEY:
        logger.warning("⚠️ [AmazonFetcher] RAPIDAPI_KEY not set — skipping search.")
        return []

    headers = {
        "x-rapidapi-host": _RAPIDAPI_HOST,
        "x-rapidapi-key":  RAPIDAPI_KEY,
    }
    params = {"keyword": keyword, "country": "us"}

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.get(_SEARCH_URL, headers=headers, params=params)

            if r.status_code == 429:
                logger.info(f"⏳ [AmazonFetcher] RapidAPI 429 — sleeping {_RETRY_SLEEP}s...")
                await asyncio.sleep(_RETRY_SLEEP)
                continue

            r.raise_for_status()
            data     = r.json().get("data", {})
            products = data.get("products", []) if isinstance(data, dict) else []
            if isinstance(products, list):
                logger.info(f"✅ [AmazonFetcher] '{keyword[:40]}' → {len(products)} results")
                return products[:max_results]
        except Exception as e:
            logger.warning(f"⚠️ [AmazonFetcher] Search attempt {attempt}: {e}")
            if attempt < _MAX_RETRIES:
                await asyncio.sleep(5)

    return []


async def _get_product_details(asin: str) -> dict:
    from config import RAPIDAPI_KEY
    if not RAPIDAPI_KEY:
        return {}
    headers = {
        "x-rapidapi-host": _RAPIDAPI_HOST,
        "x-rapidapi-key":  RAPIDAPI_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(_DETAILS_URL, headers=headers,
                                 params={"asin": asin, "country": "us"})
            return r.json().get("data", {})
    except Exception as e:
        logger.warning(f"⚠️ [AmazonFetcher] Details fetch failed for {asin}: {e}")
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# SIMILARITY VERIFIER (LLM)
# ══════════════════════════════════════════════════════════════════════════════

def _verify_similarity(extracted_product: str, amazon_title: str) -> bool:
    """
    LLM se check karo ki Amazon product wahi hai jo image me tha.
    Groq use karta hai (fast + free tier friendly).
    """
    from config import GROQ_API_KEY, GROQ_MODEL
    from groq import Groq

    if not GROQ_API_KEY:
        # Without LLM, do simple word overlap check
        extracted_words = set(extracted_product.lower().split())
        amazon_words    = set(amazon_title.lower().split())
        overlap         = extracted_words & amazon_words
        return len(overlap) >= 1

    prompt = f"""You are a product similarity checker.

EXTRACTED FROM IMAGE: "{extracted_product}"
AMAZON PRODUCT TITLE: "{amazon_title}"

Are these the SAME type of product? (e.g., both are wall clocks, both are throw pillows, etc.)
Answer ONLY: yes or no

Rules:
- "yes" = same product category AND similar features
- "no"  = different product type (e.g., image had clock but Amazon shows plates)
- Minor variation in style/color is okay — category must match

Answer:"""

    try:
        client = Groq(api_key=GROQ_API_KEY)
        resp   = client.chat.completions.create(
            model       = GROQ_MODEL,
            messages    = [{"role": "user", "content": prompt}],
            temperature = 0.0,
            max_tokens  = 5,
        )
        answer = resp.choices[0].message.content.strip().lower()
        return answer.startswith("yes")
    except Exception as e:
        logger.warning(f"⚠️ [AmazonFetcher] Similarity check failed: {e}")
        # Fallback: word overlap
        extracted_words = set(extracted_product.lower().split())
        amazon_words    = set(amazon_title.lower().split())
        return bool(extracted_words & amazon_words)


# ══════════════════════════════════════════════════════════════════════════════
# AFFILIATE LINK
# ══════════════════════════════════════════════════════════════════════════════

def _make_affiliate(amazon_url: str) -> str:
    try:
        from tools.admitad import make_affiliate_link
        return make_affiliate_link(amazon_url)
    except Exception as e:
        logger.warning(f"⚠️ [AmazonFetcher] Affiliate link failed: {e}")
        return amazon_url


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PROCESSOR
# ══════════════════════════════════════════════════════════════════════════════

async def _process_one_product(extracted: dict) -> Optional[dict]:
    """
    Ek extracted product ke liye Amazon search → verify → affiliate karo.
    """
    product_name = extracted.get("name", "")
    if not product_name:
        return None

    logger.info(f"🔎 [AmazonFetcher] Searching: '{product_name}'")
    amazon_results = await _search_amazon(product_name, max_results=5)
    await asyncio.sleep(_CALL_DELAY)

    for item in amazon_results:
        title   = str(item.get("title", ""))
        asin    = str(item.get("asin", ""))
        price   = str(item.get("price", "$0.00"))
        thumb   = str(item.get("thumbnail", ""))
        rating  = float(str(item.get("rating", "0")).split()[0] or 0)
        reviews = int(''.join(filter(str.isdigit, str(item.get("ratingNumber", "0")))) or 0)

        # Quality shield
        if rating < 3.5 or reviews < 30:
            continue

        if not asin:
            continue

        # Similarity verification
        is_similar = _verify_similarity(product_name, title)
        if not is_similar:
            logger.info(f"  ❌ Not similar: '{title[:60]}'")
            continue

        amazon_url    = f"https://www.amazon.com/dp/{asin}"
        affiliate_url = _make_affiliate(amazon_url)

        logger.info(f"  ✅ Match: '{title[:60]}' | ${price} | ⭐{rating} ({reviews})")
        return {
            "extracted_name":  product_name,
            "amazon_title":    title[:150],
            "asin":            asin,
            "price":           price,
            "rating":          rating,
            "reviews":         reviews,
            "thumbnail":       thumb,
            "amazon_url":      amazon_url,
            "affiliate_url":   affiliate_url,
            "category":        extracted.get("category", ""),
        }

    logger.info(f"  ⚠️ No verified match found for '{product_name}'")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

async def fetch_amazon_products(extracted_products: List[dict]) -> List[dict]:
    """
    Extracted products list ke liye Amazon products fetch karo.

    Args:
        extracted_products: product_extractor.extract_products_from_image() ka output
            [{"name": "wall clock", "category": "home decor", "confidence": "high"}, ...]

    Returns:
        List of verified + affiliate-linked products:
        [
            {
                "extracted_name":  "geometric wall clock",
                "amazon_title":    "...",
                "asin":            "B0XYZ123",
                "price":           "$24.99",
                "rating":          4.5,
                "reviews":         1203,
                "thumbnail":       "https://...",
                "amazon_url":      "https://www.amazon.com/dp/B0XYZ123",
                "affiliate_url":   "https://www.amazon.com/dp/B0XYZ123?tag=swiftmart0008-20",
                "category":        "home decor",
            },
            ...
        ]
    """
    if not extracted_products:
        logger.info("ℹ️ [AmazonFetcher] No extracted products to search.")
        return []

    # Only process high/medium confidence
    to_process = [
        p for p in extracted_products
        if p.get("confidence", "medium") in ("high", "medium")
    ][:8]  # cap at 8 products per image

    logger.info(f"🛒 [AmazonFetcher] Processing {len(to_process)} products...")

    results = []
    for product in to_process:
        result = await _process_one_product(product)
        if result:
            results.append(result)
        await asyncio.sleep(_CALL_DELAY)

    logger.info(f"✅ [AmazonFetcher] {len(results)}/{len(to_process)} products verified & linked.")
    return results
