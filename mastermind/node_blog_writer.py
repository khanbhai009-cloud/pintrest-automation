"""
mastermind/node_blog_writer.py — Node 6: Blog Writer

4-Model Text Fallback Chain (10s wait between each, once per model):
  1st → Gemini Key 1  (GEMINI_API_KEY)   — gemini-2.5-flash
  2nd → Gemini Key 2  (GEMINI_API_KEY_2) — gemini-2.5-flash
  3rd → Groq          (GROQ_API_KEY)     — llama-3.3-70b-versatile
  4th → Cerebras      (CEREBRAS_API_KEY) — qwen-3-235b

State input:  should_create_blog, blog_products, cmo_strategy, last_posted_image_url
State output: blog_content (complete blog dict ready for Firebase)
"""

import asyncio
import json
import logging
import re
import unicodedata

from config import (
    GEMINI_API_KEY, GEMINI_API_KEY_2,
    GROQ_API_KEY, GROQ_MODEL,
    CEREBRAS_API_KEY, CEREBRAS_VISION_MODEL,
    VISION_RETRY_DELAY,
)

logger = logging.getLogger(__name__)

_NICHE_MAP = {
    "kitchen":     ("home-decor",  "kitchen"),
    "bedroom":     ("home-decor",  "bedroom"),
    "living room": ("home-decor",  "living-room"),
    "bathroom":    ("home-decor",  "bathroom"),
    "home office": ("home-decor",  "home-office"),
    "desk":        ("tech-setup",  "desk-setup"),
    "tech":        ("tech-setup",  "gadgets"),
    "gaming":      ("tech-setup",  "gaming"),
    "phone":       ("tech-setup",  "phone"),
    "cozy":        ("home-decor",  "cozy"),
    "organize":    ("home-decor",  "organization"),
    "gadgets":     ("home-decor",  "gadgets"),
}


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    text = re.sub(r"[\s_-]+", "-", text).strip("-")
    return text[:80]


def _infer_niche(style_name: str, title: str) -> tuple:
    combined = (style_name + " " + title).lower()
    for keyword, (niche, sub_niche) in _NICHE_MAP.items():
        if keyword in combined:
            return niche, sub_niche
    return "home-decor", "lifestyle"


def _build_writer_prompt(strategy: dict, products: list, image_url: str) -> str:
    style_name    = strategy.get("style_name", strategy.get("vibe", "aesthetic"))
    title         = strategy.get("title", "Beautiful Aesthetic Inspiration")
    description   = strategy.get("description", "")
    tags          = strategy.get("tags", [])
    visual_prompt = strategy.get("visual_prompt", "")
    primary_kw    = tags[0] if tags else style_name

    if products:
        lines = [
            f"  Product {i}: {p['name']} — {p.get('price','?')} "
            f"(insert after para {p.get('insert_after_para', i*2)}): {p.get('why_fits','')}"
            for i, p in enumerate(products, 1)
        ]
        products_brief = "\n".join(lines)
    else:
        products_brief = "  No specific products — write general lifestyle content."

    return f"""You are an expert SEO blog writer for a Pinterest-driven lifestyle blog.
Target audience: Women aged 25-44, US-based, love aesthetic home decor and lifestyle content.

PIN DETAILS:
  Style Name    : {style_name}
  Pin Title     : {title}
  Pin Caption   : {description}
  Visual Theme  : {visual_prompt}
  Primary Keyword: {primary_kw}

PRODUCTS TO MENTION NATURALLY (do not write "sponsored" or "affiliate"):
{products_brief}

WRITING RULES:
  • Write exactly 9 paragraphs (id: 1 through 9)
  • Each paragraph: 120–150 words, engaging, human-sounding, NOT robotic
  • Naturally weave in the products listed above near their suggested insert point
  • Do NOT use the word "affiliate", "sponsored", "commission", or "paid"
  • Sound like a genuine lifestyle blogger recommendation
  • Include the primary keyword naturally in paragraphs 1, 4, and 8
  • Write 3 FAQ questions a US home lifestyle buyer would Google
  • Assign niche/sub_niche from this style: "{style_name}"
    Use: home-decor / kitchen | home-decor / bedroom | home-decor / cozy |
         tech-setup / desk-setup | home-decor / lifestyle

OUTPUT ONLY valid raw JSON (no markdown, no explanation):
{{
  "title": "SEO title max 60 chars — include primary keyword",
  "slug": "url-friendly-slug-max-60-chars",
  "seo_title": "meta title 55-60 chars with keyword",
  "meta_description": "compelling meta desc 150-160 chars with soft CTA",
  "primary_keyword": "{primary_kw}",
  "excerpt": "teaser 150 chars — what this post is about",
  "tags": {json.dumps(tags[:5])},
  "niche": "home-decor",
  "sub_niche": "kitchen",
  "collection_tag": "home-decor/kitchen",
  "image_url": "{image_url}",
  "style_name": "{style_name}",
  "paragraphs": [
    {{"id": 1, "text": "paragraph text here..."}},
    {{"id": 2, "text": "..."}},
    {{"id": 3, "text": "..."}},
    {{"id": 4, "text": "..."}},
    {{"id": 5, "text": "..."}},
    {{"id": 6, "text": "..."}},
    {{"id": 7, "text": "..."}},
    {{"id": 8, "text": "..."}},
    {{"id": 9, "text": "..."}}
  ],
  "faq": [
    {{"question": "...", "answer": "..."}},
    {{"question": "...", "answer": "..."}},
    {{"question": "...", "answer": "..."}}
  ]
}}"""


def _parse_blog_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        return {}
    return json.loads(cleaned[start:end])


# ── 4-Model Text Fallback Chain ───────────────────────────────────────────────

async def _try_gemini_text(api_key: str, prompt: str, key_label: str) -> dict:
    if not api_key:
        raise RuntimeError(f"Gemini {key_label} not set")

    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)

    def _sync():
        return client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.6,
                max_output_tokens=3000,
            ),
        )

    response = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=120)
    raw = response.text or ""
    logger.info(f"[BlogWriter] Gemini raw response (500 chars): {raw[:500]}")
    return _parse_blog_json(raw)


async def _try_groq_text(prompt: str) -> dict:
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY not set")

    from groq import Groq

    def _sync():
        client = Groq(api_key=GROQ_API_KEY)
        return client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert SEO blog writer. Always respond with valid JSON only."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=3000,
            temperature=0.6,
            response_format={"type": "json_object"},
        )

    response = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=120)
    return _parse_blog_json(response.choices[0].message.content)


async def _try_cerebras_text(prompt: str) -> dict:
    if not CEREBRAS_API_KEY:
        raise RuntimeError("CEREBRAS_API_KEY not set")

    from openai import OpenAI

    def _sync():
        client = OpenAI(
            api_key=CEREBRAS_API_KEY,
            base_url="https://api.cerebras.ai/v1",
        )
        return client.chat.completions.create(
            model=CEREBRAS_VISION_MODEL,
            messages=[
                {"role": "system", "content": "You are an expert SEO blog writer. Always respond with valid JSON only."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=3000,
            temperature=0.6,
        )

    response = await asyncio.wait_for(asyncio.to_thread(_sync), timeout=120)
    return _parse_blog_json(response.choices[0].message.content)


async def _write_blog_with_fallback(prompt: str) -> dict:
    """
    4-model fallback chain — 10s wait between each attempt, once per model.
    Returns blog content dict (empty if all 4 fail).
    """
    attempts = [
        ("Gemini Key 1", lambda: _try_gemini_text(GEMINI_API_KEY,  prompt, "Key 1")),
        ("Gemini Key 2", lambda: _try_gemini_text(GEMINI_API_KEY_2, prompt, "Key 2")),
        ("Groq",         lambda: _try_groq_text(prompt)),
        ("Cerebras",     lambda: _try_cerebras_text(prompt)),
    ]

    for label, fn in attempts:
        try:
            logger.info(f"✍️ [BlogWriter] Trying {label}...")
            result = await fn()

            # Unwrap common Gemini wrapper patterns
            if isinstance(result, dict):
                if not result.get("title") and result.get("blog"):
                    result = result["blog"]
                elif not result.get("title") and result.get("post"):
                    result = result["post"]
                elif not result.get("title") and result.get("content"):
                    result = result["content"]

            if result and result.get("title"):
                logger.info(f"✅ [BlogWriter] {label} succeeded")
                return result

            logger.warning(f"⚠️ [BlogWriter] {label} returned invalid/empty blog")
        except Exception as e:
            logger.warning(f"⚠️ [BlogWriter] {label} failed: {str(e)[:120]}")

        logger.info(f"⏳ [BlogWriter] Waiting {VISION_RETRY_DELAY}s before next model...")
        await asyncio.sleep(VISION_RETRY_DELAY)

    logger.error("❌ [BlogWriter] All 4 models failed — returning empty blog")
    return {}


# ── Node ──────────────────────────────────────────────────────────────────────

async def node_blog_writer(state: dict) -> dict:
    """
    Node 6 — Blog Writer.
    Skips if should_create_blog is False.
    Uses 4-model text fallback chain.
    """
    if not state.get("should_create_blog"):
        logger.info("✍️ [BlogWriter] Skipping — should_create_blog=False")
        return {**state, "blog_content": {}}

    trigger = state.get("cycle_trigger", "")
    if "account2" in trigger and "account1" not in trigger:
        strategy = state.get("a2_cmo_strategy", {})
        account  = "Account2_Tech"
    else:
        strategy = state.get("a1_cmo_strategy", {})
        account  = "Account1_HomeDecor"

    products  = state.get("blog_products", [])
    image_url = state.get("last_posted_image_url", "")

    prompt = _build_writer_prompt(strategy, products, image_url)

    blog_content = await _write_blog_with_fallback(prompt)

    if not blog_content:
        return {**state, "blog_content": {}}

    # ── Post-processing ───────────────────────────────────────────────────────
    if blog_content.get("title") and not blog_content.get("slug"):
        blog_content["slug"] = _slugify(blog_content["title"])

    blog_content["account"] = account

    niche, sub_niche = _infer_niche(
        blog_content.get("style_name", strategy.get("style_name", "")),
        blog_content.get("title", ""),
    )
    if not blog_content.get("niche"):
        blog_content["niche"] = niche
    if not blog_content.get("sub_niche"):
        blog_content["sub_niche"] = sub_niche
    if not blog_content.get("collection_tag"):
        blog_content["collection_tag"] = f"{blog_content['niche']}/{blog_content['sub_niche']}"

    title      = blog_content.get("title", "?")
    para_count = len(blog_content.get("paragraphs", []))
    logger.info(f"✍️ Blog written: '{title}' ({para_count} paragraphs)")

    return {**state, "blog_content": blog_content}
