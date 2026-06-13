"""
mastermind/node_product_researcher.py — Node 5: Product Researcher

New Flow:
  Vision AI (4-model chain) → identifies product keywords from pin image
  RapidAPI → fetches 20 raw products per keyword
  Groq LLM → quality filters: primary / approved / rejected
  Google Sheets → saves ALL products (approved + rejected) in ONE batch call per keyword
  Blog → primary products returned for blog content

Vision fallback chain (10s wait between each):
  1st → Gemini Key 1  (GEMINI_API_KEY)   — gemini-2.5-flash  [vision]
  2nd → Gemini Key 2  (GEMINI_API_KEY_2) — gemini-2.5-flash  [vision]
  3rd → Groq Vision   (GROQ_API_KEY)     — llama-4-scout      [vision]
  4th → Cerebras Text (CEREBRAS_API_KEY) — llama-3.3-70b      [text fallback]

State input:  should_create_blog, last_posted_image_url, a1/a2_cmo_strategy, cycle_trigger
State output: blog_products (list of dicts with insert_after_para)

Sheets columns (Approved Deals):
  product_name | product_id | sale_price | rating | orders | affiliate_link
  | image_url | keyword | niche | Status
"""
import asyncio
import json
import logging
import os
import re

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
VISION_RETRY_DELAY  = 10    # seconds between vision model attempts
MAX_PRODUCTS_FETCH  = 20    # raw products to fetch from RapidAPI per keyword
MAX_KEYWORDS        = 5     # max keywords to process from vision AI
MAX_BLOG_PRODUCTS   = 4     # max products to include in blog

# Quality filter thresholds
MIN_RATING  = 3.5
MIN_REVIEWS = 50


# ── Prompts ────────────────────────────────────────────────────────────────────

VISION_PRODUCT_PROMPT = """You are a Product Identification Expert for Pinterest affiliate marketing.

Analyze this image and identify purchasable products visible in it.

CRITICAL OUTPUT RULES:
- Output ONLY a valid JSON array
- Array starts with [ and ends with ]
- No explanation, no markdown fences, no extra text before or after
- Exactly 3 products only

JSON format:
[
  {
    "product_name": "Purple Bed Sheet Set",
    "search_keyword": "purple bed sheets queen size",
    "category": "bedding",
    "price_range": "$20-$60",
    "why_fits": "Main bedding visible in pin",
    "suggested_para": 2
  }
]

Rules:
- search_keyword must be Amazon-optimized (3-6 words, specific, includes color/size/material if visible)
- category: bedding / furniture / lighting / decor / tech / gaming / accessories / kitchen / outdoor
- suggested_para: 1 to 6 (which paragraph to insert affiliate link)
- Exactly 3 products — no more, no less

Output ONLY the JSON array. Nothing else at all."""


QUALITY_FILTER_PROMPT = """You are an Amazon Product Quality Analyst for a Pinterest affiliate blog.

Original search keyword: "{keyword}"
Pin visual style: "{style}"
Niche: "{niche}"

Here are {count} products fetched from Amazon:
{products_json}

Your job:
1. Pick ONE "primary" — the single best product most relevant to the keyword
2. "approved" — all other products that pass quality standards
3. "rejected" — low quality, irrelevant, or suspicious products

Quality standards (ALL must pass for approved/primary):
- rating >= 3.5 (hard requirement)
- reviews >= 50 (hard requirement)
- price must be realistic (not $0.00)
- product must be genuinely related to keyword
- no suspicious/knockoff brands

Output ONLY valid JSON, no explanation, no markdown:
{{
  "primary": {{
    "asin": "B0XXXXXXXX",
    "reason": "Best match — strong reviews and exact keyword match"
  }},
  "approved": [
    {{"asin": "B0XXXXXXXX", "reason": "Good rating, related product"}}
  ],
  "rejected": [
    {{"asin": "B0XXXXXXXX", "reason": "rating 2.1 — below threshold"}}
  ]
}}

If NO product passes quality standards, set primary to null and approved to [].
Output ONLY the JSON object."""


# ── JSON Parsers ───────────────────────────────────────────────────────────────

def _parse_json_list(raw: str) -> list:
    """Robust JSON list parser."""
    if not raw or not raw.strip():
        logger.warning("[_parse_json_list] Empty raw response received")
        return []

    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    start = cleaned.find("[")
    end   = cleaned.rfind("]") + 1
    if start != -1 and end > 0:
        try:
            result = json.loads(cleaned[start:end])
            if isinstance(result, list) and result:
                logger.info(f"[_parse_json_list] ✅ Parsed array — {len(result)} items")
                return result
        except Exception as e:
            logger.warning(f"[_parse_json_list] Array parse failed: {e}")

    try:
        obj = json.loads(cleaned)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ["products", "items", "results", "data", "product_list"]:
                if key in obj and isinstance(obj[key], list):
                    return obj[key]
            if obj:
                return [obj]
    except Exception as e:
        logger.warning(f"[_parse_json_list] Full parse failed: {e}")

    logger.error(f"[_parse_json_list] ❌ Parse failed. Raw (300 chars):\n{cleaned[:300]}")
    return []


def _parse_json_dict(raw: str) -> dict:
    """Parse LLM response into a dict."""
    if not raw or not raw.strip():
        return {}

    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start != -1 and end > 0:
        try:
            result = json.loads(cleaned[start:end])
            if isinstance(result, dict):
                return result
        except Exception as e:
            logger.warning(f"[_parse_json_dict] Parse failed: {e} | Raw: {cleaned[:200]}")

    return {}


# ── Vision AI Functions ────────────────────────────────────────────────────────

async def _try_gemini(api_key: str, image_b64: str, key_label: str) -> list:
    """Gemini Vision call (Key 1 or Key 2) — uses google.genai SDK."""
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
                        genai_types.Part(text=VISION_PRODUCT_PROMPT),
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
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=4096,
            ),
        )

    response = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=60)
    raw = response.text.strip() if response.text else ""

    logger.info(f"[Vision] Gemini {key_label} raw (500 chars): {raw[:500]}")

    if not raw:
        logger.warning(f"[Vision] Gemini {key_label} returned empty response text")
        return []

    result = _parse_json_list(raw)
    if not result:
        logger.warning(f"[Vision] Gemini {key_label} parsed to empty list")
    return result


async def _try_groq_vision(image_b64: str) -> list:
    """Groq Vision (llama-4-scout) — async client."""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        raise RuntimeError("GROQ_API_KEY not configured")

    from groq import AsyncGroq
    client = AsyncGroq(api_key=groq_key)

    resp = await client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}
                },
                {
                    "type": "text",
                    "text": VISION_PRODUCT_PROMPT
                }
            ]
        }],
        temperature=0.1,
        max_tokens=1200,
    )

    raw = resp.choices[0].message.content or ""
    logger.info(f"[Vision] Groq Vision raw (300 chars): {raw[:300]}")
    return _parse_json_list(raw)


async def _try_cerebras_text(style: str, niche: str, tags: list) -> list:
    """Cerebras text fallback — no image, infers products from style/niche/tags."""
    cerebras_key = os.getenv("CEREBRAS_API_KEY")
    if not cerebras_key:
        raise RuntimeError("CEREBRAS_API_KEY not configured")

    from cerebras.cloud.sdk import AsyncCerebras
    client = AsyncCerebras(api_key=cerebras_key)

    prompt = f"""Based on a Pinterest pin with style='{style}', niche='{niche}', tags={tags},
suggest 5 Amazon products someone would buy.

Output ONLY a valid JSON array:
[
  {{
    "product_name": "...",
    "search_keyword": "...",
    "category": "...",
    "price_range": "...",
    "why_fits": "...",
    "suggested_para": 2
  }}
]"""

    resp = await client.chat.completions.create(
        model="llama-3.3-70b",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3,
        max_tokens=1000,
    )

    raw = resp.choices[0].message.content or ""
    return _parse_json_list(raw)


async def _identify_products_with_fallback(
    image_b64: str,
    style: str = "",
    niche: str = "home",
    tags: list = None,
) -> list:
    """
    4-model fallback chain for product identification.
    Gemini Key1 → Gemini Key2 → Groq Vision → Cerebras Text
    10s wait between each attempt.
    """
    tags = tags or []

    gemini_key1 = os.getenv("GEMINI_API_KEY", "")
    gemini_key2 = os.getenv("GEMINI_API_KEY_2", "")

    attempts = [
        ("Gemini Key 1",  lambda: _try_gemini(gemini_key1, image_b64, "Key 1")),
        ("Gemini Key 2",  lambda: _try_gemini(gemini_key2, image_b64, "Key 2")),
        ("Groq Vision",   lambda: _try_groq_vision(image_b64)),
        ("Cerebras Text", lambda: _try_cerebras_text(style, niche, tags)),
    ]

    for label, fn in attempts:
        try:
            logger.info(f"👁️ [Vision] Trying {label}...")
            result = await fn()
            if result:
                logger.info(f"✅ [Vision] {label} succeeded — {len(result)} products identified")
                return result
            logger.warning(f"⚠️ [Vision] {label} returned empty list")
        except Exception as e:
            logger.warning(f"⚠️ [Vision] {label} failed: {str(e)[:120]}")

        logger.info(f"⏳ [Vision] Waiting {VISION_RETRY_DELAY}s before next model...")
        await asyncio.sleep(VISION_RETRY_DELAY)

    logger.error("❌ [Vision] All 4 models failed — returning empty product list")
    return []


async def _download_image_b64(image_url: str) -> str:
    """Download image from URL and return base64 string."""
    try:
        import httpx, base64
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(image_url)
            r.raise_for_status()
            b64 = base64.b64encode(r.content).decode("utf-8")
            logger.info(f"[Vision] Image downloaded: {len(r.content):,} bytes → {len(b64)} b64 chars")
            return b64
    except Exception as e:
        logger.error(f"[Vision] Image download failed for {image_url}: {e}")
        return ""


# ── LLM Quality Filter ─────────────────────────────────────────────────────────

async def _llm_quality_filter(keyword: str, style: str, niche: str, raw_products: list) -> dict:
    """
    Use Groq LLM to quality-filter fetched products.
    Returns: {primary: {asin, reason}, approved: [...], rejected: [...]}
    Falls back to basic numeric filter if Groq unavailable.
    """
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        logger.warning("[QualityFilter] GROQ_API_KEY not set — using basic filter")
        return _basic_quality_filter(raw_products)

    slim = []
    for p in raw_products:
        rating = _extract_rating(p)
        reviews = _extract_reviews(p)

        if len(slim) < 3:
            logger.info(
                f"[SlimBuild] asin={p.get('asin','')} | rating={rating} | "
                f"reviews={reviews} | raw_keys={list(p.keys())}"
            )

        slim.append({
            "asin":    p.get("asin", p.get("product_id", "")),
            "title":   p.get("productTitle", p.get("product_name", ""))[:80],
            "rating":  rating,
            "reviews": reviews,
            "price":   str(p.get("price", p.get("sale_price", ""))),
        })

    prompt = QUALITY_FILTER_PROMPT.format(
        keyword=keyword,
        style=style,
        niche=niche,
        count=len(slim),
        products_json=json.dumps(slim, indent=2),
    )

    try:
        from groq import AsyncGroq
        client = AsyncGroq(api_key=groq_key)

        resp = await client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500,
        )

        raw = resp.choices[0].message.content or ""
        result = _parse_json_dict(raw)

        if not result:
            logger.warning("[QualityFilter] LLM returned empty dict — using basic filter")
            return _basic_quality_filter(raw_products)

        primary  = result.get("primary") or {}
        approved = result.get("approved", [])
        rejected = result.get("rejected", [])

        logger.info(
            f"[QualityFilter] ✅ keyword='{keyword}' | "
            f"primary={'✅ ' + primary.get('asin','?') if primary else '❌ none'} | "
            f"approved={len(approved)} | rejected={len(rejected)}"
        )
        return result

    except Exception as e:
        logger.warning(f"[QualityFilter] Groq failed: {e} — using basic filter")
        return _basic_quality_filter(raw_products)


def _extract_rating(p: dict) -> float:
    """Extract rating from raw product dict — tries all known field names."""
    for field in ["stars", "rating", "averageRating", "productRating", "avgRating", "productStar"]:
        val = p.get(field)
        if val:
            try:
                r = float(str(val).split()[0])
                if r > 0:
                    return r
            except Exception:
                continue
    return 0.0


def _extract_reviews(p: dict) -> int:
    """Extract review count from raw product dict — tries all known field names."""
    for field in ["numberOfRatings", "reviews", "reviewCount", "totalReviews",
                  "ratingsCount", "numberOfReviews", "ratingCount"]:
        val = p.get(field)
        if val:
            try:
                r = int(''.join(filter(str.isdigit, str(val))) or 0)
                if r > 0:
                    return r
            except Exception:
                continue
    return 0


def _basic_quality_filter(raw_products: list) -> dict:
    """Fallback quality filter without LLM — uses rating/review thresholds only."""
    approved = []
    rejected = []

    for p in raw_products:
        asin    = p.get("asin", p.get("product_id", ""))
        rating  = _extract_rating(p)
        reviews = _extract_reviews(p)
        title   = p.get("productTitle", "")[:50]

        if rating >= MIN_RATING and reviews >= MIN_REVIEWS:
            approved.append({"asin": asin, "reason": f"rating={rating}, reviews={reviews}"})
            logger.info(f"[BasicFilter] ✅ '{title}' | rating={rating} | reviews={reviews}")
        else:
            rejected.append({"asin": asin, "reason": f"rating={rating}<3.5 or reviews={reviews}<50"})
            logger.warning(f"[BasicFilter] ❌ '{title}' | rating={rating} | reviews={reviews}")

    primary = approved[0] if approved else None
    return {
        "primary":  primary,
        "approved": approved[1:] if len(approved) > 1 else [],
        "rejected": rejected,
    }


# ── Product Normalizer ─────────────────────────────────────────────────────────

async def _normalize_product(item: dict, keyword: str = "", niche: str = "") -> dict:
    """
    Convert raw RapidAPI item → fully normalized product dict.

    Uses tools/admitad.py → enrich_with_affiliate_link(product: dict) -> dict
    which appends Amazon Associates tag to the product URL.

    Returns dict matching Sheets columns:
      product_name, product_id, sale_price, rating, orders,
      affiliate_link, image_url, keyword, niche, Status
    """
    from tools.admitad import enrich_with_affiliate_link
    from tools.aliexpress import get_rapidapi_gallery, get_best_lifestyle_image

    asin    = item.get("asin", item.get("product_id", ""))
    title   = item.get("productTitle", item.get("product_name", "Amazon Product"))
    price   = item.get("price", item.get("sale_price", "$0.00"))
    rating  = _extract_rating(item)
    reviews = _extract_reviews(item)

    # ── Image URL: try gallery first, fallback to thumbnail ───────────────────
    image_url = item.get("imgUrl", item.get("thumbnailImage", item.get("image_url", "")))
    try:
        gallery = await get_rapidapi_gallery(asin)
        await asyncio.sleep(1)
        if gallery:
            image_url = await get_best_lifestyle_image(gallery) or image_url
    except Exception as e:
        logger.warning(f"[Normalize] Gallery fetch failed for {asin}: {e}")

    # ── Build product dict for affiliate enrichment ───────────────────────────
    product_url = f"https://www.amazon.com/dp/{asin}"

    product_dict = {
        "product_id":   asin,
        "product_name": title[:100],
        "product_url":  product_url,
        "sale_price":   str(price),
        "rating":       rating,
        "orders":       reviews,          # 'orders' column = review count (Amazon proxy)
        "image_url":    image_url,
        "keyword":      keyword,
        "niche":        niche,
    }

    # ── Enrich with affiliate link via tools/admitad.py ───────────────────────
    try:
        enriched = enrich_with_affiliate_link(product_dict)
        affiliate_link = enriched.get("affiliate_link", enriched.get("affiliate_url", product_url))
    except Exception as e:
        logger.warning(f"[Normalize] enrich_with_affiliate_link failed for {asin}: {e}")
        affiliate_link = product_url  # fallback to plain URL

    return {
        "product_id":    asin,
        "product_name":  title[:100],
        "sale_price":    str(price),
        "rating":        rating,
        "orders":        reviews,
        "affiliate_link": affiliate_link,
        "image_url":     image_url,
        "keyword":       keyword,
        "niche":         niche,
        "Status":        "PENDING",
        # kept for internal use / blog node
        "product_url":   product_url,
        "affiliate_url": affiliate_link,
    }


# ── Sheets Batch Builder ───────────────────────────────────────────────────────

def _build_sheets_rows(
    approved_products: list,
    keyword: str,
    niche: str,
) -> list:
    """
    Build a flat list of row dicts for Google Sheets.
    Only approved products are saved — rejected are discarded.

    All rows go into one batch → single API call to Sheets.
    """
    rows = []

    for prod in approved_products:
        rows.append({
            "product_name":   prod.get("product_name", ""),
            "product_id":     prod.get("product_id", ""),
            "sale_price":     prod.get("sale_price", ""),
            "rating":         prod.get("rating", ""),
            "orders":         prod.get("orders", ""),
            "affiliate_link": prod.get("affiliate_link", ""),
            "image_url":      prod.get("image_url", ""),
            "keyword":        keyword,
            "niche":          niche,
            "Status":         "PENDING",
        })

    logger.info(
        f"[SheetsRows] keyword='{keyword}' | approved_rows={len(rows)}"
    )
    return rows


# ── Main Node ──────────────────────────────────────────────────────────────────

async def node_product_researcher(state: dict) -> dict:
    """
    Node 5 — Product Researcher.

    Full flow:
    1. Vision AI (4-model fallback) identifies product keywords from pin image
    2. RapidAPI fetches 20 raw products per keyword
    3. Groq LLM quality-filters: primary / approved / rejected
       → Hard filter: rating >= 3.5 AND reviews >= 50
    4. Approved products normalized: full data + affiliate_link via admitad
    5. ALL products (approved + rejected) saved to 'Approved Deals' sheet in ONE batch call
    6. Primary products returned for blog (max 4)

    Sheets columns:
      product_name | product_id | sale_price | rating | orders | affiliate_link
      | image_url | keyword | niche | Status
    """
    # ── Guard: skip if blog not needed ────────────────────────────────────────
    if not state.get("should_create_blog"):
        logger.info("🛍️ [ProductResearcher] Skipping — should_create_blog=False")
        return {**state, "blog_products": []}

    image_url = state.get("last_posted_image_url", "")
    if not image_url:
        logger.warning("🛍️ [ProductResearcher] No image URL in state")
        return {**state, "blog_products": []}

    # ── Determine account context ─────────────────────────────────────────────
    trigger = state.get("cycle_trigger", "")
    is_acc2 = "account2" in trigger and "account1" not in trigger
    account = "account_2" if is_acc2 else "account_1"
    cmo     = state.get("a2_cmo_strategy", {}) if is_acc2 else state.get("a1_cmo_strategy", {})

    style   = cmo.get("visual_style", cmo.get("vibe", "aesthetic"))
    niche   = cmo.get("niche", "home")
    tags    = list(cmo.get("tags", []))

    logger.info(
        f"🛍️ [ProductResearcher] Starting | account={account} | "
        f"style={style} | niche={niche} | image={image_url[:60]}..."
    )

    # ── Step 1: Download image ────────────────────────────────────────────────
    image_b64 = await _download_image_b64(image_url)
    if not image_b64:
        logger.error("🛍️ [ProductResearcher] Image download failed — no blog products")
        return {**state, "blog_products": []}

    # ── Step 2: Vision AI (4-model fallback) → product keywords ──────────────
    identified = await _identify_products_with_fallback(
        image_b64=image_b64,
        style=style,
        niche=niche,
        tags=tags,
    )

    if not identified:
        logger.error("🛍️ [ProductResearcher] Vision returned no products — blog will have no products")
        return {**state, "blog_products": []}

    logger.info(
        f"🛍️ [ProductResearcher] Vision identified {len(identified)} keywords: "
        f"{[i.get('search_keyword', '?') for i in identified]}"
    )

    # ── Step 3: Load sheets (optional — don't abort if unavailable) ───────────
    sheets_ok = False
    save_rows_batch = None
    try:
        from tools.sheets_product_store import save_rows_batch as _save_rows_batch
        from sheets.base import _open_worksheet
        _open_worksheet("Approved Deals")   # probe — raises if creds not set
        save_rows_batch = _save_rows_batch
        sheets_ok = True
        logger.info("📊 [ProductResearcher] Sheets connection OK — will save products")
    except ImportError:
        # Fallback: try old save_products_batch API
        try:
            from tools.sheets_product_store import save_products_batch as _save_products_batch
            from sheets.base import _open_worksheet
            _open_worksheet("Approved Deals")
            sheets_ok = True
            logger.info("📊 [ProductResearcher] Sheets connection OK (legacy API)")
        except Exception as e:
            logger.warning(f"📊 [ProductResearcher] Sheets not available: {e}")
    except Exception as e:
        logger.warning(f"📊 [ProductResearcher] Sheets not available: {e}")

    # ── Step 4: Per-keyword → fetch → filter → normalize → save → collect ────
    from tools.aliexpress import fetch_rapidapi

    blog_products = []

    for vision_item in identified[:MAX_KEYWORDS]:
        keyword = vision_item.get("search_keyword", vision_item.get("product_name", "")).strip()
        if not keyword:
            continue

        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 [ProductResearcher] Processing keyword: '{keyword}'")

        # ── Fetch raw products ────────────────────────────────────────────────
        try:
            raw_products = await fetch_rapidapi(keyword, max_results=MAX_PRODUCTS_FETCH)
        except Exception as e:
            logger.warning(f"⚠️ [ProductResearcher] fetch_rapidapi failed for '{keyword}': {e}")
            raw_products = None

        if not raw_products:
            logger.warning(f"⚠️ [ProductResearcher] No products from RapidAPI for '{keyword}' — skipping")
            continue

        logger.info(f"📦 [ProductResearcher] Got {len(raw_products)} raw products for '{keyword}'")

        # ── LLM quality filter ────────────────────────────────────────────────
        try:
            filter_result = await _llm_quality_filter(keyword, style, niche, raw_products)
        except Exception as e:
            logger.warning(f"⚠️ [ProductResearcher] Quality filter error: {e} — using basic filter")
            filter_result = _basic_quality_filter(raw_products)

        primary_info   = filter_result.get("primary") or {}
        approved_list  = filter_result.get("approved", [])
        rejected_list  = filter_result.get("rejected", [])
        primary_asin   = primary_info.get("asin", "")

        # All approved ASINs = primary + approved list
        approved_asins = ({primary_asin} | {a["asin"] for a in approved_list if a.get("asin")}) - {""}

        logger.info(
            f"[ProductResearcher] Filter result: primary={primary_asin or 'NONE'} | "
            f"approved_total={len(approved_asins)} | rejected={len(rejected_list)}"
        )

        # ── Build ASIN → raw item lookup ──────────────────────────────────────
        asin_to_raw = {
            p.get("asin", p.get("product_id", "")): p
            for p in raw_products
        }

        # ── Normalize approved products ───────────────────────────────────────
        approved_normalized = []
        for asin in approved_asins:
            raw_item = asin_to_raw.get(asin)
            if not raw_item:
                continue
            try:
                normalized = await _normalize_product(raw_item, keyword=keyword, niche=niche)
                normalized["ai_reason"] = (
                    primary_info.get("reason", "Primary product")
                    if asin == primary_asin
                    else next(
                        (a["reason"] for a in approved_list if a.get("asin") == asin),
                        "Quality approved"
                    )
                )
                approved_normalized.append(normalized)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"[ProductResearcher] Normalize failed for {asin}: {e}")

        logger.info(f"[ProductResearcher] Normalized {len(approved_normalized)} approved products")

        # ── Save ALL products to Sheets in ONE batch call ─────────────────────
        if sheets_ok:
            try:
                if save_rows_batch:
                    # ── New API: save_rows_batch(rows: list[dict]) ────────────
                    rows = _build_sheets_rows(
                        approved_products=approved_normalized,
                        keyword=keyword,
                        niche=niche,
                    )
                    saved = save_rows_batch(rows)
                    logger.info(f"📊 [ProductResearcher] Sheets: {len(rows)} rows saved for '{keyword}'")
                else:
                    # ── Legacy API fallback ───────────────────────────────────
                    from tools.sheets_product_store import save_products_batch
                    saved = save_products_batch(
                        keyword=keyword,
                        niche=niche,
                        primary_asin=primary_asin,
                        approved_products=approved_normalized,
                        rejected_products=[],   # rejected nahi daalenge sheets mein
                    )
                    logger.info(f"📊 [ProductResearcher] Sheets (legacy): {saved} rows saved for '{keyword}'")
            except Exception as e:
                logger.warning(f"⚠️ [ProductResearcher] Sheets save failed for '{keyword}': {e}")

        # ── Pick primary product for blog ─────────────────────────────────────
        if len(blog_products) < MAX_BLOG_PRODUCTS:
            if not approved_normalized:
                logger.warning(f"[ProductResearcher] No approved products for '{keyword}' — skipping blog entry")
            else:
                primary_product = next(
                    (p for p in approved_normalized if p["product_id"] == primary_asin),
                    approved_normalized[0],
                )

                blog_entry = {
                    "name":              primary_product["product_name"],
                    "price":             primary_product["sale_price"],
                    "affiliate_url":     primary_product["affiliate_link"],   # ← affiliate_link field
                    "image_url":         primary_product.get("image_url", ""),
                    "insert_after_para": int(vision_item.get("suggested_para", len(blog_products) * 2 + 1)),
                    "why_fits":          vision_item.get("why_fits", primary_product.get("ai_reason", "")),
                    "keyword":           keyword,
                    "niche":             niche,
                    "rating":            primary_product.get("rating", ""),
                    "orders":            primary_product.get("orders", ""),
                }
                blog_products.append(blog_entry)
                logger.info(
                    f"✅ [ProductResearcher] Blog product #{len(blog_products)}: "
                    f"'{primary_product['product_name'][:50]}' | "
                    f"asin={primary_asin} | keyword='{keyword}' | "
                    f"affiliate={primary_product['affiliate_link'][:60]}"
                )

        await asyncio.sleep(2)   # rate-limit buffer between keywords

    logger.info(
        f"\n🛍️ [ProductResearcher] DONE | "
        f"blog_products={len(blog_products)} | "
        f"keywords_processed={min(len(identified), MAX_KEYWORDS)}"
    )

    return {**state, "blog_products": blog_products}
