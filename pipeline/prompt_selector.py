"""
pipeline/prompt_selector.py — Keyword ke basis pe Prompts_Master se best T2I prompt select karo

HOW IT WORKS:
  1. Prompts_Master sheet se saare prompts load karo (already cached via sheets/prompts_master.py)
  2. Keyword ke saath niche + tags match karo
  3. Agar match mile → woh prompt return karo
  4. Agar koi match nahi → LLM se best pick karwao
  5. Agar prompts sheet empty hai → keyword se synthetic prompt banao

RATE LIMITING: Gemini → 30s sleep on 429 → Groq fallback
"""

import logging
import random
import time
from typing import Optional

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SMART KEYWORD MATCHER (no LLM needed — pure Python)
# ══════════════════════════════════════════════════════════════════════════════

def _score_prompt(prompt_row: dict, keyword: str, niche: str) -> int:
    """
    Prompt row ko keyword + niche ke saath score karo.
    Higher = better match.
    """
    score = 0
    kw_lower    = keyword.lower()
    niche_lower = niche.lower()

    # Niche affinity match
    niche_affinity = str(prompt_row.get("niche_affinity", "")).lower()
    if niche_lower in niche_affinity:
        score += 10

    # Style key or label match with keyword words
    style_key = str(prompt_row.get("style_key", "")).lower()
    label     = str(prompt_row.get("label", "")).lower()
    tags      = str(prompt_row.get("tags", "")).lower()

    for word in kw_lower.split():
        if len(word) < 4:
            continue
        if word in style_key:
            score += 3
        if word in label:
            score += 2
        if word in tags:
            score += 1

    return score


def _find_best_match(prompts: list, keyword: str, niche: str) -> Optional[dict]:
    """Pure scoring — no LLM call."""
    if not prompts:
        return None

    scored = [(p, _score_prompt(p, keyword, niche)) for p in prompts]
    scored.sort(key=lambda x: x[1], reverse=True)

    best_row, best_score = scored[0]
    if best_score > 0:
        logger.info(f"🎯 [PromptSelector] Best match score={best_score}: {str(best_row.get('label',''))[:50]}")
        return best_row

    # No keyword match — pick random from same niche
    niche_matched = [p for p in prompts if niche.lower() in str(p.get("niche_affinity", "")).lower()]
    if niche_matched:
        chosen = random.choice(niche_matched)
        logger.info(f"🎲 [PromptSelector] Random niche match: {str(chosen.get('label',''))[:50]}")
        return chosen

    # Total fallback — any random prompt
    chosen = random.choice(prompts)
    logger.info(f"🎲 [PromptSelector] Random fallback: {str(chosen.get('label',''))[:50]}")
    return chosen


# ══════════════════════════════════════════════════════════════════════════════
# SYNTHETIC PROMPT BUILDER (when Prompts_Master is empty)
# ══════════════════════════════════════════════════════════════════════════════

_NICHE_BACKDROPS = {
    "home":      "bright airy living room with natural light, white walls, wooden accents",
    "kitchen":   "clean modern kitchen countertop, marble surface, morning daylight",
    "cozy":      "warm cozy bedroom nook, soft blankets, ambient lighting, reading corner",
    "organize":  "neat organized shelf display, neutral tones, minimalist aesthetic",
    "tech":      "clean desk setup with dual monitors, RGB lighting, cable management",
    "gadgets":   "modern tech flat lay on concrete surface, dramatic side lighting",
    "budget":    "lifestyle product shot, clean white background, soft shadows",
    "phone":     "iPhone on aesthetic desk, marble surface, minimalist accessories",
    "smarthome": "smart home devices in modern living room, ambient glow, evening mood",
    "wfh":       "productive home office setup, large monitor, plants, morning light",
}


def _build_synthetic_prompt(keyword: str, niche: str) -> str:
    backdrop = _NICHE_BACKDROPS.get(niche, "clean modern interior, natural daylight")
    return (
        f"A beautifully styled {keyword} scene. {backdrop}. "
        f"Pinterest-worthy composition, lifestyle photography style, "
        f"bright soft window light, rule of thirds framing, "
        f"4K ultra HD, photorealistic, highly detailed, award-winning photography"
    )


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def select_best_prompt(keyword: str, niche: str = "home") -> str:
    """
    Keyword ke liye best image generation prompt return karo.

    Flow:
      1. Prompts_Master sheet load karo
      2. Keyword + niche se best match dhundho
      3. Matched row ka t2i_base field return karo
      4. Koi prompt nahi mila → synthetic prompt banao

    Args:
        keyword : Viral keyword (e.g. "aesthetic bedroom wall decor 2025")
        niche   : Board niche

    Returns:
        str — T2I prompt ready for image_creator.generate_pin_image()
    """
    prompts = []
    try:
        from sheets import get_prompts_master
        prompts = get_prompts_master()
        logger.info(f"📚 [PromptSelector] Prompts_Master: {len(prompts)} prompts loaded.")
    except Exception as e:
        logger.warning(f"⚠️ [PromptSelector] Sheet load failed: {e}")

    if prompts:
        best = _find_best_match(prompts, keyword, niche)
        if best:
            t2i = str(best.get("t2i_base", "")).strip()
            if t2i:
                logger.info(f"✅ [PromptSelector] Prompt selected ({len(t2i)} chars)")
                return t2i

    # Synthetic fallback
    synthetic = _build_synthetic_prompt(keyword, niche)
    logger.info(f"🔧 [PromptSelector] Synthetic prompt built: {synthetic[:80]}...")
    return synthetic
