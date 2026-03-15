import httpx
import logging
from config import MAX_PRODUCTS_TO_FETCH, ALLOWED_CATEGORIES, BLOCKED_CATEGORIES

logger = logging.getLogger(__name__)

async def fetch_digistore_products(api_key: str) -> list:
    url = "https://www.digistore24.com/api/call/listMarketplace/format/json"
    params = {"api_key": api_key, "language": "en"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, params=params)
        data = response.json()
        logger.info(f"🔍 API Response keys: {list(data.keys())}")
        
        # Try different response structures
        products_data = (
            data.get("data", {}).get("products") or
            data.get("data", {}).get("items") or
            data.get("products") or
            []
        )
        
        logger.info(f"📦 Raw products: {len(products_data)}")
        
        normalized = []
        for p in products_data:
            category = str(p.get("category", "")).lower()
            if any(b in category for b in BLOCKED_CATEGORIES):
                continue
            normalized.append({
                "product_name": p.get("name", p.get("product_name", "")),
                "gravity": p.get("units_sold", p.get("gravity", 0)),
                "category": p.get("category", ""),
                "affiliate_link": p.get("affiliate_url", p.get("hoplink", "")),
                "image_url": p.get("picture", p.get("image_url", ""))
            })
            if len(normalized) >= MAX_PRODUCTS_TO_FETCH:
                break
        
        logger.info(f"✅ Normalized: {len(normalized)} products")
        return normalized
    except Exception as e:
        logger.error(f"❌ Digistore error: {e}")
        return []
