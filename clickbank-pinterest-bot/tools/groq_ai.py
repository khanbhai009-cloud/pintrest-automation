import json
import logging
from groq import Groq
from config import GROQ_API_KEY, GROQ_MODEL, MIN_GRAVITY

logger = logging.getLogger(__name__)
client = Groq(api_key=GROQ_API_KEY)

# ─────────────────────────────────────────
# INTERNAL: Raw Groq call
# ─────────────────────────────────────────
def _chat(prompt: str, temperature: float = 0.1) -> str:
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature
    )
    return response.choices[0].message.content


# ─────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────
def filter_product(product: dict) -> bool:
    """Returns True if product should be approved"""
    prompt = f"""You are an affiliate marketing expert. Analyze this ClickBank product.

Product data: {json.dumps(product)}

REJECT if any of these:
- Gravity below {MIN_GRAVITY}
- Scammy health claims ("cure diabetes in 3 days")
- Get-rich-quick schemes
- Adult or gambling niche
- Suspicious refund policy

Respond ONLY with valid JSON, no extra text:
{{"approve": true, "reason": "good gravity, health niche"}}"""

    try:
        raw = _chat(prompt, temperature=0.1)
        result = json.loads(raw.strip())
        status = "✅" if result["approve"] else "❌"
        logger.info(f"{status} {product.get('product_name')}: {result.get('reason')}")
        return result["approve"]
    except Exception as e:
        logger.error(f"Filter error: {e}")
        return False


def generate_pin_copy(product: dict) -> dict:
    """Generate Pinterest title, description, hashtags"""
    prompt = f"""You are a Pinterest marketing expert. Create pin content for this product.

Product: {json.dumps(product)}

Rules:
- Title: Max 100 chars, curiosity hook, no caps spam
- Description: Max 500 chars, benefit-focused, soft CTA at end
- Tags: 5 niche hashtags (no spaces)

Respond ONLY with valid JSON:
{{"title": "...", "description": "...", "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"]}}"""

    try:
        raw = _chat(prompt, temperature=0.7)
        return json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Copy gen error: {e}")
        return {
            "title": product.get("product_name", "Check this out"),
            "description": "Amazing product worth checking!",
            "tags": ["affiliate", "deals"]
        }

# ─────────────────────────────────────────
# FUTURE: Add generate_image_prompt() here
# for Level 3 AI image generation
# ─────────────────────────────────────────
