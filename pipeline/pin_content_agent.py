"""
pipeline/pin_content_agent.py — Keyword → Pinterest Pin Content (Title + Description + Hashtags)

AI CHAIN:
  Primary:  Gemini 2.5 Flash (gemini_api_key)
  Fallback: Gemini Flash Lite (gemini_api_key_2)
  Last:     Groq llama-3.3-70b

RATE LIMITING:
  - 429 hit → 30s sleep → retry
  - Max 3 attempts per model before switching
"""

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── Lazy imports (avoids circular deps at startup) ─────────────────────────────
def _get_gemini_clients():
    from config import GEMINI_API_KEY, GEMINI_API_KEY_2
    from google import genai
    primary  = genai.Client(api_key=GEMINI_API_KEY)  if GEMINI_API_KEY  else None
    fallback = genai.Client(api_key=GEMINI_API_KEY_2) if GEMINI_API_KEY_2 else None
    return primary, fallback


def _get_groq_client():
    from config import GROQ_API_KEY, GROQ_MODEL
    from groq import Groq
    return Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None, GROQ_MODEL


# ══════════════════════════════════════════════════════════════════════════════
# PROMPT BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_prompt(keyword: str, niche: str) -> str:
    return f"""You are a world-class Pinterest SEO expert who has grown multiple accounts to 1M+ monthly views.

Your task: Generate viral Pinterest pin content for the keyword below.

KEYWORD: {keyword}
NICHE:   {niche}

OUTPUT RULES:
1. title       : Max 100 chars. Start with PRIMARY KEYWORD. Use power words: "genius", "life-changing", "under $20", "you need this". Active voice only.
2. description : Max 500 chars. Open with core benefit. Naturally include 2-3 long-tail keywords. Add a CTA: "Save this pin for later", "Shop via link in bio". 2-4 emojis max. NO generic filler.
3. hashtags    : Exactly 5 hashtags. Mix: 1 broad niche + 2 specific + 1 trending + 1 lifestyle. NO generic ones like #shopping or #deals.
4. niche       : Return the niche as-is: {niche}
5. board_suggestion: Suggest ONE Pinterest board name this pin belongs to.

Respond ONLY with valid JSON, no extra text:
{{
  "title": "...",
  "description": "...",
  "hashtags": ["tag1","tag2","tag3","tag4","tag5"],
  "niche": "{niche}",
  "board_suggestion": "..."
}}"""


# ══════════════════════════════════════════════════════════════════════════════
# LLM CALLERS
# ══════════════════════════════════════════════════════════════════════════════

def _call_gemini(client, model: str, prompt: str, max_retries: int = 3) -> Optional[str]:
    from google.genai import types
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.models.generate_content(
                model    = model,
                contents = prompt,
                config   = types.GenerateContentConfig(temperature=0.8),
            )
            text = resp.text.strip()
            if text:
                return text
        except Exception as e:
            err = str(e)
            logger.warning(f"⚠️ Gemini [{model}] attempt {attempt}: {err[:80]}")
            if "429" in err or "quota" in err.lower() or "rate" in err.lower():
                logger.info(f"⏳ Rate limited — sleeping 30s...")
                time.sleep(30)
            elif attempt < max_retries:
                time.sleep(5)
    return None


def _call_groq(prompt: str, max_retries: int = 3) -> Optional[str]:
    from config import GROQ_API_KEY, GROQ_MODEL
    from groq import Groq
    if not GROQ_API_KEY:
        return None
    client = Groq(api_key=GROQ_API_KEY)
    for attempt in range(1, max_retries + 1):
        try:
            resp = client.chat.completions.create(
                model    = GROQ_MODEL,
                messages = [{"role": "user", "content": prompt}],
                temperature = 0.8,
            )
            text = resp.choices[0].message.content.strip()
            if text:
                return text
        except Exception as e:
            err = str(e)
            logger.warning(f"⚠️ Groq attempt {attempt}: {err[:80]}")
            if "429" in err or "rate" in err.lower():
                logger.info(f"⏳ Groq rate limited — sleeping 30s...")
                time.sleep(30)
            elif attempt < max_retries:
                time.sleep(5)
    return None


def _parse_json(raw: str) -> Optional[dict]:
    """JSON extract karo — markdown fencing ke saath bhi kaam kare."""
    try:
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
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


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def generate_pin_content(keyword: str, niche: str = "home") -> dict:
    """
    Keyword se Pinterest pin content generate karo.

    Args:
        keyword : Viral Pinterest keyword (e.g. "aesthetic bedroom wall decor 2025")
        niche   : Board niche (home/kitchen/tech/etc.)

    Returns:
        {
            "title"           : str,
            "description"     : str,
            "hashtags"        : list[str],
            "niche"           : str,
            "board_suggestion": str,
        }
    """
    from config import GEMINI_CMO_MODEL, GEMINI_CHAT_MODEL
    prompt = _build_prompt(keyword, niche)
    raw    = None

    # ── Step 1: Gemini Primary ──────────────────────────────────────────────
    try:
        primary, fallback = _get_gemini_clients()
        if primary:
            logger.info(f"🧠 [PinContent] Gemini primary → '{keyword[:50]}'")
            raw = _call_gemini(primary, GEMINI_CMO_MODEL, prompt)
    except Exception as e:
        logger.warning(f"⚠️ Gemini primary init failed: {e}")

    # ── Step 2: Gemini Fallback ─────────────────────────────────────────────
    if not raw:
        try:
            primary, fallback = _get_gemini_clients()
            if fallback:
                logger.info(f"🔄 [PinContent] Gemini fallback → '{keyword[:50]}'")
                raw = _call_gemini(fallback, GEMINI_CHAT_MODEL, prompt)
        except Exception as e:
            logger.warning(f"⚠️ Gemini fallback init failed: {e}")

    # ── Step 3: Groq Last Resort ────────────────────────────────────────────
    if not raw:
        logger.info(f"🔄 [PinContent] Groq last resort → '{keyword[:50]}'")
        raw = _call_groq(prompt)

    # ── Parse ───────────────────────────────────────────────────────────────
    if raw:
        result = _parse_json(raw)
        if result and "title" in result and "description" in result:
            logger.info(f"✅ [PinContent] Generated: '{result['title'][:60]}'")
            return result

    # ── Hard fallback ───────────────────────────────────────────────────────
    logger.error(f"❌ [PinContent] All models failed — using keyword as fallback title")
    return {
        "title":            keyword[:100],
        "description":      f"Discover the best {keyword}! 🌟 Save this pin for later. Shop via link in bio. #{niche.title()}Finds #MustHave #AmazonFinds",
        "hashtags":         [f"{niche.title()}Ideas", "AmazonFinds", "MustHave", "PinterestInspo", "HomeDecorGoals"],
        "niche":            niche,
        "board_suggestion": f"{niche.title()} Inspiration",
    }
