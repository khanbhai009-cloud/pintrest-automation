import httpx
import logging
from config import RAPIDAPI_KEY

logger = logging.getLogger(__name__)
BASE_URL = "https://aliexpress-datahub.p.rapidapi.com"
HEADERS  = {
    "x-rapidapi-host": "aliexpress-datahub.p.rapidapi.com",
    "x-rapidapi-key":  RAPIDAPI_KEY,
}
DEFAULT_KEYWORDS = [
    "home gadgets", "fitness equipment", "phone accessories",
    "kitchen tools", "beauty products", "led lights",
    "portable charger", "smart watch", "desk accessories",
]

async def search_products(keyword: str, page: int = 1, max_results: int = 20) -> list:
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(
                f"{BASE_URL}/item_search_2",
                headers=HEADERS,
                params={"keywords": keyword, "page": str(page), "sort": "SALE_PRICE_ASC"},
            )
        r.raise_for_status()
        data = r.json()
        raw  = (data.get("result", {}).get("resultList", [])
                or data.get("data", {}).get("products", []) or [])
        normalized = []
        for item in raw[:max_results]:
            info = item.get("item", item)
            pid  = str(info.get("itemId") or info.get("item_id") or "")
            if not pid:
                continue
            price   = info.get("sku", {}).get("def", {})
            images  = info.get("images") or []
            img     = images[0] if images else info.get("image", "")
            if img and not img.startswith("http"):
                img = f"https:{img}"
            normalized.append({
                "product_id":   pid,
                "product_name": (info.get("title") or info.get("name", ""))[:120],
                "sale_price":   price.get("promotionPrice") or price.get("price") or 0,
                "orders":       info.get("sales") or "0",
                "rating":       info.get("averageStar") or 0,
                "image_url":    img,
                "product_url":  f"https://www.aliexpress.com/item/{pid}.html",
                "keyword":      keyword,
            })
        logger.info(f"✅ AliExpress '{keyword}': {len(normalized)} products")
        return normalized
    except Exception as e:
        logger.error(f"❌ AliExpress error: {e}")
        return []
