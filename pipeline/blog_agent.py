"""
pipeline/blog_agent.py — SEO Blog Post Generator

INPUT:
  - pin_content : {title, description, hashtags, niche} from pin_content_agent
  - image_url   : ImgBB hosted pin image URL
  - products    : [{amazon_title, affiliate_url, price, rating, thumbnail, ...}] from amazon_fetcher
  - keyword     : Primary keyword

OUTPUT:
  {
    "slug"         : "aesthetic-bedroom-wall-decor-ideas-2025",
    "title"        : "...",
    "meta_desc"    : "...",
    "content_html" : "...",   # Full HTML article ~1500 words
    "image_url"    : "...",
    "products"     : [...],   # Same product list
    "keyword"      : "...",
    "niche"        : "...",
    "word_count"   : 1500,
  }

AI CHAIN:
  Primary:  Gemini 2.5 Flash  (GEMINI_API_KEY)   ← best quality
  Fallback: Gemini Flash Lite (GEMINI_API_KEY_2)  ← if primary 429
  Last:     Groq llama-3.3-70b                    ← if both Gemini fail

RATE LIMITING: 429 → 30s sleep → retry (max 3 per model)

SEO PROMPT STYLE: Based on Free SEO Writing prompt (conversational, H2/H3, active voice,
  short paragraphs, bold key info, rhetorical questions, light humor)
"""

import json
import logging
import re
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_SLEEP = 30


# ══════════════════════════════════════════════════════════════════════════════
# SLUG GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def _slugify(text: str) -> str:
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:80]


# ══════════════════════════════════════════════════════════════════════════════
# BLOG PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_blog_prompt(
    keyword:     str,
    title:       str,
    description: str,
    niche:       str,
    products:    List[dict],
    image_url:   str,
) -> str:
    # Build product section for the blog
    product_section = ""
    if products:
        product_section = "\n\nPRODUCTS TO FEATURE IN THE BLOG (embed as HTML links in the article):\n"
        for i, p in enumerate(products[:6], 1):
            product_section += (
                f"{i}. {p.get('amazon_title','Product')[:80]}\n"
                f"   Price: {p.get('price','N/A')} | Rating: ⭐{p.get('rating','N/A')}\n"
                f"   Affiliate Link: {p.get('affiliate_url','#')}\n"
                f"   Thumbnail: {p.get('thumbnail','')}\n\n"
            )

    return f"""Write a 1,500-word SEO blog article titled "{title}" for a Pinterest lifestyle blog.

PRIMARY KEYWORD: {keyword}
NICHE: {niche}
META DESCRIPTION (use this exactly): {description}

FEATURED IMAGE: {image_url}
{product_section}

WRITING STYLE (follow PRECISELY):
1. Conversational & Informal — write like talking to a friend. Relaxed, approachable, everyday language.
2. Active Voice ONLY — "I love this gadget" not "This gadget is loved by many."
3. Short paragraphs — 3-4 sentences MAX per paragraph. No walls of text.
4. H2 headings for major sections, H3 for subtopics.
5. Bold the most important points and product names using <strong> tags.
6. Rhetorical questions — ask the reader 2-3 questions to engage them (e.g., "Ever wondered why this works so well?")
7. Light humor + sarcasm — subtle, witty, not overwhelming. 1-2 instances max.
8. 2-3 internet slang (FYI, IMO, tbh) or emoticons (:)) sprinkled naturally.
9. Bullet points or numbered lists for technical details / product features.
10. NO filler phrases: no "dive into", "in today's world", "in modern times", "it's worth noting".
11. NO generic openers. Start with a punchy hook that immediately addresses the reader.

HTML STRUCTURE:
- Use proper HTML: <h2>, <h3>, <p>, <ul>, <li>, <strong>, <em>, <a href="...">
- Insert the FEATURED IMAGE: <img src="{image_url}" alt="{keyword}" style="max-width:100%;border-radius:12px;margin:20px 0;">
- For EACH PRODUCT: embed as a card — name as <strong>, price, star rating, and an <a href="AFFILIATE_LINK">Shop on Amazon →</a> link
- Include products naturally IN THE FLOW of the article (not just at the end)
- Product cards format:
  <div class="product-card" style="border:1px solid #eee;border-radius:10px;padding:16px;margin:16px 0;display:flex;gap:12px;align-items:center;">
    <img src="THUMBNAIL_URL" style="width:80px;height:80px;object-fit:cover;border-radius:8px;" />
    <div>
      <strong>PRODUCT NAME</strong><br/>
      ⭐ RATING &nbsp;|&nbsp; PRICE<br/>
      <a href="AFFILIATE_URL" style="color:#e60023;font-weight:600;">Shop on Amazon →</a>
    </div>
  </div>

CONCLUSION:
- Concise summary of key points.
- Engaging final thought or call to action.
- Invite reader to save the pin or visit the blog again.

OUTPUT FORMAT — Return ONLY valid JSON, no extra text:
{{
  "title": "{title}",
  "meta_desc": "{description[:155]}",
  "content_html": "<full HTML article here — ~1500 words>"
}}"""


# ══════════════════════════════════════════════════════════════════════════════
# LLM CALLERS
# ══════════════════════════════════════════════════════════════════════════════

def _call_gemini(api_key: str, model: str, prompt: str) -> Optional[str]:
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.models.generate_content(
                model    = model,
                contents = prompt,
                config   = types.GenerateContentConfig(
                    temperature    = 0.85,
                    max_output_tokens = 4096,
                ),
            )
            text = resp.text.strip()
            if text:
                return text
        except Exception as e:
            err = str(e)
            logger.warning(f"⚠️ [BlogAgent] Gemini [{model}] attempt {attempt}: {err[:80]}")
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                logger.info(f"⏳ Gemini rate limit — sleeping {_RETRY_SLEEP}s...")
                time.sleep(_RETRY_SLEEP)
            elif attempt < _MAX_RETRIES:
                time.sleep(5)
    return None


def _call_groq(prompt: str) -> Optional[str]:
    from config import GROQ_API_KEY, GROQ_MODEL
    from groq import Groq

    if not GROQ_API_KEY:
        return None

    client = Groq(api_key=GROQ_API_KEY)
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model       = GROQ_MODEL,
                messages    = [{"role": "user", "content": prompt}],
                temperature = 0.85,
                max_tokens  = 4096,
            )
            text = resp.choices[0].message.content.strip()
            if text:
                return text
        except Exception as e:
            err = str(e)
            logger.warning(f"⚠️ [BlogAgent] Groq attempt {attempt}: {err[:80]}")
            if "429" in err or "rate" in err.lower():
                logger.info(f"⏳ Groq rate limit — sleeping {_RETRY_SLEEP}s...")
                time.sleep(_RETRY_SLEEP)
            elif attempt < _MAX_RETRIES:
                time.sleep(5)
    return None


# ══════════════════════════════════════════════════════════════════════════════
# JSON PARSER
# ══════════════════════════════════════════════════════════════════════════════

def _parse_blog_json(raw: str) -> Optional[dict]:
    try:
        cleaned = raw.strip()
        if "```" in cleaned:
            parts   = cleaned.split("```")
            cleaned = parts[1] if len(parts) > 1 else cleaned
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        return json.loads(cleaned.strip())
    except Exception:
        try:
            start = raw.index("{")
            end   = raw.rindex("}") + 1
            return json.loads(raw[start:end])
        except Exception:
            return None


def _count_words(html: str) -> int:
    text = re.sub(r"<[^>]+>", " ", html)
    return len(text.split())


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def generate_blog_post(
    keyword:     str,
    pin_content: dict,
    image_url:   str,
    products:    List[dict],
) -> dict:
    """
    SEO blog post generate karo.

    Args:
        keyword     : Primary Pinterest keyword
        pin_content : generate_pin_content() ka output
        image_url   : ImgBB hosted image URL
        products    : fetch_amazon_products() ka output

    Returns:
        {
            "slug"         : str,
            "title"        : str,
            "meta_desc"    : str,
            "content_html" : str,
            "image_url"    : str,
            "products"     : list,
            "keyword"      : str,
            "niche"        : str,
            "word_count"   : int,
        }
    """
    from config import GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_CMO_MODEL, GEMINI_CHAT_MODEL

    title       = pin_content.get("title", keyword)
    description = pin_content.get("description", "")
    niche       = pin_content.get("niche", "home")

    logger.info(f"📝 [BlogAgent] Generating blog: '{title[:60]}'")

    prompt = _build_blog_prompt(keyword, title, description, niche, products, image_url)
    raw    = None

    # ── Gemini Primary ──────────────────────────────────────────────────────
    if GEMINI_API_KEY:
        logger.info("🧠 [BlogAgent] Gemini primary...")
        raw = _call_gemini(GEMINI_API_KEY, GEMINI_CMO_MODEL, prompt)

    # ── Gemini Fallback ─────────────────────────────────────────────────────
    if not raw and GEMINI_API_KEY_2:
        logger.info("🔄 [BlogAgent] Gemini fallback...")
        raw = _call_gemini(GEMINI_API_KEY_2, GEMINI_CHAT_MODEL, prompt)

    # ── Groq Last Resort ────────────────────────────────────────────────────
    if not raw:
        logger.info("🔄 [BlogAgent] Groq last resort...")
        raw = _call_groq(prompt)

    blog_data = _parse_blog_json(raw) if raw else None

    if blog_data and blog_data.get("content_html"):
        content_html = blog_data["content_html"]
        slug         = _slugify(title)
        word_count   = _count_words(content_html)
        logger.info(f"✅ [BlogAgent] Blog done — slug='{slug}', ~{word_count} words")
        return {
            "slug":         slug,
            "title":        blog_data.get("title", title),
            "meta_desc":    blog_data.get("meta_desc", description[:155]),
            "content_html": content_html,
            "image_url":    image_url,
            "products":     products,
            "keyword":      keyword,
            "niche":        niche,
            "word_count":   word_count,
        }

    # Hard fallback — minimal blog
    logger.error("❌ [BlogAgent] All models failed — using minimal fallback blog.")
    fallback_html = f"""<img src="{image_url}" alt="{keyword}" style="max-width:100%;border-radius:12px;margin:20px 0;">
<p>{description}</p>
<h2>Our Top Picks</h2>
{"".join([
    f'<p><strong>{p.get("amazon_title","Product")[:60]}</strong> — '
    f'<a href="{p.get("affiliate_url","#")}">Shop on Amazon →</a></p>'
    for p in products[:5]
])}"""

    return {
        "slug":         _slugify(title),
        "title":        title,
        "meta_desc":    description[:155],
        "content_html": fallback_html,
        "image_url":    image_url,
        "products":     products,
        "keyword":      keyword,
        "niche":        niche,
        "word_count":   _count_words(fallback_html),
    }
