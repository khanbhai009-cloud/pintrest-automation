import json
import logging
from tools.llm import chat
from config import MIN_GRAVITY

logger = logging.getLogger(__name__)


def filter_product(product: dict) -> bool:
    prompt = f"""You are an affiliate marketing expert. Analyze this AliExpress product.

Product: {json.dumps(product)}

REJECT if:
- 0 rating AND no orders
- Clearly low quality or scammy
- Adult or gambling niche
- No real image URL

Respond ONLY with valid JSON:
{{"approve": true, "reason": "good product"}}"""

    try:
        raw    = chat(prompt, temperature=0.1)
        result = json.loads(raw.strip())
        status = "✅" if result["approve"] else "❌"
        logger.info(f"{status} {str(product.get('product_name',''))[:80]}: {result.get('reason')}")
        return result["approve"]
    except Exception as e:
        logger.error(f"Filter error: {e}")
        return False


def generate_pin_copy(product: dict) -> dict:
    prompt = f"""You are a Pinterest marketing expert targeting us audience.
Create viral pin content for this AliExpress product.

Product: {json.dumps(product)}

Rules:
- Title: Max 100 chars, curiosity hook, keyword-rich ok 
- Description: Max 500 chars, benefits + CTA, emojis, hashtags at end
- Tags: 5 niche hashtags

Respond ONLY with valid JSON:
{{"title": "...", "description": "...", "tags": ["tag1","tag2","tag3","tag4","tag5"]}}"""

    try:
        raw = chat(prompt, temperature=0.7)
        return json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Copy gen error: {e}")
        return {
            "title":       product.get("product_name", "Check this out")[:100],
            "description": "Amazing product! Check it out 🔥 #deals #shopping",
            "tags":        ["deals", "shopping", "aliexpress", "india", "trending"]
        }
