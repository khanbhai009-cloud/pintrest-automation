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
    # 🏠 ACCOUNT 1 BOARDS (Home Decor & Lifestyle)
    "home": [
        "aesthetic room decor",
        "amazon home finds 2026",
        "nordic home decor",
        "led room lighting aesthetic",
        "minimalist home accessories",
        "cute room decor viral"
    ],
    "kitchen": [
        "smart kitchen gadgets",
        "viral kitchen tools",
        "aesthetic kitchen accessories",
        "time saving kitchen hacks",
        "kitchen organization tools",
        "pastel kitchen gadgets"
    ],
    "cozy": [
        "cozy bedroom aesthetic",
        "warm night light",
        "fluffy room decor",
        "reading nook accessories",
        "ambient room lighting",
        "kawaii room decor"
    ],
    "gadgets": [
        "cool home gadgets viral",
        "problem solving gadgets",
        "smart home tech finds",
        "tiktok made me buy it home",
        "lazy home gadgets",
        "cleaning gadgets hacks"
    ],
    "organize": [
        "aesthetic storage box",
        "acrylic makeup organizer",
        "closet organization tools",
        "cable management aesthetic",
        "bathroom space saver",
        "fridge organization containers"
    ],

    # 💻 ACCOUNT 2 BOARDS (Tech & Gadgets)
    "tech": [
        "aesthetic desk setup",
        "gaming setup accessories",
        "cool tech gadgets 2026",
        "cyberpunk desk accessories",
        "futuristic tech gadgets",
        "laptop accessories aesthetic"
    ],
    "budget": [
        "cool gadgets under 10",
        "cheap tech finds",
        "useful gadgets under 20",
        "mini tech gadgets",
        "budget gaming accessories",
        "pocket gadgets"
    ],
    "phone": [
        "cute iphone cases",
        "magsafe accessories aesthetic",
        "viral phone charms",
        "phone camera lens kit",
        "aesthetic phone stand",
        "power bank aesthetic"
    ],
    "smarthome": [
        "smart rgb led strip",
        "smart home automation",
        "voice control lights",
        "smart desk lamp",
        "galaxy projector light",
        "smart sensor gadgets"
    ],
    "wfh": [
        "work from home desk setup",
        "ergonomic desk accessories",
        "ipad accessories aesthetic",
        "productivity gadgets",
        "wireless mechanical keyboard",
        "desk mat aesthetic"
    ]
}

# Master Fallback List (Agar koi error aaye)
DEFAULT_KEYWORDS = [
    "tiktok viral finds 2026", 
    "aesthetic must haves", 
    "cool gadgets 2026"
]

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
