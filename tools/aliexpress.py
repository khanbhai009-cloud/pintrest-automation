import httpx
import logging
from config import RAPIDAPI_KEY

logger   = logging.getLogger(__name__)
BASE_URL = "https://aliexpress-datahub.p.rapidapi.com"
HEADERS  = {
    "x-rapidapi-host": "aliexpress-datahub.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}

# ── Niche-Based Keywords ────────────────────────────────────
KEYWORDS_BY_NICHE = {
    "home": [
        "home gadgets 2025",
        "kitchen tools viral",
        "led strip lights",
        "desk accessories aesthetic",
        "smart home devices",
        "home organization",
        "room decor gadgets",
        "kitchen gadgets under 20",
    ],
    "tech": [
        "phone accessories 2025",
        "portable charger",
        "smart watch budget",
        "wireless earbuds",
        "phone camera lens",
        "usb gadgets",
        "laptop accessories",
        "mini projector",
    ],
    "fashion": [
        "aesthetic accessories",
        "minimalist jewelry",
        "hair accessories viral",
        "trendy bags",
        "sunglasses 2025",
        "fashion accessories women",
    ],
    "fitness": [
        "fitness equipment home",
        "gym accessories",
        "portable massager",
        "resistance bands",
        "workout gadgets",
        "yoga accessories",
    ],
    "beauty": [
        "beauty products viral",
        "skincare tools",
        "face massager",
        "nail art kit",
        "makeup organizer",
        "gua sha stone",
    ],
}

# Flat list — backward compatible
DEFAULT_KEYWORDS = [kw for kws in KEYWORDS_BY_NICHE.values() for kw in kws]


async def search_products(
    keyword: str    = "",
    page: int       = 1,
    max_results: int = 20,
    niche: str      = ""
) -> list:
    try:
        # Auto-select keyword from niche if not provided
        if not keyword and niche:
            import random
            keyword = random.choice(KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS))

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{BASE_URL}/item_search_2",
                headers=HEADERS,
                params={
                    "q":    keyword,
                    "page": str(page),
                    "sort": "LAST_VOLUME_DESC",  # Trending / Most orders
                },
            )
        r.raise_for_status()
        data = r.json()

        logger.info(f"🔍 Raw keys: {list(data.keys())}")

        raw = (
            data.get("result", {}).get("resultList") or
            data.get("result", {}).get("items")      or
            data.get("data",   {}).get("products")   or
            data.get("items")    or
            data.get("products") or
            []
        )

        if not raw:
            logger.warning(f"⚠️ No items. Response: {str(data)[:300]}")
            return []

        normalized = []
        for item in raw[:max_results]:
            info = item.get("item", item)
            pid  = str(
                info.get("itemId")    or
                info.get("item_id")   or
                info.get("productId") or ""
            )
            if not pid:
                continue

            sku        = info.get("sku", {})
            price_info = sku.get("def", {}) if isinstance(sku, dict) else {}
            sale_price = (
                price_info.get("promotionPrice") or
                price_info.get("price")          or
                info.get("salePrice")            or
                info.get("price")                or 0
            )

            images    = info.get("images") or []
            image_url = images[0] if images else (
                info.get("image") or info.get("imageUrl") or ""
            )
            if image_url and not str(image_url).startswith("http"):
                image_url = f"https:{image_url}"

            title = (
                info.get("title")        or
                info.get("name")         or
                info.get("productTitle") or
                "AliExpress Product"
            )

            normalized.append({
                "product_id":   pid,
                "product_name": str(title)[:120],
                "sale_price":   sale_price,
                "orders":       info.get("sales") or info.get("orders") or "0",
                "rating":       info.get("averageStar") or info.get("starRating") or 0,
                "image_url":    image_url,
                "product_url":  f"https://www.aliexpress.com/item/{pid}.html",
                "keyword":      keyword,
                "niche":        niche,  # Niche saved for sheet + routing
            })

        logger.info(f"✅ AliExpress '{keyword}': {len(normalized)} products")
        return normalized

    except Exception as e:
        logger.error(f"❌ AliExpress error: {e}")
        return []
