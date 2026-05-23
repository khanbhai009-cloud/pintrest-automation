import os
import asyncio
import httpx
import logging
import random
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

# ── CONFIG ──
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
APIFY_API_KEY = os.getenv("APIFY_API_KEY")
APIFY_ACTOR_ID = os.getenv("APIFY_ACTOR_ID")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

GROQ_MODEL = "llama-3.2-11b-vision-preview"
GITHUB_MODEL = "Llama-3.2-11B-Vision-Instruct"

# ── ENDPOINTS ──
# SEARCH_URL aur HOST dono fix karo
SEARCH_URL   = "https://real-time-amazon-data.p.rapidapi.com/search"
DETAILS_URL  = "https://real-time-amazon-data.p.rapidapi.com/product-details"
RAPIDAPI_HOST = "real-time-amazon-data.p.rapidapi.com"


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

# ── VISION AI: BEST IMAGE SELECTOR ──
async def get_best_lifestyle_image(image_urls: list) -> str:
    if not image_urls: return ""
    if len(image_urls) == 1: return image_urls[0]

    safe_images = image_urls[1:6] if len(image_urls) > 1 else image_urls
    content_payload = [{"type": "text", "text": "Pick the ONE lifestyle image (real room/aesthetic). Output ONLY the URL."}]
    for url in safe_images: content_payload.append({"type": "image_url", "image_url": {"url": url}})

    # Try Groq First
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post("https://api.groq.com/openai/v1/chat/completions", 
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": content_payload}], "temperature": 0.1})
            best_url = res.json()["choices"][0]["message"]["content"].strip().strip('"').strip("'")
            if any(img in best_url for img in safe_images): return best_url
    except: logger.warning("🔄 Groq Vision failed, trying GitHub...")

    # Fallback to GitHub
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post("https://models.inference.ai.azure.com/chat/completions",
                headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
                json={"model": GITHUB_MODEL, "messages": [{"role": "user", "content": content_payload}]})
            best_url = res.json()["choices"][0]["message"]["content"].strip().strip('"').strip("'")
            return best_url if any(img in best_url for img in safe_images) else safe_images[0]
    except: return safe_images[0]

# ── ENGINES ──
async def fetch_rapidapi(keyword):
    """RapidAPI Search"""
    headers = {
        "x-rapidapi-host": RAPIDAPI_HOST,
        "x-rapidapi-key": RAPIDAPI_KEY,
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
            r = await client.get(SEARCH_URL, headers=headers, params={"keyword": keyword, "country": "us"})
            if r.status_code == 503:
                logger.error(f"❌ RapidAPI 503 — possible Cloudflare block. Response body:\n{r.text[:2000]}")
                return None
            if r.status_code == 200:
                data = r.json().get("data", [])
                products = data.get("products", []) if isinstance(data, dict) else data
                # Guard: only return if it's actually a list
                return products if isinstance(products, list) else None
    except: return None

async def get_rapidapi_gallery(asin):
    """Gallery fetcher for RapidAPI"""
    headers = {"x-rapidapi-host": RAPIDAPI_HOST, "x-rapidapi-key": RAPIDAPI_KEY}
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.get(DETAILS_URL, headers=headers, params={"asin": asin, "country": "us"})
            return r.json().get("data", {}).get("images", [])
    except: return []

async def fetch_apify(keyword, max_results):
    """Apify Tank Engine (Deep Scrape)"""
    logger.info("🛡️ Failover: Triggering Apify Tank Engine...")
    url = f"https://api.apify.com/v2/acts/{APIFY_ACTOR_ID}/run-sync-get-dataset-items?token={APIFY_API_KEY}"
    payload = {"searchTerms": [{"searchQuery": keyword}], "maxItems": max_results}
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            res = await client.post(url, json=payload)
            # FIX: Guard against non-200 responses (e.g. 400 Bad Request returns an error dict,
            # not a list — slicing a dict causes "unhashable type: 'slice'")
            if res.status_code != 200:
                logger.error(f"❌ Apify returned {res.status_code}: {res.text[:200]}")
                return None
            data = res.json()
            # Guard: ensure the parsed body is a list, not an error-shaped dict
            if not isinstance(data, list):
                logger.error(f"❌ Apify response is not a list: {str(data)[:200]}")
                return None
            return data
    except Exception as e:
        logger.error(f"❌ Apify request exception: {e}")
        return None

# ── MAIN HYBRID FUNCTION ──
async def search_products(keyword: str = "", niche: str = "", max_results: int = 5) -> list:
    raw_products = await fetch_rapidapi(keyword)

    if not raw_products:
        logger.warning(f"⚠️ RapidAPI returned nothing for keyword: '{keyword}' — skipping.")
        return []

    normalized = []
    for idx, item in enumerate(raw_products[:max_results]):
        # Quality Shield
        rating = float(str(item.get("rating", "0")).split()[0])
        reviews = int(''.join(filter(str.isdigit, str(item.get("ratingNumber", "0")))) or 0)

        if rating < 3.5 or reviews < 50: continue

        asin = item.get("asin")
        title = item.get("title", "Amazon Product")
        price = item.get("price", "$0.00")

        # Image via RapidAPI details endpoint only
        gallery = await get_rapidapi_gallery(asin)
        await asyncio.sleep(2)  # Detail calls delay

        best_img = await get_best_lifestyle_image(gallery) if gallery else item.get("thumbnail", "")

        normalized.append({
            "product_id": asin, "product_name": title[:100], "sale_price": str(price),
            "rating": rating, "image_url": best_img, "product_url": f"https://www.amazon.com/dp/{asin}"
        })
        await asyncio.sleep(5) # Vision call spacing

    return normalized

if __name__ == "__main__":
    async def test():
        data = await search_products(keyword="aesthetic desk lamp", max_results=3)
        print(f"Fetched {len(data)} items.")
    asyncio.run(test())
