# 🤖 Replit Agent — Complete Fix: Vision → Product Fetch → Sheets → Blog

## 🎯 Mission Overview

Tujhe yeh kaam karna hai **ek complete new product pipeline** banana jo existing code ke saath kaam kare:

1. **Vision AI** se image se product keywords extract ho
2. **RapidAPI** se har keyword ke liye **20 products** fetch ho
3. **LLM (Groq)** quality verify kare — rating, reviews, relevance check
4. **Approved products** `Approved Deals` Google Sheet mein save ho
5. **Primary (best match) product** blog ke liye select ho
6. **Blog mein products** properly show ho

---

## 📁 Files jo modify/create karni hain

```
tools/
  aliexpress.py          ← MODIFY (fetch_rapidapi max_results fix)
  sheets_product_store.py ← CREATE NEW
mastermind/
  node_product_researcher.py  ← FULL REWRITE
```

---

## ❌ Current Bugs (Fix These First)

### Bug 1: Gemini Vision — 200 OK but Empty List

**File:** `mastermind/node_product_researcher.py`

**Problem:** `_try_gemini()` function mein Gemini `200 OK` return karta hai lekin response empty list ban jaata hai.

**Root cause:** Gemini response ek JSON **object** `{}` return karta hai ya plain text, lekin `_parse_json()` function sirf **array** `[]` dhundta hai. Agar `[` bracket nahi mila toh `[]` return ho jaata hai.

**Fix — `_parse_json` function update karo:**

```python
def _parse_json(raw: str) -> list:
    """
    Parse LLM response into a list.
    Handles: JSON array, JSON object with list key, plain text fallback.
    """
    if not raw or not raw.strip():
        logger.warning("[_parse_json] Empty raw response received")
        return []
    
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    
    # Try direct array parse first
    start = cleaned.find("[")
    end   = cleaned.rfind("]") + 1
    if start != -1 and end > 0:
        try:
            result = json.loads(cleaned[start:end])
            if isinstance(result, list) and result:
                logger.info(f"[_parse_json] ✅ Parsed array — {len(result)} items")
                return result
        except Exception as e:
            logger.warning(f"[_parse_json] Array parse failed: {e}")
    
    # Try full JSON parse (might be object with list inside)
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            # Look for any key that contains a list
            for key in ["products", "items", "results", "data", "product_list"]:
                if key in obj and isinstance(obj[key], list):
                    logger.info(f"[_parse_json] ✅ Found list under key '{key}'")
                    return obj[key]
            # Return single item wrapped in list
            if obj:
                logger.info("[_parse_json] ✅ Wrapped single object in list")
                return [obj]
    except Exception as e:
        logger.warning(f"[_parse_json] Full JSON parse failed: {e}")
    
    logger.error(f"[_parse_json] ❌ Could not parse response. Raw (first 300):\n{raw[:300]}")
    return []
```

---

### Bug 2: Gemini `_try_gemini` Function — Prompt Fix

**File:** `mastermind/node_product_researcher.py`

**Problem:** Gemini ko jo prompt diya ja raha hai woh kabhi kabhi object return karta hai array nahi.

**Fix — `_try_gemini` prompt update karo:**

```python
VISION_PRODUCT_PROMPT = """You are a Product Identification Expert for Pinterest affiliate marketing.

Analyze this image carefully and identify ALL purchasable products visible.

CRITICAL OUTPUT RULES:
- Output ONLY a valid JSON array
- No explanation, no markdown, no extra text
- Array must start with [ and end with ]
- Minimum 3 products, maximum 5 products

Required JSON structure:
[
  {
    "product_name": "Purple Bed Sheet Set",
    "search_keyword": "purple bed sheets queen size",
    "category": "bedding",
    "price_range": "$20-$60",
    "why_fits": "Main bedding item visible in the pin",
    "suggested_para": 2
  }
]

Field rules:
- product_name: Clean product title
- search_keyword: Amazon search-optimized keyword (3-6 words, specific)
- category: One of: bedding, furniture, lighting, decor, tech, gaming, accessories
- price_range: Estimated price range
- why_fits: Why this product fits the Pinterest pin (1 sentence)
- suggested_para: Which paragraph number to insert affiliate link (1-6)

Respond with ONLY the JSON array. Nothing else."""
```

**Also add raw response logging in `_try_gemini`:**

```python
async def _try_gemini(api_key: str, image_b64: str, key_label: str) -> list:
    """Try Gemini Vision for product identification."""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        image_part = {
            "mime_type": "image/jpeg",
            "data": image_b64
        }
        
        response = model.generate_content(
            [VISION_PRODUCT_PROMPT, image_part],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,  # LOW temperature for consistent JSON
                max_output_tokens=1000,
            )
        )
        
        raw = response.text.strip() if response.text else ""
        
        # CRITICAL: Always log raw response for debugging
        logger.info(f"[Vision] Gemini {key_label} raw response (first 500): {raw[:500]}")
        
        if not raw:
            logger.warning(f"[Vision] Gemini {key_label} returned empty text")
            return []
        
        result = _parse_json(raw)
        
        if not result:
            logger.warning(f"[Vision] Gemini {key_label} parsed to empty list. Raw was: {raw[:300]}")
        
        return result
        
    except Exception as e:
        logger.warning(f"[Vision] Gemini {key_label} exception: {str(e)[:200]}")
        raise
```

---

### Bug 3: RapidAPI Returns 20 Products But Blog Mein Zero

**Root Cause:** Quality filter `rating < 3.5 or reviews < 50` silently drop kar deta hai products ko. Koi log nahi hota.

**Fix — quality filter mein debug logging add karo:**

```python
# In search_products() function in tools/aliexpress.py
# BEFORE the quality filter, add this:

filtered_count = 0
for idx, item in enumerate(raw_products[:max_results]):
    try:
        rating = float(str(item.get("stars", "0")).split()[0])
    except Exception:
        rating = 0.0
    try:
        reviews = int(''.join(filter(str.isdigit, str(item.get("numberOfRatings", "0")))) or 0)
    except Exception:
        reviews = 0
    
    title = item.get("productTitle", "")[:60]
    
    # Log EVERY product and why it passes/fails
    if rating < 3.5 or reviews < 50:
        logger.warning(
            f"[QualityFilter] ❌ REJECTED: '{title}' | "
            f"rating={rating} (need≥3.5) | reviews={reviews} (need≥50)"
        )
        filtered_count += 1
        continue
    
    logger.info(
        f"[QualityFilter] ✅ PASSED: '{title}' | "
        f"rating={rating} | reviews={reviews}"
    )
    # ... rest of normalization
```

---

## 🆕 New File: `tools/sheets_product_store.py`

**Create this file from scratch:**

```python
"""
sheets_product_store.py
Saves fetched Amazon products (approved + rejected) to 'Approved Deals' Google Sheet.
Sheet format matches existing: product_name | product_id | sale_price | rating | orders | affiliate_link | image_url | keyword | niche | Status
"""
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

PRODUCT_SHEET_NAME = "Approved Deals"

# Must match EXACT column order of existing sheet
SHEET_COLUMNS = [
    "product_name",   # col A
    "product_id",     # col B  (ASIN)
    "sale_price",     # col C
    "rating",         # col D
    "orders",         # col E  (reviews count)
    "affiliate_link", # col F
    "image_url",      # col G
    "keyword",        # col H
    "niche",          # col I
    "Status",         # col J  → "approved" / "rejected" / "primary"
]


def _get_sheet(sheets_client):
    """Get the Approved Deals worksheet. Returns None on failure."""
    try:
        return sheets_client.worksheet(PRODUCT_SHEET_NAME)
    except Exception as e:
        logger.error(f"[ProductStore] ❌ Cannot access sheet '{PRODUCT_SHEET_NAME}': {e}")
        return None


def save_products_batch(
    sheets_client,
    keyword: str,
    niche: str,
    primary_asin: str,
    approved_products: list,
    rejected_products: list,
):
    """
    Append all products to 'Approved Deals' sheet in one batch.
    
    approved_products: list of normalized product dicts (from _normalize_product)
    rejected_products: list of dicts with at least {product_id, product_name}
    primary_asin: the ASIN selected for blog
    """
    ws = _get_sheet(sheets_client)
    if not ws:
        logger.error("[ProductStore] Sheet not accessible — skipping save")
        return 0
    
    rows = []
    
    # Add approved products
    for product in approved_products:
        asin = product.get("product_id", "")
        
        if asin == primary_asin:
            status = "primary"       # This one goes to blog
        else:
            status = "approved"      # Quality passed, saved for future use
        
        rows.append([
            product.get("product_name", "")[:100],
            asin,
            str(product.get("sale_price", "")),
            str(product.get("rating", "")),
            str(product.get("reviews", "")),
            product.get("affiliate_url", product.get("product_url", "")),
            product.get("image_url", ""),
            keyword,
            niche,
            status,
        ])
    
    # Add rejected products (minimal info)
    for product in rejected_products:
        rows.append([
            product.get("product_name", "")[:100],
            product.get("product_id", product.get("asin", "")),
            str(product.get("sale_price", "")),
            str(product.get("rating", "")),
            str(product.get("reviews", "")),
            "",   # no affiliate link for rejected
            "",
            keyword,
            niche,
            "rejected",
        ])
    
    if not rows:
        logger.warning(f"[ProductStore] No rows to save for keyword='{keyword}'")
        return 0
    
    try:
        ws.append_rows(rows, value_input_option="RAW")
        approved_count = len(approved_products)
        rejected_count = len(rejected_products)
        logger.info(
            f"[ProductStore] ✅ Saved {len(rows)} rows for '{keyword}' | "
            f"approved={approved_count} (1 primary) | rejected={rejected_count}"
        )
        return len(rows)
    except Exception as e:
        logger.error(f"[ProductStore] ❌ append_rows failed: {e}")
        return 0
```

---

## 🔄 Updated `tools/aliexpress.py` — fetch_rapidapi max_results fix

**Find `fetch_rapidapi` function and update signature:**

```python
async def fetch_rapidapi(keyword: str, max_results: int = 20):
    """
    RapidAPI Search with automatic key rotation (KEY1 → KEY2 on any failure).
    max_results: how many products to return (default 20 for new bulk flow)
    """
    # Key 1 (primary)
    if RAPIDAPI_KEY:
        result = await _rapidapi_request(keyword, RAPIDAPI_KEY, "KEY1", max_results=max_results)
        if result is not None:
            return result
        logger.warning("🔄 RapidAPI KEY1 failed — rotating to KEY2...")
    else:
        logger.warning("⚠️ RAPIDAPI_KEY not set — skipping KEY1")

    # Key 2 (fallback)
    if RAPIDAPI_KEY2:
        result = await _rapidapi_request(keyword, RAPIDAPI_KEY2, "KEY2", max_results=max_results)
        if result is not None:
            logger.info("✅ RapidAPI KEY2 succeeded.")
        return result

    logger.error("❌ No RapidAPI keys available or both failed.")
    return None
```

**Update `_rapidapi_request` to accept max_results:**

```python
async def _rapidapi_request(keyword: str, api_key: str, key_label: str, max_results: int = 20):
    """Single RapidAPI attempt. Returns raw products list or None."""
    headers = {
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key":  api_key,
    }
    params = {
        "domainCode":      "com",
        "keyword":         keyword,
        "page":            "1",
        "excludeSponsored":"false",
        "sortBy":          "relevanceblender",
        "withCache":       "true",
    }
    try:
        async with httpx.AsyncClient(timeout=30, http2=True) as client:
            r = await client.get(SEARCH_URL, headers=headers, params=params)
            
            if r.status_code == 403:
                logger.warning(f"⚠️ RapidAPI [{key_label}] returned 403: {r.text[:200]}")
                return None
            if r.status_code != 200:
                logger.warning(f"⚠️ RapidAPI [{key_label}] returned {r.status_code}: {r.text[:300]}")
                return None
            
            data = r.json()
            products = data.get("searchProductDetails", [])
            
            if not products:
                logger.warning(f"⚠️ RapidAPI [{key_label}] searchProductDetails empty for '{keyword}'")
                logger.debug(f"Full response keys: {list(data.keys())}")
                return None
            
            logger.info(f"✅ RapidAPI [{key_label}] got {len(products)} products for '{keyword}'")
            return products[:max_results] if isinstance(products, list) else None
            
    except Exception as e:
        logger.warning(f"⚠️ RapidAPI [{key_label}] exception: {e}")
        return None
```

---

## 🧠 Full Rewrite: `mastermind/node_product_researcher.py`

**Replace the ENTIRE file with this:**

```python
"""
node_product_researcher.py
New Flow: Vision AI → Bulk Fetch (20/keyword) → LLM Quality Filter → Sheets Save → Blog Products
"""
import json
import logging
import re
import asyncio
import os

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
VISION_RETRY_DELAY = 10      # seconds between vision model attempts
MAX_PRODUCTS_FETCH  = 20     # fetch this many from RapidAPI per keyword
MAX_KEYWORDS        = 5      # max keywords from vision AI
MAX_BLOG_PRODUCTS   = 4      # max products to pass to blog

# ── Prompts ────────────────────────────────────────────────────────────────────

VISION_PRODUCT_PROMPT = """You are a Product Identification Expert for Pinterest affiliate marketing.

Analyze this image and identify ALL purchasable products visible in it.

CRITICAL OUTPUT RULES:
- Output ONLY a valid JSON array
- Array starts with [ and ends with ]
- No explanation, no markdown fences, no extra text before or after
- 3 to 5 products minimum

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
{
  "primary": {
    "asin": "B0XXXXXXXX",
    "reason": "Best match — strong reviews and exact keyword match"
  },
  "approved": [
    {"asin": "B0XXXXXXXX", "reason": "Good rating, related product"}
  ],
  "rejected": [
    {"asin": "B0XXXXXXXX", "reason": "rating 2.1 — below threshold"}
  ]
}

If NO product passes quality standards, set primary to null and approved to [].
Output ONLY the JSON object."""


# ── JSON Parser ────────────────────────────────────────────────────────────────

def _parse_json_list(raw: str) -> list:
    """
    Robust JSON list parser.
    Handles: array, object with list key, single object, malformed JSON.
    """
    if not raw or not raw.strip():
        logger.warning("[_parse_json_list] Empty raw response")
        return []
    
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    
    # Try direct array parse
    start = cleaned.find("[")
    end   = cleaned.rfind("]") + 1
    if start != -1 and end > 0:
        try:
            result = json.loads(cleaned[start:end])
            if isinstance(result, list) and result:
                logger.info(f"[_parse_json_list] ✅ Array parsed — {len(result)} items")
                return result
        except Exception as e:
            logger.warning(f"[_parse_json_list] Array parse failed: {e}")
    
    # Try full object parse
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, list):
            return obj
        if isinstance(obj, dict):
            for key in ["products", "items", "results", "data", "product_list"]:
                if key in obj and isinstance(obj[key], list):
                    logger.info(f"[_parse_json_list] ✅ List found under key '{key}'")
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
    """Try Gemini Vision to identify products from image."""
    if not api_key:
        logger.warning(f"[Vision] Gemini {key_label}: API key not set")
        return []
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        image_part = {"mime_type": "image/jpeg", "data": image_b64}
        
        response = model.generate_content(
            [VISION_PRODUCT_PROMPT, image_part],
            generation_config=genai.GenerationConfig(
                response_mime_type="application/json",
                temperature=0.1,
                max_output_tokens=1200,
            )
        )
        
        raw = response.text.strip() if response.text else ""
        logger.info(f"[Vision] Gemini {key_label} raw (500 chars): {raw[:500]}")
        
        if not raw:
            logger.warning(f"[Vision] Gemini {key_label} returned empty response text")
            return []
        
        result = _parse_json_list(raw)
        if not result:
            logger.warning(f"[Vision] Gemini {key_label} parsed to empty — check raw above")
        
        return result
        
    except Exception as e:
        logger.warning(f"[Vision] Gemini {key_label} error: {str(e)[:200]}")
        raise


async def _try_groq_vision(image_b64: str) -> list:
    """Try Groq Vision (llava) to identify products."""
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        return []
    try:
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
        
    except Exception as e:
        logger.warning(f"[Vision] Groq Vision error: {str(e)[:200]}")
        raise


async def _try_cerebras_text(style: str, niche: str, tags: list) -> list:
    """Cerebras text fallback — no image, uses style/niche/tags."""
    cerebras_key = os.getenv("CEREBRAS_API_KEY")
    if not cerebras_key:
        return []
    try:
        from cerebras.cloud.sdk import AsyncCerebras
        client = AsyncCerebras(api_key=cerebras_key)
        
        prompt = f"""Based on a Pinterest pin with style='{style}', niche='{niche}', tags={tags},
suggest 5 Amazon products someone would buy.

Output ONLY valid JSON array:
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
        
    except Exception as e:
        logger.warning(f"[Vision] Cerebras text error: {str(e)[:200]}")
        raise


async def _identify_products_with_fallback(
    image_b64: str,
    style: str = "",
    niche: str = "home",
    tags: list = None,
) -> list:
    """
    4-model fallback chain for product identification.
    Gemini Key1 → Gemini Key2 → Groq Vision → Cerebras Text
    """
    tags = tags or []
    
    gemini_key1 = os.getenv("GEMINI_API_KEY", "")
    gemini_key2 = os.getenv("GEMINI_API_KEY_2", "")
    
    attempts = [
        ("Gemini Key 1", lambda: _try_gemini(gemini_key1, image_b64, "Key 1")),
        ("Gemini Key 2", lambda: _try_gemini(gemini_key2, image_b64, "Key 2")),
        ("Groq Vision",  lambda: _try_groq_vision(image_b64)),
        ("Cerebras Text",lambda: _try_cerebras_text(style, niche, tags)),
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
    
    logger.error("❌ [Vision] All 4 models failed — empty product list")
    return []


async def _download_image_b64(image_url: str) -> str:
    """Download image from URL and return base64 string."""
    try:
        import httpx, base64
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(image_url)
            r.raise_for_status()
            b64 = base64.b64encode(r.content).decode("utf-8")
            logger.info(f"[Vision] Image downloaded: {len(r.content):,} bytes")
            return b64
    except Exception as e:
        logger.error(f"[Vision] Image download failed for {image_url}: {e}")
        return ""


# ── LLM Quality Filter ─────────────────────────────────────────────────────────

async def _llm_quality_filter(keyword: str, style: str, niche: str, raw_products: list) -> dict:
    """
    Use Groq LLM to quality-filter fetched products.
    Returns: {primary: {asin, reason}, approved: [...], rejected: [...]}
    """
    groq_key = os.getenv("GROQ_API_KEY")
    if not groq_key:
        logger.warning("[QualityFilter] GROQ_API_KEY not set — using basic filter fallback")
        return _basic_quality_filter(raw_products)
    
    # Build slim product list for LLM (only essential fields)
    slim = []
    for p in raw_products:
        try:
            rating = float(str(p.get("stars", p.get("rating", "0"))).split()[0])
        except Exception:
            rating = 0.0
        try:
            reviews = int(''.join(filter(str.isdigit, str(p.get("numberOfRatings", p.get("reviews", "0"))))) or 0)
        except Exception:
            reviews = 0
        
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
        products_json=json.dumps(slim, indent=2)
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
            logger.warning(f"[QualityFilter] LLM returned empty dict — using basic filter")
            return _basic_quality_filter(raw_products)
        
        primary   = result.get("primary") or {}
        approved  = result.get("approved", [])
        rejected  = result.get("rejected", [])
        
        logger.info(
            f"[QualityFilter] ✅ keyword='{keyword}' | "
            f"primary={'✅ ' + primary.get('asin','?') if primary else '❌ none'} | "
            f"approved={len(approved)} | rejected={len(rejected)}"
        )
        return result
        
    except Exception as e:
        logger.warning(f"[QualityFilter] Groq failed: {e} — using basic filter")
        return _basic_quality_filter(raw_products)


def _basic_quality_filter(raw_products: list) -> dict:
    """
    Fallback quality filter without LLM — uses rating/review thresholds only.
    """
    approved = []
    rejected = []
    
    for p in raw_products:
        asin = p.get("asin", p.get("product_id", ""))
        try:
            rating = float(str(p.get("stars", "0")).split()[0])
        except Exception:
            rating = 0.0
        try:
            reviews = int(''.join(filter(str.isdigit, str(p.get("numberOfRatings", "0")))) or 0)
        except Exception:
            reviews = 0
        
        title = p.get("productTitle", "")[:50]
        
        if rating >= 3.5 and reviews >= 50:
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

async def _normalize_product(item: dict) -> dict:
    """Convert raw RapidAPI item → normalized product dict."""
    from tools.admitad import make_affiliate_link
    
    asin  = item.get("asin", "")
    title = item.get("productTitle", item.get("product_name", "Amazon Product"))
    price = item.get("price", item.get("sale_price", "$0.00"))
    
    try:
        rating = float(str(item.get("stars", item.get("rating", "0"))).split()[0])
    except Exception:
        rating = 0.0
    try:
        reviews = int(''.join(filter(str.isdigit, str(item.get("numberOfRatings", item.get("reviews", "0"))))) or 0)
    except Exception:
        reviews = 0
    
    # Get gallery image (try, don't block on failure)
    image_url = item.get("imgUrl", "")
    try:
        from tools.aliexpress import get_rapidapi_gallery, get_best_lifestyle_image
        gallery = await get_rapidapi_gallery(asin)
        await asyncio.sleep(1)
        if gallery:
            image_url = await get_best_lifestyle_image(gallery) or image_url
    except Exception as e:
        logger.warning(f"[Normalize] Gallery fetch failed for {asin}: {e}")
    
    product_url   = f"https://www.amazon.com/dp/{asin}"
    affiliate_url = make_affiliate_link(product_url)
    
    return {
        "product_id":    asin,
        "product_name":  title[:100],
        "sale_price":    str(price),
        "rating":        rating,
        "reviews":       reviews,
        "image_url":     image_url,
        "product_url":   product_url,
        "affiliate_url": affiliate_url,
    }


# ── Main Node ──────────────────────────────────────────────────────────────────

async def node_product_researcher(state: dict) -> dict:
    """
    Node: Product Researcher
    
    New Flow:
    1. Vision AI identifies product keywords from pin image
    2. RapidAPI fetches 20 products per keyword
    3. LLM quality filters: primary (blog) + approved (sheets) + rejected (sheets)
    4. All products saved to 'Approved Deals' Google Sheet
    5. Primary products returned for blog
    """
    
    # ── Guard: skip if blog not needed ────────────────────────────────────────
    if not state.get("should_create_blog"):
        logger.info("🛍️ [ProductResearcher] Skipping — should_create_blog=False")
        return {**state, "blog_products": []}
    
    # ── Get image URL ─────────────────────────────────────────────────────────
    image_url = state.get("last_posted_image_url", "")
    if not image_url:
        logger.warning("🛍️ [ProductResearcher] No image URL in state")
        return {**state, "blog_products": []}
    
    # ── Determine account context ─────────────────────────────────────────────
    trigger  = state.get("cycle_trigger", "")
    is_acc2  = "account2" in trigger
    account  = "account_2" if is_acc2 else "account_1"
    cmo      = state.get("a2_cmo_strategy", {}) if is_acc2 else state.get("a1_cmo_strategy", {})
    style    = cmo.get("style_name", "general")
    niche    = cmo.get("niche", "home")
    tags     = cmo.get("tags", [])
    
    logger.info(
        f"🛍️ [ProductResearcher] Starting | account={account} | "
        f"style={style} | niche={niche} | image={image_url[:60]}..."
    )
    
    # ── Step 1: Download image ────────────────────────────────────────────────
    image_b64 = await _download_image_b64(image_url)
    if not image_b64:
        logger.error("🛍️ [ProductResearcher] Image download failed")
        return {**state, "blog_products": []}
    
    # ── Step 2: Vision AI → product keywords ──────────────────────────────────
    identified = await _identify_products_with_fallback(
        image_b64=image_b64,
        style=style,
        niche=niche,
        tags=tags,
    )
    
    if not identified:
        logger.error("🛍️ [ProductResearcher] Vision returned no products — blog will have no products")
        return {**state, "blog_products": []}
    
    logger.info(f"🛍️ [ProductResearcher] Vision identified {len(identified)} keywords: "
                f"{[i.get('search_keyword','?') for i in identified]}")
    
    # ── Step 3: Get sheets client ─────────────────────────────────────────────
    try:
        # Use your existing sheets client — adjust import path if needed
        from core.sheets import get_sheets_client
        sheets_client = get_sheets_client()
    except Exception as e:
        logger.warning(f"🛍️ [ProductResearcher] Sheets client failed: {e} — will skip sheets save")
        sheets_client = None
    
    # ── Step 4: For each keyword → fetch → filter → save → collect ───────────
    from tools.aliexpress import fetch_rapidapi
    from tools.sheets_product_store import save_products_batch
    
    blog_products = []
    
    for vision_item in identified[:MAX_KEYWORDS]:
        keyword = vision_item.get("search_keyword", vision_item.get("product_name", "")).strip()
        if not keyword:
            continue
        
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 [ProductResearcher] Processing keyword: '{keyword}'")
        
        # Fetch 20 raw products from RapidAPI
        try:
            raw_products = await fetch_rapidapi(keyword, max_results=MAX_PRODUCTS_FETCH)
        except Exception as e:
            logger.warning(f"⚠️ [ProductResearcher] fetch_rapidapi failed for '{keyword}': {e}")
            raw_products = None
        
        if not raw_products:
            logger.warning(f"⚠️ [ProductResearcher] No products from RapidAPI for '{keyword}' — skipping")
            continue
        
        logger.info(f"📦 [ProductResearcher] Got {len(raw_products)} raw products for '{keyword}'")
        
        # LLM quality filter
        try:
            filter_result = await _llm_quality_filter(keyword, style, niche, raw_products)
        except Exception as e:
            logger.warning(f"⚠️ [ProductResearcher] Quality filter failed: {e} — using basic filter")
            filter_result = _basic_quality_filter(raw_products)
        
        primary_info  = filter_result.get("primary") or {}
        approved_list = filter_result.get("approved", [])
        rejected_list = filter_result.get("rejected", [])
        
        primary_asin  = primary_info.get("asin", "")
        approved_asins = {primary_asin} | {a["asin"] for a in approved_list if a.get("asin")}
        
        logger.info(
            f"[ProductResearcher] Filter result: primary={primary_asin or 'NONE'} | "
            f"approved={len(approved_asins)} | rejected={len(rejected_list)}"
        )
        
        if not approved_asins or not primary_asin:
            logger.warning(f"[ProductResearcher] No products passed quality filter for '{keyword}'")
            # Still save rejected to sheets for tracking
            if sheets_client and rejected_list:
                try:
                    rejected_products = [
                        {"product_id": r["asin"], "product_name": r.get("reason", ""), 
                         "sale_price": "", "rating": "", "reviews": ""}
                        for r in rejected_list
                    ]
                    save_products_batch(
                        sheets_client=sheets_client,
                        keyword=keyword,
                        niche=niche,
                        primary_asin="",
                        approved_products=[],
                        rejected_products=rejected_products,
                    )
                except Exception as e:
                    logger.warning(f"[ProductResearcher] Sheets save (rejected only) failed: {e}")
            continue
        
        # Normalize approved products
        approved_normalized = []
        asin_to_raw = {
            p.get("asin", p.get("product_id", "")): p 
            for p in raw_products
        }
        
        for asin in approved_asins:
            if not asin:
                continue
            raw_item = asin_to_raw.get(asin)
            if not raw_item:
                continue
            try:
                normalized = await _normalize_product(raw_item)
                # Attach LLM reason
                if asin == primary_asin:
                    normalized["ai_reason"] = primary_info.get("reason", "Primary product")
                else:
                    reason = next(
                        (a["reason"] for a in approved_list if a.get("asin") == asin),
                        "Quality approved"
                    )
                    normalized["ai_reason"] = reason
                approved_normalized.append(normalized)
                await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(f"[ProductResearcher] Normalize failed for {asin}: {e}")
        
        logger.info(f"[ProductResearcher] Normalized {len(approved_normalized)} approved products")
        
        # Build rejected list for sheets
        rejected_products_for_sheets = []
        for r in rejected_list:
            raw_item = asin_to_raw.get(r.get("asin", ""), {})
            rejected_products_for_sheets.append({
                "product_id":   r.get("asin", ""),
                "product_name": raw_item.get("productTitle", "")[:80],
                "sale_price":   str(raw_item.get("price", "")),
                "rating":       str(raw_item.get("stars", "")),
                "reviews":      str(raw_item.get("numberOfRatings", "")),
            })
        
        # Save to Google Sheets
        if sheets_client:
            try:
                saved = save_products_batch(
                    sheets_client=sheets_client,
                    keyword=keyword,
                    niche=niche,
                    primary_asin=primary_asin,
                    approved_products=approved_normalized,
                    rejected_products=rejected_products_for_sheets,
                )
                logger.info(f"📊 [ProductResearcher] Sheets: {saved} rows saved for '{keyword}'")
            except Exception as e:
                logger.warning(f"⚠️ [ProductResearcher] Sheets save failed for '{keyword}': {e}")
        
        # Pick primary product for blog
        if len(blog_products) < MAX_BLOG_PRODUCTS:
            primary_product = next(
                (p for p in approved_normalized if p["product_id"] == primary_asin),
                approved_normalized[0] if approved_normalized else None
            )
            
            if primary_product:
                blog_entry = {
                    "name":              primary_product["product_name"],
                    "price":             primary_product["sale_price"],
                    "affiliate_url":     primary_product["affiliate_url"],
                    "image_url":         primary_product.get("image_url", ""),
                    "insert_after_para": int(vision_item.get("suggested_para", len(blog_products) * 2 + 1)),
                    "why_fits":          vision_item.get("why_fits", primary_product.get("ai_reason", "")),
                }
                blog_products.append(blog_entry)
                logger.info(
                    f"✅ [ProductResearcher] Blog product #{len(blog_products)}: "
                    f"'{primary_product['product_name'][:50]}' | "
                    f"asin={primary_asin} | keyword='{keyword}'"
                )
        
        await asyncio.sleep(2)  # Rate limit buffer between keywords
    
    logger.info(
        f"\n🛍️ [ProductResearcher] DONE | "
        f"blog_products={len(blog_products)} | "
        f"keywords_processed={min(len(identified), MAX_KEYWORDS)}"
    )
    
    return {**state, "blog_products": blog_products}
```

---

## 🔧 Sheets Import Fix

**In `node_product_researcher.py`, yeh import line hai:**
```python
from core.sheets import get_sheets_client
```

**Agar tera existing sheets client kisi aur jagah se aata hai, toh yeh adjust karo.**

Check karo ki tera existing code kaise sheets client get karta hai. Common patterns:

```python
# Pattern 1 — direct gspread
import gspread
from google.oauth2.service_account import Credentials

# Pattern 2 — custom module
from utils.google_sheets import get_client

# Pattern 3 — already imported globally somewhere
from config import sheets_client
```

**Jahan bhi tera `gspread` client aata hai, wahi se import karo `node_product_researcher.py` mein.**

---

## ✅ Testing Checklist (After Changes)

Replit Agent se yeh verify karwao:

```
1. [ ] tools/sheets_product_store.py file create hua
2. [ ] 'Approved Deals' sheet mein EXACT column headers match hain:
       product_name | product_id | sale_price | rating | orders | affiliate_link | image_url | keyword | niche | Status
3. [ ] _parse_json_list() function test karo with:
       - '[]' → should return []
       - '[{"a":1}]' → should return [{"a":1}]
       - '{"products":[{"a":1}]}' → should return [{"a":1}]
       - '' → should return []
4. [ ] fetch_rapidapi(keyword, max_results=20) — max_results parameter accepted
5. [ ] Manual trigger karo → logs mein check karo:
       - "Vision identified X keywords"
       - "Got 20 raw products for 'keyword'"
       - "Filter result: primary=B0XXX"
       - "Sheets: X rows saved"
       - "Blog product #1: 'Product Name'"
6. [ ] Google Sheet 'Approved Deals' mein rows appear ho rahi hain
7. [ ] Blog mein products show ho rahe hain
```

---

## 🚨 Critical Notes for Replit Agent

1. **`Approved Deals` sheet mein headers mat change karna** — existing format preserve karo
2. **`get_sheets_client()` import path** — existing codebase se match karo, guess mat karo
3. **`make_affiliate_link()` import** — `tools/admitad.py` mein hai, change mat karo
4. **`fetch_rapidapi` signature change** — sirf `max_results` parameter add karo, baki existing logic same raho
5. **`_identify_products_with_fallback` function** — vision fallback chain ka order same raho (Gemini1 → Gemini2 → Groq → Cerebras)
6. **Logging** — har step pe detailed logs rakho, debugging ke liye zaruri hai
7. **`asyncio.sleep` calls** — rate limiting ke liye important hain, remove mat karo
