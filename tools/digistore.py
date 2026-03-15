import httpx
import logging
from config import MAX_PRODUCTS_TO_FETCH, ALLOWED_CATEGORIES, BLOCKED_CATEGORIES

logger = logging.getLogger(__name__)

async def fetch_digistore_products(api_key: str) -> list:
    url = f"https://www.digistore24.com/api/call/listMarketplace/api_key/{api_key}/format/json/language/en"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
        data = response.json()
        logger.info(f"🔍 Result: {data.get('result')} | Message: {data.get('message')}")

        products_data = (
            data.get("data", {}).get("products") or
            data.get("data", {}).get("items") or []
        )
        logger.info(f"📦 Raw products: {len(products_data)}")

        normalized = []
        for p in products_data:
            category = str(p.get("category", "")).lower()
            if any(b in category for b in BLOCKED_CATEGORIES):
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

        logger.info(f"✅ Normalized: {len(normalized)} products")
        return normalized
    except Exception as e:
        logger.error(f"❌ Digistore error: {e}")
        return []
