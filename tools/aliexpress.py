import httpx
import logging
import random
import os
from config import RAPIDAPI_KEY

# Agar tumne GROQ_API_KEY config.py me daali hai toh wahan se import kar lena, 
# warna .env se uthane ke liye os.getenv use kar rahe hain.
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "your_groq_api_key_here")

logger = logging.getLogger(__name__)

# RapidAPI Endpoints
SEARCH_URL = "https://real-time-amazon-data.p.rapidapi.com/search"
DETAILS_URL = "https://real-time-amazon-data.p.rapidapi.com/product-details"

HEADERS = {
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

async def get_product_photos(asin: str) -> list:
    """ASIN ka use karke product ki saari images fetch karta hai."""
    logger.info(f"🔍 Fetching photo gallery for ASIN: {asin}...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            params = {"asin": asin, "country": "US"}
            r = await client.get(DETAILS_URL, headers=HEADERS, params=params)
            r.raise_for_status()
            
            data = r.json()
            # RapidAPI 'product_photos' array return karta hai
            photos = data.get("data", {}).get("product_photos", [])
            return photos
    except Exception as e:
        logger.error(f"❌ Failed to get details for {asin}: {e}")
        return []

async def get_best_lifestyle_image(image_urls: list) -> str:
    """Groq Vision LLM ko use karke sabse aesthetic Pinterest-worthy image select karta hai."""
    if not image_urls:
        return ""
    if len(image_urls) == 1:
        return image_urls[0]

    logger.info("👁️ [Vision Agent] Analyzing images for best Pinterest vibe...")
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            content_payload = [
                {
                    "type": "text", 
                    "text": "You are an expert Pinterest aesthetic curator. Review these product images. Select the ONE image that is most 'lifestyle' oriented (e.g., product in a real room setting, aesthetic background, warm lighting). DO NOT pick plain white background images or images with heavy text/dimensions. Output ONLY the exact URL of the best image. No extra words."
                }
            ]
            
            # API load kam rakhne ke liye max 5 images bhej rahe hain
            for url in image_urls[:5]: 
                content_payload.append({
                    "type": "image_url",
                    "image_url": {"url": url}
                })

            payload = {
                "model": "llama-3.2-11b-vision-preview",
                "messages": [{"role": "user", "content": content_payload}],
                "temperature": 0.1, # Low temp for deterministic strict URL output
                "max_tokens": 100
            }
            
            headers = {"Authorization": f"Bearer {GROQ_API_KEY}"}
            
            response = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            response.raise_for_status()
            
            best_url = response.json()['choices'][0]['message']['content'].strip()
            
            # Verify karte hain ki LLM ne URL hi return kiya hai
            if best_url.startswith("http"):
                logger.info("✅ [Vision Agent] Best aesthetic image selected!")
                return best_url
            else:
                logger.warning("⚠️ [Vision Agent] LLM didn't return a valid URL. Falling back.")
                return image_urls[0] 

    except Exception as e:
        logger.error(f"❌ [Vision Agent] Failed: {e}")
        return image_urls[0] # Error aane par fallback to default image

async def search_products(keyword: str = "", page: int = 1, max_results: int = 5, niche: str = "") -> list:
    """Main function jo search, fetch details, aur Vision filter ko combine karta hai."""
    try:
        if not keyword and niche:
            keyword = random.choice(KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS))

        logger.info(f"🛒 Searching Amazon for: '{keyword}'...")
        async with httpx.AsyncClient(timeout=30) as client:
            params = {
                "query": keyword,
                "page": str(page),
                "country": "US",
                "sort_by": "RELEVANCE",
                "language": "en_US"
            }
            r = await client.get(SEARCH_URL, headers=HEADERS, params=params)
        
        r.raise_for_status()
        data = r.json()
        raw = data.get("data", {}).get("products", [])

        if not raw:
            logger.warning(f"⚠️ No products found in API response for: {keyword}")
            return []

        normalized = []
        # Sirf top 'max_results' (default 5) process karenge taaki credits bachein
        for item in raw[:max_results]:
            asin = item.get("asin")
            if not asin:
                continue

            title = item.get("product_title", "Amazon Product")
            price = item.get("product_price", "$0.00")
            rating = item.get("product_star_rating", 0)
            reviews = item.get("product_num_ratings", 0)
            default_image = item.get("product_photo", "")
            
            # 1. Product details se saari images fetch karo
            photo_gallery = await get_product_photos(asin)
            
            if not photo_gallery:
                photo_gallery = [default_image] if default_image else []
                
            # 2. Vision Agent se best image filter karwao
            best_aesthetic_image = await get_best_lifestyle_image(photo_gallery)

            normalized.append({
                "product_id":   asin,
                "product_name": str(title)[:120],
                "sale_price":   str(price),
                "orders":       str(reviews),
                "rating":       rating,
                "image_url":    best_aesthetic_image, # 🚀 Vision Filtered Image!
                "product_url":  f"https://www.amazon.com/dp/{asin}",
                "keyword":      keyword,
                "niche":        niche,
            })

        logger.info(f"✅ Mastermind Cycle Complete! '{keyword}': {len(normalized)} highly-aesthetic items ready.")
        return normalized

    except Exception as e:
        logger.error(f"❌ Amazon Scraper Error: {e}")
        return []
