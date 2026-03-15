import json
import logging
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL

logger = logging.getLogger(__name__)
client = Groq(api_key=GROQ_API_KEY)

def _chat(prompt: str, temperature: float = 0.1) -> str:
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature
    )
    return response.choices[0].message.content

def filter_product(product: dict) -> bool:
    prompt = f"""You are an affiliate marketing expert. Analyze this product.
Product: {json.dumps(product)}
APPROVE if: legitimate digital product, health/fitness/self-help/make money niche, has real image URL
REJECT if: scammy claims, adult/gambling content, no image, 0 sales
Respond ONLY with JSON: {{"approve": true, "reason": "brief reason"}}"""
    try:
        raw = _chat(prompt, temperature=0.1).strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        result = json.loads(raw)
        status = "✅" if result["approve"] else "❌"
        logger.info(f"{status} {product.get('product_name')}: {result.get('reason')}")
        return result["approve"]
    except Exception as e:
        logger.error(f"Filter error: {e}")
        return False

def generate_pin_copy(product: dict) -> dict:
    prompt = f"""You are a Pinterest marketing expert. Create viral pin content.
Product: {json.dumps(product)}
Rules:
- Title: Max 100 chars, curiosity hook
- Description: Max 500 chars, problem to solution, soft CTA
- Tags: 5 trending hashtags (no spaces, no #)
Respond ONLY with JSON: {{"title": "...", "description": "...", "tags": ["tag1","tag2","tag3","tag4","tag5"]}}"""
    try:
        raw = _chat(prompt, temperature=0.7).strip()
        if "```" in raw:
            raw = raw.split("```")[1].replace("json", "").strip()
        return json.loads(raw)
    except Exception as e:
        logger.error(f"Copy error: {e}")
        return {
            "title": product.get("product_name", "Check this"),
            "description": "Amazing product worth checking!",
            "tags": ["health", "wellness", "affiliate", "tips", "lifestyle"]
        }
