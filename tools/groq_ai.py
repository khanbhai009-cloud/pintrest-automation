import json
import logging
from tools.llm import chat
from config import MIN_GRAVITY

logger = logging.getLogger(__name__)


def filter_product(product: dict) -> bool:
    prompt = f"""You are a senior affiliate marketing strategist with 10+ years of experience in e-commerce and Pinterest marketing.

Analyze this AliExpress product for Pinterest affiliate marketing potential.

Product Data:
{json.dumps(product, indent=2)}

HARD REJECT if ANY of these are true:
- Rating is 0 AND orders is 0 or missing
- Product is adult, gambling, political, or religious in nature
- No valid image URL
- Product title is gibberish or clearly low quality
- Price is suspiciously too low (likely scam, e.g. $0.01)

APPROVE if:
- Has decent sales volume OR good rating (3.5+)
- Product solves a real problem or fulfills a desire
- Has visual appeal potential for Pinterest (aesthetic, satisfying, useful)
- Fits trending niches: home improvement, fitness, beauty, tech gadgets, kitchen, travel, pet care, organization
- Global audience would find it interesting (not hyper-local)

Think step by step, then respond ONLY with valid JSON, no extra text:
{{"approve": true/false, "reason": "one line reason", "niche": "identified niche category", "viral_potential": "high/medium/low"}}"""

    try:
        raw = chat(prompt, temperature=0.1)
        result = json.loads(raw.strip())
        status = "✅" if result["approve"] else "❌"
        logger.info(f"{status} [{result.get('viral_potential','?')}] {str(product.get('product_name',''))[:80]}: {result.get('reason')}")
        return result["approve"]
    except Exception as e:
        logger.error(f"Filter error: {e}")
        return False


def generate_pin_copy(product: dict) -> dict:
    prompt = f"""You are a world-class Pinterest marketing expert and viral content strategist. You have grown multiple Pinterest accounts to 1M+ monthly views. You deeply understand Pinterest's global audience, SEO algorithm, and what makes pins go viral.

Your task: Create high-converting, viral Pinterest pin content for this AliExpress affiliate product.

Product Data:
{json.dumps(product, indent=2)}

PINTEREST AUDIENCE CONTEXT:
- 70%+ users are women aged 18-45 globally (US, UK, Australia, Canada heavily)
- Users come to Pinterest with BUYING INTENT and for inspiration
- Pinterest is a VISUAL SEARCH ENGINE, not a social media — SEO matters massively
- Pins have a 4-6 month lifespan, unlike Instagram/TikTok posts
- Emotional triggers that work: aspiration, problem-solving, "I need this", FOMO, lifestyle upgrades

TITLE RULES (CRITICAL for SEO):
- Max 100 characters
- Put PRIMARY KEYWORD first (Pinterest indexes first words heavily)
- Use power words: "genius", "life-changing", "under $20", "hidden gem", "you need this"
- Create curiosity gap or immediate value statement
- NO clickbait — Pinterest penalizes misleading titles
- Example style: "Genius Kitchen Gadget That Saves 30 Min Daily ✨"

DESCRIPTION RULES:
- Max 500 characters with powerful seo of pinterest 
- Open with the CORE BENEFIT & THE PRODUCT FEATURES 
- Include 2-3 long-tail keywords naturally woven in
- Add example how this product help you 
- Clear CTA: "Shop now via link in bio", "Grab it before it sells out"
- Use emojis strategically — 2-4 max, not spammy

HASHTAG RULES:
- Use NICHE hashtags, NOT generic ones
- Good: #HomeOrganization #KitchenHacks #GadgetLovers
- Bad: #shopping #deals #aliexpress #india
- Mix: 1 broad niche + 2 specific + 1 trending style
- Total: exactly 5 hashtags

TONE:
- Aspirational and confident, NOT salesy or desperate
- Write like a trusted friend who found an amazing product
- Global English — avoid Indian slang, must appeal to US/UK/AU audience

Respond ONLY with valid JSON, absolutely no extra text:
{{"title": "...", "description": "...", "tags": ["tag1","tag2","tag3","tag4","tag5"], "board_suggestion": "suggested Pinterest board name"}}"""

    try:
        raw = chat(prompt, temperature=0.75)
        return json.loads(raw.strip())
    except Exception as e:
        logger.error(f"Copy gen error: {e}")
        return {
            "title": product.get("product_name", "Amazing Find")[:100],
            "description": "This product is a total game changer! 🔥 Check it out via link in bio. #HomeGadgets #MustHave #GadgetLovers #LifeHacks #AmazonFinds",
            "tags": ["HomeGadgets", "MustHave", "GadgetLovers", "LifeHacks", "TrendingNow"],
            "board_suggestion": "Home & Living Essentials"
        }