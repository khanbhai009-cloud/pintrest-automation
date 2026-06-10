# Vision, Product Fetch, and Blog Flow Report

## 1. Vision / Image Analysis Function that Calls Gemini

File: `tools/visions_ai.py`

```python
def analyze_image(image_path: str) -> dict:
    """Gemini Vision ka use karke strict dynamic JSON extract karta hai."""
    prompt = """
    You are an Elite Visual Art Director and Reverse-Engineering Expert.
    Analyze the provided image and extract its complete aesthetic DNA into a strict JSON format.
    
    RULES:
    1. style_key: Create a unique snake_case name (e.g., "sunset_gaming_desk").
    2. account: If the image is Home Decor/Lifestyle/Garden, output "account_1". If it is Tech/Gaming/Desk setup, output "account_2".
    3. label: A clean, human-readable Title Case label.
    4. description: 2-3 sentences of rich, sensory description. Describe the mood, colors, and key elements.
    5. t2i_base: A highly detailed text-to-image prompt. Include specific objects, textures, and compositional technique. 
       CRITICAL ENDING: Do NOT use a hardcoded ending. You must dynamically analyze the exact photographic style, lighting finish, or rendering aesthetic of the specific image and end the prompt with 3-4 comma-separated descriptive tags. 
       (Examples: "warm twilight lighting, cozy amber glow, soft indoor lifestyle photography" OR "hyper-detailed digital art, vivid saturated colors, majestic sunset lighting, unreal engine 5 style".)
    6. niche_affinity: Comma-separated niches (e.g., "home, cozy" or "tech, gadgets").
    7. tags: Exactly 5 CamelCase tags, comma-separated (e.g., "AestheticRoom, CozyVibes").
    
    Output ONLY a valid JSON object matching this exact structure.
    """
    
    # Primary try, fallback on error
    for attempt, active_client in enumerate([_primary_client, _fallback_client]):
        if not active_client:
            continue
        label = "PRIMARY" if attempt == 0 else "FALLBACK"
        try:
            logging.info(f"🔑 Using {label} Gemini API key...")
            myfile = active_client.files.upload(file=image_path)
            response = active_client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt, myfile],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.7
                )
            )
            active_client.files.delete(name=myfile.name)
            return json.loads(response.text.strip())
        except Exception as e:
            logging.warning(f"⚠️ {label} key failed: {e}")
            if attempt == 1:
                raise
    raise RuntimeError("Both Gemini API keys failed.")
```

### Notes
- This function uploads the image to Gemini, generates JSON output with `gemini-2.5-flash`, and parses `response.text` into JSON.
- A fallback key is used on the second attempt via `_fallback_client`.

## 2. Vision Response Parsing into Product List and Fallback Logic

File: `mastermind/node_product_researcher.py`

```python
def _parse_json(raw: str) -> list:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("[")
    end   = cleaned.rfind("]") + 1
    if start == -1 or end == 0:
        return []
    return json.loads(cleaned[start:end])
```

```python
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
```

```python
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

    # ... determine strategy, style, niche, tags ...

    image_b64 = await _download_image_b64(image_url)
    if not image_b64:
        return {**state, "blog_products": []}

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
```

### Notes
- The product list can become empty at multiple points:
  - `last_posted_image_url` is missing.
  - image download fails in `_download_image_b64`.
  - `_identify_products_with_fallback` returns an empty list.
  - the downstream `search_products` call returns `[]`.
  - no results pass the quality filter.

## 3. RapidAPI Fetch Function with Key Rotation Logic

File: `tools/aliexpress.py`

```python
async def _rapidapi_request(keyword: str, api_key: str, key_label: str):
    """Single RapidAPI attempt with the given key. Returns products list or None."""
    headers = {
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": api_key,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(timeout=30, http2=True) as client:
            r = await client.get(SEARCH_URL, headers=headers, params={
                "domainCode": "com",
                "keyword": keyword,
                "page": "1",
                "excludeSponsored": "false",
                "sortBy": "relevanceblender",
                "withCache": "true"
            })
            if r.status_code == 503:
                logger.error(
                    f"❌ RapidAPI 503 [{key_label}] — possible Cloudflare block. "
                    f"Response body:\n{r.text[:2000]}"
                )
                return None
            if r.status_code != 200:
                logger.warning(f"⚠️ RapidAPI [{key_label}] returned {r.status_code}: {r.text[:300]}")
                return None
            products = r.json().get("searchProductDetails", [])
            return products if isinstance(products, list) else None
    except Exception as e:
        logger.warning(f"⚠️ RapidAPI [{key_label}] exception: {e}")
        return None
```

```python
async def fetch_rapidapi(keyword):
    """RapidAPI Search with automatic key rotation (KEY1 → KEY2 on any failure)."""
    # ── Key 1 (primary) ──
    if RAPIDAPI_KEY:
        result = await _rapidapi_request(keyword, RAPIDAPI_KEY, "KEY1")
        if result is not None:
            return result
        logger.warning("🔄 RapidAPI KEY1 failed — rotating to KEY2...")
    else:
        logger.warning("⚠️ RAPIDAPI_KEY not set — skipping KEY1")

    # ── Key 2 (fallback) ──
    if RAPIDAPI_KEY2:
        result = await _rapidapi_request(keyword, RAPIDAPI_KEY2, "KEY2")
        if result is not None:
            logger.info("✅ RapidAPI KEY2 succeeded.")
        return result

    logger.error("❌ No RapidAPI keys available or both failed.")
    return None
```

### Notes
- If KEY1 returns 403 or any non-200 error, the logic rotates to KEY2.
- If KEY2 returns 200, the response is parsed from `searchProductDetails`.

## 4. API Response Parsing into Product Objects

File: `tools/aliexpress.py`

```python
async def search_products(keyword: str = "", niche: str = "", max_results: int = 5) -> list:
    # Try RapidAPI first (with key rotation inside)
    raw_products = await fetch_rapidapi(keyword)
    normalized = []

    if raw_products:
        logger.info("✅ Using RapidAPI (Axesso) results.")
        for idx, item in enumerate(raw_products[:max_results]):
            # Quality Shield
            try:
                rating = float(str(item.get("stars", "0")).split()[0])
            except Exception:
                rating = 0.0
            try:
                reviews = int(''.join(filter(str.isdigit, str(item.get("numberOfRatings", "0")))) or 0)
            except Exception:
                reviews = 0

            if rating < 3.5 or reviews < 50:
                continue

            asin  = item.get("asin")
            title = item.get("productTitle", "Amazon Product")
            price = item.get("price", "$0.00")

            # Image via details endpoint
            gallery = await get_rapidapi_gallery(asin)
            await asyncio.sleep(2)

            best_img = await get_best_lifestyle_image(gallery) if gallery else item.get("imgUrl", "")

            normalized.append({
                "product_id": asin,
                "product_name": title[:100],
                "sale_price": str(price),
                "rating": rating,
                "image_url": best_img,
                "product_url": f"https://www.amazon.com/dp/{asin}"
            })
            await asyncio.sleep(5)

        return normalized

    # RapidAPI failed — Apify fallback
    logger.warning(f"⚠️ RapidAPI returned nothing for keyword: '{keyword}' — switching to Apify fallback.")
    apify_data = await fetch_apify(keyword, max_results)
    if not apify_data:
        logger.error("❌ Apify also failed or returned no data.")
        return []

    logger.info("🛡️ Using Apify results.")
    for item in apify_data[:max_results]:
        # ... fallback normalization ...
```
```

### Product object structure from RapidAPI

RapidAPI normalized product objects use keys:
- `product_id`
- `product_name`
- `sale_price`
- `rating`
- `image_url`
- `product_url`

### Why product count may stay zero

The `search_products()` function filters RapidAPI results with:

```python
if rating < 3.5 or reviews < 50:
    continue
```

If every item fails that quality filter, `normalized` remains empty even though the API returned 200.

## 5. How Products Are Stored / Passed to the Next Step

File: `mastermind/node_product_researcher.py`

```python
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
```
```

### Blog product object structure

The blog pipeline stores products as:
- `name`
- `price`
- `affiliate_url`
- `insert_after_para`
- `why_fits`

This is the shape used in `state["blog_products"]`.

## 6. How Products Are Passed from the Pinterest Pin Flow to the Blog Generator

File: `agent.py`

```python
async def _run_inline_blog(imgbb_url: str, cmo: dict, trigger: str) -> str:
    """
    Run the 4-node blog pipeline INLINE — before the Pinterest post.

    Flow: node_blog_trigger → node_product_researcher → node_blog_writer
          → node_firebase_publisher → returns blog_url or ""
    """
    import os
    if not os.getenv("FIREBASE_CREDS_JSON"):
        return ""

    try:
        from mastermind.node_blog_trigger import node_blog_trigger
        from mastermind.node_product_researcher import node_product_researcher
        from mastermind.node_blog_writer import node_blog_writer
        from mastermind.node_firebase_publisher import node_firebase_publisher

        acct = "account2" if "account2" in trigger else "account1"

        state: dict = {
            "last_posted_image_url": imgbb_url,
            "cycle_trigger":         trigger,
            "a1_cmo_strategy":       cmo if acct == "account1" else {},
            "a2_cmo_strategy":       cmo if acct == "account2" else {},
            "should_create_blog":    False,
            "blog_products":         [],
            "blog_content":          {},
            "blog_url":              "",
            "blog_published":        False,
            # ... additional schema fields ...
        }

        state = await node_blog_trigger(state)
        if not state.get("should_create_blog"):
            logger.info("📝 [InlineBlog] Skipped — trigger check failed")
            return ""

        state = await node_product_researcher(state)
        state = await node_blog_writer(state)
        state = await node_firebase_publisher(state)

        blog_url = state.get("blog_url", "")
        if blog_url:
            logger.info(f"📝 [InlineBlog] Published: {blog_url}")
        return blog_url

    except Exception as e:
        logger.error(f"❌ [InlineBlog] Failed (pin will still post): {e}")
        return ""
```

### `publish_next_pin` flow

```python
if blog_enabled:
    blog_url = await _run_inline_blog(imgbb_url=imgbb_url, cmo=cmo, trigger=trigger)
else:
    blog_url = ""
```

Then the Pinterest post is created with:
- `blog_url=blog_url`
- `image_url=imgbb_url`
- `title`, `description`, `tags`, `board_id`, `board_name`

## 7. Blog Generation Function

File: `mastermind/node_blog_writer.py`

```python
async def node_blog_writer(state: dict) -> dict:
    if not state.get("should_create_blog"):
        logger.info("✍️ [BlogWriter] Skipping — should_create_blog=False")
        return {**state, "blog_content": {}}

    trigger = state.get("cycle_trigger", "")
    if "account2" in trigger and "account1" not in trigger:
        strategy = state.get("a2_cmo_strategy", {})
        account  = "Account2_Tech"
    else:
        strategy = state.get("a1_cmo_strategy", {})
        account  = "Account1_HomeDecor"

    products  = state.get("blog_products", [])
    image_url = state.get("last_posted_image_url", "")

    prompt = _build_writer_prompt(strategy, products, image_url)

    blog_content = await _write_blog_with_fallback(prompt)

    if not blog_content:
        return {**state, "blog_content": {}}

    if blog_content.get("title") and not blog_content.get("slug"):
        blog_content["slug"] = _slugify(blog_content["title"])

    blog_content["account"] = account

    niche, sub_niche = _infer_niche(
        blog_content.get("style_name", strategy.get("style_name", "")),
        blog_content.get("title", ""),
    )
    if not blog_content.get("niche"):
        blog_content["niche"] = niche
    if not blog_content.get("sub_niche"):
        blog_content["sub_niche"] = sub_niche
    if not blog_content.get("collection_tag"):
        blog_content["collection_tag"] = f"{blog_content['niche']}/{blog_content['sub_niche']}"

    logger.info(f"✍️ Blog written: '{blog_content.get('title', '?')}' ({len(blog_content.get('paragraphs', []))} paragraphs)")

    return {**state, "blog_content": blog_content}
```
```

### Prompt build and product embedding

```python
if products:
    lines = [
        f"  Product {i}: {p['name']} — {p.get('price','?')} "
        f"(insert after para {p.get('insert_after_para', i*2)}): {p.get('why_fits','')}"
        for i, p in enumerate(products, 1)
    ]
    products_brief = "\n".join(lines)
else:
    products_brief = "  No specific products — write general lifestyle content."
```

The prompt instructs Gemini to "naturally weave in the products listed above near their suggested insert point." The actual embedding is produced by Gemini-generated JSON paragraphs.

## 8. How Products Are Embedded / Rendered in Blog HTML / Markdown

The current application writes raw blog JSON and saves it to Firebase. The product list is stored as a separate field in the saved blog document.

File: `mastermind/node_firebase_publisher.py`

```python
blog_data = dict(blog_content)
blog_data["products"]   = state.get("blog_products", [])
blog_data["image_url"]  = state.get("last_posted_image_url", blog_data.get("image_url", ""))

blog_url = await save_blog_post(blog_data)
```
```

File: `tools/firebase_publisher.py`

```python
doc_data = {
    "slug":            slug,
    "title":           blog_data.get("title", ""),
    "seo_title":       blog_data.get("seo_title", ""),
    "meta_desc":       blog_data.get("meta_description", ""),
    "excerpt":         blog_data.get("excerpt", ""),
    "niche":           niche,
    "sub_niche":       sub_niche,
    "style_name":      blog_data.get("style_name", ""),
    "collection_tag":  blog_data.get("collection_tag", f"{niche}/{sub_niche}"),
    "image_url":       blog_data.get("image_url", ""),
    "pinterest_url":   blog_data.get("pinterest_url", ""),
    "paragraphs":      blog_data.get("paragraphs", []),
    "products":        blog_data.get("products", []),
    "faq":             blog_data.get("faq", []),
    "tags":            blog_data.get("tags", []),
    "primary_keyword": blog_data.get("primary_keyword", ""),
    "status":          "published",
    "views":           0,
    "account":         blog_data.get("account", ""),
    "created_at":      _fs.SERVER_TIMESTAMP,
    "updated_at":      _fs.SERVER_TIMESTAMP,
}
```

### Notes
- The actual blog text content is stored in `paragraphs` inside `blog_content`.
- Products are saved as `products` in Firestore, not directly injected into HTML by this code path.

## 9. Conditional Logic that Might Skip Products

### Skip points in blog pipeline
- `node_blog_trigger` can set `should_create_blog` to `False`, which stops product research and blog writing.
- `node_product_researcher` returns `blog_products=[]` if:
  - `should_create_blog` is false
  - `last_posted_image_url` is missing
  - image download fails
  - vision identification returns an empty list
  - product search returns no results
- `node_blog_writer` can skip if `blog_content` is empty after generation.
- `node_firebase_publisher` can skip saving if `blog_content` is empty.

## 10. Complete Data Flow Trace (Image → Product Fetcher → Blog)

### Step A: Pin creation / image generation
- `publish_next_pin(visual_style)` in `agent.py`
- Generates `imgbb_url` with `generate_pin_image(...)`
- Calls `_run_inline_blog(imgbb_url=imgbb_url, cmo=cmo, trigger=trigger)` if `BLOG_ENABLED=true`

### Step B: Inline blog pipeline state object
- `state["last_posted_image_url"]` = `imgbb_url`
- `state["cycle_trigger"]` = `trigger`
- `state["a1_cmo_strategy"]` / `state["a2_cmo_strategy"]` = `cmo`
- `state["should_create_blog"]` starts as `False`
- `state["blog_products"]` starts as `[]`
- `state["blog_content"]` starts as `{}`

### Step C: Trigger decision
- `node_blog_trigger(state)` updates:
  - `should_create_blog` = `True` or `False`

### Step D: Vision product identification
- `node_product_researcher(state)` reads:
  - `last_posted_image_url`
  - `cycle_trigger`
  - `a1_cmo_strategy` / `a2_cmo_strategy`
- It builds `image_b64` and calls `_identify_products_with_fallback(...)`
- Fallback chain uses:
  - `Gemini Key 1` via `GEMINI_API_KEY`
  - `Gemini Key 2` via `GEMINI_API_KEY_2`
  - `Groq Vision` via `GROQ_API_KEY`
  - `Cerebras Text` via `CEREBRAS_API_KEY`
- Output is parsed into a JSON list by `_parse_json(raw)`
- If empty, `blog_products` remains `[]`

### Step E: Product search
- For each identified vision product, `search_products(keyword, max_results=1, niche=niche)` is called
- It uses `fetch_rapidapi(keyword)` which rotates keys:
  - tries `RAPIDAPI_KEY` first
  - then `RAPIDAPI_KEY2` if KEY1 fails
- It parses `searchProductDetails` into `normalized` product objects
- It applies the filter:
  - `rating < 3.5` or `reviews < 50` are skipped
- If no normalized items survive, `search_products()` returns `[]`

### Step F: Blog product assembly
- `node_product_researcher` converts the chosen product into:
  - `name`
  - `price`
  - `affiliate_url`
  - `insert_after_para`
  - `why_fits`
- Assigned to `state["blog_products"]`

### Step G: Blog generation
- `node_blog_writer` reads:
  - `state["blog_products"]`
  - `state["last_posted_image_url"]`
  - `state["cycle_trigger"]`
  - `state["a1_cmo_strategy"]` / `state["a2_cmo_strategy"]`
- Builds a prompt with `_build_writer_prompt(strategy, products, image_url)`
- Calls `_write_blog_with_fallback(prompt)` to generate `blog_content`
- Final `blog_content` keys include `title`, `slug`, `paragraphs`, `faq`, `tags`, `niche`, `sub_niche`, `collection_tag`, etc.

### Step H: Save blog post
- `node_firebase_publisher(state)` merges:
  - `blog_content`
  - `blog_products`
  - `last_posted_image_url`
- Writes `blog_data["products"]` to Firestore in `tools/firebase_publisher.py`

### Key loss points for product list
- If `node_blog_trigger` returns `should_create_blog=False`
- If `_download_image_b64()` fails
- If `_identify_products_with_fallback()` returns `[]`
- If `search_products()` returns `[]` for every vision item
- If `node_blog_writer()` fails to generate blog content
- If Firebase save fails, `blog_url` remains empty

## 11. GitHub Push
- Created: `VISION_PRODUCT_BLOG_FLOW.md`
- Branch: `main`
- This report is now committed and pushed to GitHub.
