"""
mastermind/node_copy.py — Node 3: Fast Copywriters (Groq → Cerebras → Local Templates)
Generates Pinterest-optimised titles, descriptions, and hashtags per account.
Accounts are treated as completely separate brands — no copy leaks between them.

Fallback chain (per account, independently):
  1. Groq (llama-3.3-70b-versatile)  — primary, fastest
  2. Cerebras (llama3.3-70b)          — auto-fallback on Groq failure
  3. Local niche templates            — guaranteed non-empty, last resort
"""
import json
import logging
import re

from cerebras.cloud.sdk import Cerebras
from groq import Groq

from config import CEREBRAS_API_KEY, CEREBRAS_MODEL, GROQ_API_KEY, GROQ_MODEL
from mastermind.state import MastermindState
from mastermind.templates import LOCAL_TEMPLATES

logger = logging.getLogger(__name__)

# ── Client singletons (safe for missing keys) ─────────────────────────────────
_groq = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
_cerebras = Cerebras(api_key=CEREBRAS_API_KEY) if CEREBRAS_API_KEY else None

# ── Prompt template ────────────────────────────────────────────────────────────
_COPY_PROMPT = """You are a world-class Pinterest SEO copywriter specialising in {niche_description}.

STRATEGY BRIEF FROM CMO:
  Strategy: {strategy}
  Brand Vibe: {vibe}
  Visual Concept: {image_prompt}

Generate high-converting Pinterest pin content that matches this exact brief.

TITLE RULES (critical for Pinterest SEO):
  - Max 100 characters. Primary keyword MUST come first.
  - Use power words: "genius", "life-changing", "under $20", "you need this"
  - Create curiosity or immediate value. No misleading clickbait.

DESCRIPTION RULES:
  - Max 500 characters. Open with the core benefit, weave in 2-3 long-tail keywords.
  - Include a clear CTA: "Shop via link in bio" or "Grab it before it sells out"
  - 2-4 strategic emojis — not spammy.

HASHTAG RULES:
  - Exactly 5 niche-specific hashtags (return as plain words, no # symbol).
  - Mix: 1 broad niche + 2 specific + 2 trending style.

TONE: Aspirational, trusted friend, global English (US/UK/AU audience).

Respond ONLY with raw valid JSON — no markdown, no code fences:
{{"title": "...", "description": "...", "tags": ["tag1","tag2","tag3","tag4","tag5"]}}"""


def _extract_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in copy response.")
    parsed = json.loads(cleaned[start:end])
    # Validate required fields exist and are non-empty
    for field in ("title", "description", "tags"):
        if not parsed.get(field):
            raise ValueError(f"Field '{field}' is empty in copy response.")
    return parsed


def _call_groq(messages: list) -> str:
    if not _groq:
        raise ValueError("Groq client not initialised — GROQ_API_KEY missing.")
    resp = _groq.chat.completions.create(
        model=GROQ_MODEL,
        messages=messages,
        temperature=0.75,
        timeout=20,
    )
    return resp.choices[0].message.content


def _call_cerebras(messages: list) -> str:
    if not _cerebras:
        raise ValueError("Cerebras client not initialised — CEREBRAS_API_KEY missing.")
    resp = _cerebras.chat.completions.create(
        model=CEREBRAS_MODEL,
        messages=messages,
        temperature=0.75,
    )
    return resp.choices[0].message.content


def _generate_copy(
    prompt: str,
    account_label: str,
    fallback_niche: str,
) -> dict:
    """
    Groq → Cerebras → Local template fallback chain.
    Guaranteed to return a dict with title, description, and tags.
    """
    messages = [{"role": "user", "content": prompt}]

    # ── 1. Try Groq ─────────────────────────────────────────────────────────
    try:
        raw = _call_groq(messages)
        copy = _extract_json(raw)
        logger.info(f"✅ [Node 3 — Groq] [{account_label}] '{copy['title'][:60]}'")
        return copy
    except Exception as e:
        logger.warning(f"⚠️ [Node 3] [{account_label}] Groq failed: {e} — trying Cerebras.")

    # ── 2. Try Cerebras ──────────────────────────────────────────────────────
    try:
        raw = _call_cerebras(messages)
        copy = _extract_json(raw)
        logger.info(f"✅ [Node 3 — Cerebras] [{account_label}] '{copy['title'][:60]}'")
        return copy
    except Exception as e:
        logger.warning(
            f"⚠️ [Node 3] [{account_label}] Cerebras failed: {e} — using local template."
        )

    # ── 3. Local template — never returns empty ──────────────────────────────
    template = LOCAL_TEMPLATES.get(fallback_niche, LOCAL_TEMPLATES["default"])
    logger.info(f"✅ [Node 3 — Template] [{account_label}] niche='{fallback_niche}' applied.")
    return template


def _build_copy_for_account(
    account_label: str,
    strategy: dict,
    niche_description: str,
    primary_niche: str,
) -> dict:
    image_prompt = (strategy.get("image_prompts") or ["aesthetic product photo"])[0]
    prompt = _COPY_PROMPT.format(
        niche_description=niche_description,
        strategy=strategy.get("strategy", "Visual Pivot / High-Aesthetic Bait"),
        vibe=strategy.get("vibe", "Aspirational and aesthetic"),
        image_prompt=image_prompt,
    )
    return _generate_copy(prompt, account_label, primary_niche)


def node_fast_copywriters(state: MastermindState) -> dict:
    """
    Node 3 — Fast Copywriters.
    Generates isolated SEO copy for each account using the CMO strategy.
    Account 1 (HomeDecor) and Account 2 (Tech) never share copy.
    """
    logger.info("✍️  [Node 3 — Fast Copywriters] Generating SEO copy for both accounts...")

    # ── Account 1 — HomeDecor ────────────────────────────────────────────────
    a1_copy = _build_copy_for_account(
        account_label="Account1 HomeDecor",
        strategy=state["a1_cmo_strategy"],
        niche_description="Home Decor, Kitchen Gadgets, Cozy Living, Smart Home Gadgets, Organisation",
        primary_niche="home",
    )

    # ── Account 2 — Tech ────────────────────────────────────────────────────
    a2_copy = _build_copy_for_account(
        account_label="Account2 Tech",
        strategy=state["a2_cmo_strategy"],
        niche_description="Tech Gadgets, Budget Electronics, Phone Accessories, Smart Home, Work From Home",
        primary_niche="tech",
    )

    return {
        "a1_final_seo_copy": a1_copy,
        "a2_final_seo_copy": a2_copy,
    }
