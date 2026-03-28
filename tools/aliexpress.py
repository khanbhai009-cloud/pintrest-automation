import httpx
import logging
import random
from config import RAPIDAPI_KEY

logger   = logging.getLogger(__name__)

BASE_URL = "https://real-time-amazon-data.p.rapidapi.com/search"
HEADERS  = {
    "x-rapidapi-host": "real-time-amazon-data.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}

# Niche-Based Keywords
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
            # Exact parameters jo tune test kiye hain
            params = {
                "query": keyword, # API check: use 'query' as per your successful test
                "page": str(page),
                "country": "US",
                "sort_by": "RELEVANCE",
                "language": "en_US"
            }
            
            r = await client.get(BASE_URL, headers=HEADERS, params=params)
        
        r.raise_for_status()
        data = r.json()

        # Data mapping according to your successful JSON response
        raw = data.get("data", {}).get("products", [])

        if not raw:
            logger.warning(f"⚠️ No products found in API response for: {keyword}")
            return []

        normalized = []
        for item in raw[:max_results]:
            asin = item.get("asin")
            if not asin:
                continue

            # Keys updated to match your exact JSON output
            title = item.get("product_title", "Amazon Product")
            image_url = item.get("product_photo", "")
            price = item.get("product_price", "$0.00")
            rating = item.get("product_star_rating", 0)
            reviews = item.get("product_num_ratings", 0)

            normalized.append({
                "product_id":   asin,
                "product_name": str(title)[:120],
                "sale_price":   str(price),
                "orders":       str(reviews), # Amazon provides num_ratings
                "rating":       rating,
                "image_url":    image_url,
                "product_url":  f"https://www.amazon.com/dp/{asin}",
                "keyword":      keyword,
                "niche":        niche,
            })

        logger.info(f"✅ Amazon Success! '{keyword}': {len(normalized)} items fetched.")
        return normalized

    except Exception as e:
        logger.error(f"❌ Amazon Scraper Error: {e}")
        return []
