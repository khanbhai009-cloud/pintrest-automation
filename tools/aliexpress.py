import asyncio
import httpx
import logging
import random
from config import RAPIDAPI_KEY, GROQ_API_KEY, GROQ_VISION_MODEL

logger = logging.getLogger(__name__)

SEARCH_URL  = "https://real-time-amazon-data.p.rapidapi.com/search"
DETAILS_URL = "https://real-time-amazon-data.p.rapidapi.com/product-details"

HEADERS = {
    "x-rapidapi-host": "real-time-amazon-data.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}

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

# ── Rate limiting for Groq Vision API ────────────────────────────────────────
# Groq vision model free tier: 30 RPM, 7,000 tokens/min
# Strategy: 5s gap between consecutive calls + exponential backoff on 429
_VISION_INTER_CALL_DELAY = 5    # seconds between products (safe = 12 calls/min max)
_VISION_RETRY_DELAYS     = [12, 24, 48]  # seconds to wait on successive 429s


async def get_product_photos(asin: str) -> list:
    """ASIN ka use karke product ki saari images fetch karta hai."""
    logger.info(f"🔍 Fetching photo gallery for ASIN: {asin}...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(DETAILS_URL, headers=HEADERS, params={"asin": asin, "country": "US"})
            r.raise_for_status()
            return r.json().get("data", {}).get("product_photos", [])
    except Exception as e:
        logger.error(f"❌ Failed to get details for {asin}: {e}")
        return []


async def get_best_lifestyle_image(image_urls: list) -> str:
    """
    Groq Vision LLM ko use karke sabse aesthetic Pinterest-worthy image select karta hai.
    Rate limiting: exponential backoff on 429 — retries up to 3 times.
    """
    if not image_urls:
        return ""
    if len(image_urls) == 1:
        return image_urls[0]

    logger.info("👁️ [Vision Agent] Analyzing images for best Pinterest vibe...")

    content_payload = [
        {
            "type": "text",
            "text": (
                "You are an expert Pinterest aesthetic curator. Review these product images. "
                "Select the ONE image that is most 'lifestyle' oriented (e.g., product in a real "
                "room setting, aesthetic background, warm lighting). "
                "DO NOT pick plain white background images or images with heavy text/dimensions. "
                "Output ONLY the exact URL of the best image. No extra words."
            )
        }
    ]
    for url in image_urls[:5]:
        content_payload.append({"type": "image_url", "image_url": {"url": url}})

    payload = {
        "model": GROQ_VISION_MODEL,
        "messages": [{"role": "user", "content": content_payload}],
        "temperature": 0.1,
        "max_tokens": 100
    }
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}

    for attempt, wait_sec in enumerate([0] + _VISION_RETRY_DELAYS):
        if wait_sec > 0:
            logger.warning(f"⏳ [Vision Agent] 429 — sleeping {wait_sec}s before retry {attempt}/{len(_VISION_RETRY_DELAYS)}...")
            await asyncio.sleep(wait_sec)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers=headers, json=payload
                )

            if response.status_code == 429:
                logger.warning(f"⚠️ [Vision Agent] Groq 429 on attempt {attempt + 1}")
                continue

            response.raise_for_status()
            best_url = response.json()["choices"][0]["message"]["content"].strip()

            if best_url.startswith("http"):
                logger.info("✅ [Vision Agent] Best aesthetic image selected!")
                return best_url
            else:
                logger.warning("⚠️ [Vision Agent] LLM returned non-URL. Falling back to first image.")
                return image_urls[0]

        except Exception as e:
            logger.error(f"❌ [Vision Agent] Attempt {attempt + 1} failed: {e}")
            if attempt == len(_VISION_RETRY_DELAYS):
                break

    logger.warning("⚠️ [Vision Agent] All retries exhausted — using first image as fallback.")
    return image_urls[0]


async def search_products(keyword: str = "", page: int = 1, max_results: int = 5, niche: str = "") -> list:
    """
    Main function: search Amazon → fetch product details → Vision filter for best image.
    Rate limiting: _VISION_INTER_CALL_DELAY seconds between consecutive Vision API calls.
    """
    try:
        if not keyword and niche:
            keyword = random.choice(KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS))

        logger.info(f"🛒 Searching Amazon for: '{keyword}'...")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(SEARCH_URL, headers=HEADERS, params={
                "query": keyword, "page": str(page),
                "country": "US", "sort_by": "RELEVANCE", "language": "en_US"
            })
        r.raise_for_status()
        raw = r.json().get("data", {}).get("products", [])

        if not raw:
            logger.warning(f"⚠️ No products found for: {keyword}")
            return []

        normalized = []
        for idx, item in enumerate(raw[:max_results]):
            asin = item.get("asin")
            if not asin:
                continue

            # ── Rate limit guard: wait between Vision calls ────────────────
            if idx > 0:
                logger.info(f"⏱️ [Rate Limit] Sleeping {_VISION_INTER_CALL_DELAY}s before next Vision call...")
                await asyncio.sleep(_VISION_INTER_CALL_DELAY)

            title         = item.get("product_title", "Amazon Product")
            price         = item.get("product_price", "$0.00")
            rating        = item.get("product_star_rating", 0)
            reviews       = item.get("product_num_ratings", 0)
            default_image = item.get("product_photo", "")

            photo_gallery = await get_product_photos(asin)
            if not photo_gallery:
                photo_gallery = [default_image] if default_image else []

            best_aesthetic_image = await get_best_lifestyle_image(photo_gallery)

            normalized.append({
                "product_id":   asin,
                "product_name": str(title)[:120],
                "sale_price":   str(price),
                "orders":       str(reviews),
                "rating":       rating,
                "image_url":    best_aesthetic_image,
                "product_url":  f"https://www.amazon.com/dp/{asin}",
                "keyword":      keyword,
                "niche":        niche,
            })

        logger.info(f"✅ Fetch complete! '{keyword}': {len(normalized)} aesthetic items ready.")
        return normalized

    except Exception as e:
        logger.error(f"❌ Amazon Scraper Error: {e}")
        return []
