import httpx
import logging
from config import MAX_PRODUCTS_TO_FETCH, ALLOWED_CATEGORIES, BLOCKED_CATEGORIES

logger = logging.getLogger(__name__)

async def fetch_digistore_products(api_key: str) -> list:
    url = "https://www.digistore24.com/api/call/listProductsForAffiliate/format/json"
    params = {"api_key": api_key, "language": "en", "currency": "USD"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
        data = response.json()
        raw = data.get("data", {}).get("products", [])
        logger.info(f"📦 Raw products from Digistore: {len(raw)}")
        normalized = []
        for p in raw:
            category = p.get("category", "").lower()
            if any(b in category for b in BLOCKED_CATEGORIES):
                continue
            if not any(a in category for a in ALLOWED_CATEGORIES):
                continue
            normalized.append({
                "product_name": p.get("name", ""),
                "gravity": p.get("units_sold", 0),
                "category": p.get("category", ""),
                "affiliate_link": p.get("affiliate_url", ""),
                "image_url": p.get("picture", "")
            })
            if len(normalized) >= MAX_PRODUCTS_TO_FETCH:
                break
        logger.info(f"✅ After category filter: {len(normalized)} products")
        return normalized
    except Exception as e:
        logger.error(f"❌ Digistore error: {e}")
        return []
