"""
mastermind/node_cmo.py — Node 2: CMO Mastermind

PRIMARY  : Gemini 2.5 Flash  (JSON mode forced via response_mime_type)
FALLBACK : Cerebras qwen-3-235b  (429 = no retry, skip to hardcoded immediately)
HARDCODED: Last-resort static strategy keeps pipeline alive

Ratio per pin: randomly chosen — 9:16 portrait OR 1:1 square
"""
import asyncio
import json
import logging
import random
import re

from config import CEREBRAS_API_KEY, CEREBRAS_CMO_MODEL, GEMINI_API_KEY
from mastermind.state import MastermindState

logger = logging.getLogger(__name__)

# ── Gemini client ──────────────────────────────────────────────────────────────
try:
    from google import genai as _genai
    from google.genai import types as _gtypes
    _gemini_client = _genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except Exception:
    _gemini_client = None

_GEMINI_CMO_MODEL = "gemini-2.5-flash"

# ── Cerebras client ────────────────────────────────────────────────────────────
try:
    from cerebras.cloud.sdk import Cerebras as _Cerebras
    _cerebras_client = _Cerebras(api_key=CEREBRAS_API_KEY) if CEREBRAS_API_KEY else None
except Exception:
    _cerebras_client = None

# ── Image ratio config ─────────────────────────────────────────────────────────
_RATIOS = {
    "9:16": {"label": "9:16 tall portrait", "w": 1080, "h": 1920},
    "1:1":  {"label": "1:1 square",          "w": 1080, "h": 1080},
}

def _pick_ratio() -> str:
    """70% portrait (9:16), 30% square (1:1) — both perform well on Pinterest."""
    return random.choices(["9:16", "1:1"], weights=[70, 30], k=1)[0]

# ── Hardcoded last-resort fallbacks ───────────────────────────────────────────
HARDCODED_FALLBACK: dict = {
    "account_1": {
        "pin_type":     "VIRAL_PIN",
        "strategy":     "Visual Pivot",
        "vibe":         "Warm luxe kitchen — ASMR marble flatlay, golden hour glow",
        "title":        "Cozy Home Aesthetic That Will Transform Your Space ✨",
        "description":  "Create the most satisfying, organised home with these gorgeous finds. Pure aesthetic bliss for your Pinterest feed.",
        "tags":         ["HomeAesthetic", "CozyHome", "HomeOrganization", "KitchenGoals", "HomeDecor"],
        "visual_prompt": "cozy kitchen flatlay, marble countertop, golden hour lighting, warm tones, ASMR aesthetic, hyperrealistic, 4K ultra HD",
        "ratio":        "9:16",
    },
    "account_2": {
        "pin_type":     "VIRAL_PIN",
        "strategy":     "Visual Pivot",
        "vibe":         "Apple-style glassmorphism desk — ultra-clean premium tech",
        "title":        "Minimal WFH Setup That Looks Like a $10K Studio 🖥️",
        "description":  "The cleanest desk setup inspiration for your home office. Frosted glass, gradient light, premium precision.",
        "tags":         ["WFHSetup", "DeskSetup", "TechAesthetic", "HomeOffice", "MinimalDesk"],
        "visual_prompt": "Apple glassmorphism desk setup, frosted glass panels, smarthome hub, blue-purple gradient, cinematic lighting, 4K ultra HD",
        "ratio":        "9:16",
    },
}

# ── Account profiles ───────────────────────────────────────────────────────────
_ACCOUNT_PROFILES = {
    "account_1": (
        "Account 1 — HomeDecor & Lifestyle\n"
        "Niches : home, kitchen, cozy, gadgets, organize\n"
        "Aesthetic: ASMR / Luxury warm — marble, gold tones, flatlay, warm lighting\n"
        "Audience : Homemakers, interior design fans, 18-45 female-skewed USA/UK"
    ),
    "account_2": (
        "Account 2 — Tech & WFH\n"
        "Niches : tech, budget, phone, smarthome, wfh\n"
        "Aesthetic: Apple Glassmorphism — frosted glass, minimal, blue-purple gradients\n"
        "Audience : Tech enthusiasts, remote workers, 18-35 male-skewed USA/India"
    ),
}

# ── System prompt (shared) ─────────────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "You are the CMO of PINTERESTO — a fully autonomous Pinterest affiliate marketing AI.\n"
    "Your output feeds directly into an image generation pipeline and Pinterest posting engine.\n\n"
    "RULES:\n"
    "- Respond ONLY with a valid JSON object. No markdown, no explanation, no extra text.\n"
    "- visual_prompt must be clean comma-separated keywords — no sentences.\n"
    "- Always append ', 4K ultra HD, photorealistic' at the end of visual_prompt.\n"
    "- Pinterest algorithm loves: keyword-rich titles, aspirational lifestyle copy, fresh aesthetics.\n"
    "- VIRAL_PIN: pure aesthetic, no product names, no CTAs, no prices.\n"
    "- AFFILIATE_PIN: authentic recommendation tone, 1-2 real benefits, soft CTA at end.\n"
)

# ── Pin type prompts ───────────────────────────────────────────────────────────
def _build_viral_prompt(profile: str, metrics_str: str, ratio: str) -> str:
    ratio_cfg = _RATIOS[ratio]
    return f"""{_SYSTEM_PROMPT}
TASK: VIRAL_PIN strategy — maximum saves and impressions.

ACCOUNT:
{profile}

ANALYTICS (last 30 days):
{metrics_str}

IMAGE RATIO: {ratio_cfg['label']} ({ratio_cfg['w']}x{ratio_cfg['h']}px)

OUTPUT FORMAT (JSON only):
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "Visual Pivot",
  "vibe": "<1-line aesthetic direction, max 80 chars>",
  "title": "<SEO title, primary keyword first, max 90 chars>",
  "description": "<lifestyle copy, max 380 chars, NO product names, NO CTAs, NO prices>",
  "tags": ["<tag1>", "<tag2>", "<tag3>", "<tag4>", "<tag5>"],
  "visual_prompt": "<comma-separated T2I keywords, max 180 chars, ends with: 4K ultra HD, photorealistic>",
  "ratio": "{ratio}"
}}"""


def _build_affiliate_prompt(profile: str, metrics_str: str, ratio: str) -> str:
    ratio_cfg = _RATIOS[ratio]
    return f"""{_SYSTEM_PROMPT}
TASK: AFFILIATE_PIN strategy — drive outbound clicks and conversions.

ACCOUNT:
{profile}

ANALYTICS (last 30 days):
{metrics_str}

IMAGE RATIO: {ratio_cfg['label']} — raw product photo will be used (no AI image).

OUTPUT FORMAT (JSON only):
{{
  "pin_type": "AFFILIATE_PIN",
  "strategy": "Affiliate Strike",
  "vibe": "<authentic product rec tone, max 80 chars>",
  "title": "<benefit/price hook first, max 90 chars>",
  "description": "<genuine rec, 1-2 specific benefits, ends with: Link in bio 🔗, max 380 chars>",
  "tags": ["<tag1>", "<tag2>", "<tag3>", "<tag4>", "<tag5>"],
  "visual_prompt": "NONE",
  "ratio": "{ratio}"
}}"""


# ── Helpers ────────────────────────────────────────────────────────────────────
def _choose_pin_type() -> str:
    return random.choices(["VIRAL_PIN", "AFFILIATE_PIN"], weights=[70, 30], k=1)[0]


def _extract_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found. Raw: {cleaned[:200]}")
    return json.loads(cleaned[start:end])


def _validate(result: dict, account_key: str) -> None:
    required = ("pin_type", "strategy", "vibe", "title", "description", "tags", "visual_prompt")
    for field in required:
        if field not in result:
            raise KeyError(f"Missing '{field}' in CMO response for {account_key}.")


# ── Gemini call (primary) ──────────────────────────────────────────────────────
def _call_gemini_sync(prompt: str) -> str:
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY not configured.")
    response = _gemini_client.models.generate_content(
        model=_GEMINI_CMO_MODEL,
        contents=prompt,
        config=_gtypes.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            temperature=0.35,
            max_output_tokens=800,
            response_mime_type="application/json",
        ),
    )
    return response.text.strip()


# ── Cerebras call (fallback — 429 = immediate abort, no retry) ────────────────
def _call_cerebras_sync(prompt: str) -> str:
    if not _cerebras_client:
        raise ValueError("CEREBRAS_API_KEY not configured.")
    try:
        response = _cerebras_client.chat.completions.create(
            model=CEREBRAS_CMO_MODEL,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            temperature=0.35,
            max_tokens=800,
        )
        return response.choices[0].message.content
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate" in err_str.lower():
            raise RuntimeError(f"Cerebras rate-limited (429) — aborting: {e}") from e
        raise


# ── Main per-account orchestration ────────────────────────────────────────────
def _call_cmo_for_account(account_key: str, metrics: dict, pin_type_override: str = None) -> dict:
    pin_type = (
        pin_type_override
        if pin_type_override in ("VIRAL_PIN", "AFFILIATE_PIN")
        else _choose_pin_type()
    )
    ratio       = _pick_ratio()
    profile     = _ACCOUNT_PROFILES[account_key]
    metrics_str = json.dumps(metrics, indent=2)

    logger.info(f"   [{account_key}] pin={pin_type} | ratio={ratio}")

    prompt = (
        _build_viral_prompt(profile, metrics_str, ratio)
        if pin_type == "VIRAL_PIN"
        else _build_affiliate_prompt(profile, metrics_str, ratio)
    )

    # PRIMARY: Gemini 2.5 Flash
    try:
        logger.info(f"   [{account_key}] 🧠 Gemini 2.5 Flash (primary)...")
        raw    = _call_gemini_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["ratio"] = result.get("ratio", ratio)
        logger.info(f"   [{account_key}] ✅ Gemini succeeded")
        return result
    except Exception as gemini_err:
        logger.warning(f"   [{account_key}] ⚠️ Gemini failed: {gemini_err}")

    # FALLBACK: Cerebras (skip if 429)
    try:
        logger.info(f"   [{account_key}] 🔄 Cerebras fallback...")
        raw    = _call_cerebras_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["ratio"] = result.get("ratio", ratio)
        logger.info(f"   [{account_key}] ✅ Cerebras succeeded")
        return result
    except RuntimeError as rate_err:
        logger.warning(f"   [{account_key}] 🚫 {rate_err}")
        raise
    except Exception as cerebras_err:
        logger.warning(f"   [{account_key}] ⚠️ Cerebras failed: {cerebras_err}")
        raise


# ── Metrics helper ─────────────────────────────────────────────────────────────
def _compute_metrics(rows: list) -> dict:
    is_stagnant = not rows or rows[0].get("Date") == "fallback"
    if is_stagnant:
        return {"impressions_avg": 0, "clicks_avg": 0, "outbound_avg": 0, "saves_avg": 0, "profile": "Stagnant"}

    def _avg(key: str) -> float:
        vals = []
        for r in rows:
            raw = r.get(key, 0)
            try:
                vals.append(float(str(raw).replace(",", "") or 0))
            except (ValueError, TypeError):
                vals.append(0.0)
        return round(sum(vals) / len(vals), 1) if vals else 0.0

    imp     = _avg("Impressions")
    clicks  = _avg("Clicks")
    saves   = _avg("Saves")
    outbound = _avg("Outbound Clicks")

    if imp > 5000 and clicks < 100 and saves < 100:
        profile = "High-Impression / Low-Engagement"
    elif clicks > 200 or saves > 200:
        profile = "High-Engagement / Conversion-Ready"
    else:
        profile = "Stagnant"

    return {
        "impressions_avg": imp,
        "clicks_avg": clicks,
        "outbound_avg": outbound,
        "saves_avg": saves,
        "profile": profile,
    }


# ── LangGraph node ─────────────────────────────────────────────────────────────
async def node_cmo_mastermind(state: MastermindState) -> dict:
    """
    Node 2 — CMO Mastermind.
    Primary: Gemini 2.5 Flash (JSON mode)
    Fallback: Cerebras (429 → skip immediately)
    Last resort: hardcoded strategy
    """
    trigger = state.get("cycle_trigger", "")

    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    a1_override = None
    a2_override = None
    if "VIRAL_PIN" in trigger:
        if only_a1: a1_override = "VIRAL_PIN"
        elif only_a2: a2_override = "VIRAL_PIN"
    elif "AFFILIATE_PIN" in trigger:
        if only_a1: a1_override = "AFFILIATE_PIN"
        elif only_a2: a2_override = "AFFILIATE_PIN"

    label = "A1 only" if only_a1 else ("A2 only" if only_a2 else "Both")
    logger.info(f"🧠 [Node 2 — CMO] Gemini→Cerebras | {label} | trigger={trigger}")

    a1_metrics = _compute_metrics(state["a1_raw_analytics"])
    a2_metrics = _compute_metrics(state["a2_raw_analytics"])
    fallback   = False

    # Account 1
    if run_a1:
        logger.info(f"   A1 profile: {a1_metrics['profile']}")
        try:
            a1_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_1", a1_metrics, a1_override)
            logger.info(f"✅ [Node 2] A1 → {a1_strategy['pin_type']} | ratio={a1_strategy.get('ratio','9:16')}")
        except Exception as e:
            logger.error(f"❌ [Node 2] All CMO models failed for A1: {e}. Using hardcoded fallback.")
            a1_strategy = HARDCODED_FALLBACK["account_1"]
            fallback = True
    else:
        a1_strategy = {}

    # Account 2
    if run_a2:
        logger.info(f"   A2 profile: {a2_metrics['profile']}")
        try:
            a2_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_2", a2_metrics, a2_override)
            logger.info(f"✅ [Node 2] A2 → {a2_strategy['pin_type']} | ratio={a2_strategy.get('ratio','9:16')}")
        except Exception as e:
            logger.error(f"❌ [Node 2] All CMO models failed for A2: {e}. Using hardcoded fallback.")
            a2_strategy = HARDCODED_FALLBACK["account_2"]
            fallback = True
    else:
        a2_strategy = {}

    return {
        "a1_cmo_strategy":    a1_strategy,
        "a2_cmo_strategy":    a2_strategy,
        "fallback_triggered": fallback,
    }
