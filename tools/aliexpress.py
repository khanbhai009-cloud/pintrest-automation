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
                params={"q": keyword, "page": str(page), "sort": "SALE_PRICE_ASC"},
            )
        r.raise_for_status()
        data = r.json()

        # Log raw response structure for debugging
        logger.info(f"🔍 Raw keys: {list(data.keys())}")

        # Try all possible response paths
        raw = (
            data.get("result", {}).get("resultList") or
            data.get("result", {}).get("items") or
            data.get("data", {}).get("products") or
            data.get("items") or
            data.get("products") or
            []
        )

        if not raw:
            logger.warning(f"⚠️ No items in response. Full response: {str(data)[:300]}")
            return []

        normalized = []
        for item in raw[:max_results]:
            # DataHub wraps in "item" key sometimes
            info = item.get("item", item)

            pid = str(
                info.get("itemId") or
                info.get("item_id") or
                info.get("productId") or ""
            )
            if not pid:
                continue

            # Price extraction
            sku         = info.get("sku", {})
            price_info  = sku.get("def", {}) if isinstance(sku, dict) else {}
            sale_price  = (
                price_info.get("promotionPrice") or
                price_info.get("price") or
                info.get("salePrice") or
                info.get("price") or 0
            )

            # Image extraction
            images    = info.get("images") or []
            image_url = images[0] if images else (info.get("image") or info.get("imageUrl") or "")
            if image_url and not str(image_url).startswith("http"):
                image_url = f"https:{image_url}"

            title = (
                info.get("title") or
                info.get("name") or
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
            })

        logger.info(f"✅ AliExpress '{keyword}': {len(normalized)} products")
        return normalized

    except Exception as e:
        logger.error(f"❌ AliExpress error: {e}")
        return []
