import httpx
import logging
import random
from config import RAPIDAPI_KEY

logger   = logging.getLogger(__name__)

# RapidAPI Endpoint for Amazon Search
BASE_URL = "https://real-time-amazon-data.p.rapidapi.com/search"
HEADERS  = {
    "x-rapidapi-host": "real-time-amazon-data.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}

# ── Niche-Based Keywords (Amazon Friendly) ────────────────────────────────────
KEYWORDS_BY_NICHE = {
    "home": [
        "aesthetic room decor", "amazon home finds", "nordic home decor",
        "led room lighting aesthetic", "minimalist home accessories", "cute room decor"
    ],
    "kitchen": [
        "smart kitchen gadgets", "viral kitchen tools", "aesthetic kitchen accessories",
        "time saving kitchen hacks", "kitchen organization tools", "pastel kitchen gadgets"
    ],
    "cozy": [
        "cozy bedroom aesthetic", "warm night light", "fluffy room decor",
        "reading nook accessories", "ambient room lighting", "kawaii room decor"
    ],
    "gadgets": [
        "cool home gadgets viral", "problem solving gadgets", "smart home tech finds",
        "tiktok made me buy it home", "lazy home gadgets", "cleaning gadgets hacks"
    ],
    "organize": [
        "aesthetic storage box", "acrylic makeup organizer", "closet organization tools",
        "cable management aesthetic", "bathroom space saver", "fridge organization containers"
    ],
    "tech": [
        "aesthetic desk setup", "gaming setup accessories", "cool tech gadgets",
        "cyberpunk desk accessories", "futuristic tech gadgets", "laptop accessories aesthetic"
    ],
    "budget": [
        "cool gadgets under 10", "cheap tech finds", "useful gadgets under 20",
        "mini tech gadgets", "budget gaming accessories", "pocket gadgets"
    ],
    "phone": [
        "cute iphone cases", "magsafe accessories aesthetic", "viral phone charms",
        "phone camera lens kit", "aesthetic phone stand", "power bank aesthetic"
    ],
    "smarthome": [
        "smart rgb led strip", "smart home automation", "voice control lights",
        "smart desk lamp", "galaxy projector light", "smart sensor gadgets"
    ],
    "wfh": [
        "work from home desk setup", "ergonomic desk accessories", "ipad accessories aesthetic",
        "productivity gadgets", "wireless mechanical keyboard", "desk mat aesthetic"
    ]
}

DEFAULT_KEYWORDS = ["tiktok viral finds", "aesthetic must haves", "cool gadgets"]

async def search_products(
    keyword: str     = "",
    page: int        = 1,
    max_results: int = 20,
    niche: str       = ""
) -> list:
    try:
        if not keyword and niche:
            keyword = random.choice(KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS))

        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                BASE_URL,
                headers=HEADERS,
                params={
                    "query": keyword,
                    "page": str(page),
                    "country": "US",         # US traffic only
                    "sort_by": "REVIEWS_DESC" 
                },
            )
        r.raise_for_status()
        data = r.json()

        logger.info(f"🔍 Raw keys from Amazon API: {list(data.keys())}")

        raw = (
            data.get("data", {}).get("products") or
            data.get("products") or
            data.get("results") or
            []
        )

        if not raw:
            logger.warning(f"⚠️ No items found for {keyword}.")
            return []

        normalized = []
        for item in raw[:max_results]:
            asin = item.get("asin") or item.get("product_id")
            if not asin:
                continue

            title = item.get("product_title") or item.get("title") or "Amazon Find"
            image_url = item.get("product_photo") or item.get("image") or ""
            price_str = str(item.get("product_price") or item.get("price") or "$0.00")

            normalized.append({
                "product_id":   asin,
                "product_name": str(title)[:120],
                "sale_price":   price_str,
                "orders":       str(item.get("product_num_ratings") or item.get("review_count") or "0"),
                "rating":       item.get("product_star_rating") or item.get("rating") or 0,
                "image_url":    image_url,
                "product_url":  f"https://www.amazon.com/dp/{asin}", 
                "keyword":      keyword,
                "niche":        niche,
            })

        logger.info(f"✅ Amazon '{keyword}': {len(normalized)} products fetched")
        return normalized

    except Exception as e:
        logger.error(f"❌ Amazon API error: {e}")
        return []
