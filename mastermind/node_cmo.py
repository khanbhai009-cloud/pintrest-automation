"""
mastermind/node_cmo.py — Node 2: CMO Mastermind

STRATEGY : 100% VIRAL_PIN — aesthetic AI-generated images only, zero affiliate/product content.
PRIMARY  : Gemini 2.5 Flash  (JSON mode forced via response_mime_type)
FALLBACK : Cerebras qwen-3-235b  (429 = no retry, skip to hardcoded immediately)
HARDCODED: Last-resort static strategy keeps pipeline alive

CMO reads analytics -> picks best performing Visual Style from 4 options -> outputs VIRAL_PIN.
Visual Styles: Green Minimalist Interior | Sunset Landscape | Cozy Aesthetic Architecture | Cinematic Retro Scenes
Ratio per pin: randomly chosen — 9:16 portrait OR 1:1 square
"""
import asyncio
import json
import logging
import random
import re

from config import CEREBRAS_API_KEY, CEREBRAS_CMO_MODEL, GEMINI_API_KEY, GEMINI_CMO_MODEL
from mastermind.state import MastermindState

logger = logging.getLogger(__name__)

# ── Gemini client ──────────────────────────────────────────────────────────────
try:
    from google import genai as _genai
    from google.genai import types as _gtypes
    _gemini_client = _genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None
except Exception:
    _gemini_client = None

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

# ── 4 Core Visual Styles — Analytics-driven selection by CMO ──────────────────
VISUAL_STYLES = {
    "green_minimalist": {
        "label":       "Green Minimalist Interior",
        "description": "Lush indoor plants, clean white/beige walls, minimal clutter, natural sunlight, organic textures, Scandinavian-biophilic fusion",
        "t2i_base":    "lush indoor plants, minimalist interior, white walls, natural sunlight, organic textures, neutral tones, scandinavian aesthetic, biophilic design",
        "tags":        ["GreenMinimalist", "BiophilicDesign", "MinimalistInterior", "IndoorPlants", "NaturalAesthetic"],
    },
    "sunset_landscape": {
        "label":       "Sunset Landscape",
        "description": "Golden hour landscapes, dramatic orange-pink skies, open horizons, silhouetted terrain, emotional and cinematic atmosphere",
        "t2i_base":    "golden hour landscape, dramatic sunset sky, orange pink hues, silhouette terrain, open horizon, cinematic nature, warm glow atmosphere",
        "tags":        ["SunsetVibes", "GoldenHour", "LandscapeAesthetic", "CinematicNature", "SunsetPhotography"],
    },
    "cozy_architecture": {
        "label":       "Cozy Aesthetic Architecture",
        "description": "Warm-lit interiors, wooden beams, stone details, plush textures, intimate reading nooks, hygge atmosphere",
        "t2i_base":    "cozy warm interior, wooden beams, stone fireplace, plush textures, ambient warm lighting, intimate nook, hygge atmosphere, architectural beauty",
        "tags":        ["CozyAesthetic", "HyggeHome", "CozyArchitecture", "WarmInterior", "CozyVibes"],
    },
    "cinematic_retro": {
        "label":       "Cinematic Retro Scenes",
        "description": "Film grain, vintage color grading, 35mm nostalgic urban or cafe scenes, warm amber tones, timeless mood",
        "t2i_base":    "film grain texture, vintage color grading, 35mm photography style, retro urban scene, warm amber tones, nostalgic mood, cinematic composition",
        "tags":        ["CinematicRetro", "VintageAesthetic", "FilmGrain", "RetroVibes", "CinematicMood"],
    },
}

# ── System prompts ─────────────────────────────────────────────────────────────
_SYSTEM_PROMPT = """\
You are an Elite Visual Art Director and Pinterest SEO Mastermind.
Your ONLY output is pure aesthetic AI-generated content — 100% VIRAL_PIN, zero products, zero affiliate links.
You read analytics to identify which of the 4 Visual Styles is resonating most, then craft a world-class pin for that style.

ABSOLUTE RULES (violating any = system failure):
1. Output ONLY a single valid JSON object. Zero prose, zero explanation.
2. pin_type MUST always be exactly: "VIRAL_PIN"
3. visual_prompt = comma-separated T2I keywords ONLY. No sentences. No brand names. No text in images.
4. visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed
5. Zero product names, zero prices, zero CTAs, zero affiliate signals anywhere.
6. Tags: CamelCase, no hashtag symbol, exactly 5 tags.
"""

_GEMINI_SYSTEM_INSTRUCTION = """\
You are an Elite Visual Art Director and Pinterest SEO Mastermind.
Your sole job: analyze analytics -> pick the best performing Visual Style -> return ONE valid VIRAL_PIN JSON strategy.

STRICT RULES:
- Output ONLY raw JSON. No markdown. No explanation. No text before or after the JSON.
- pin_type MUST always be exactly: "VIRAL_PIN" -- never "AFFILIATE_PIN".
- visual_prompt = comma-separated T2I image generation keywords only (no sentences, no brand names).
- visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed
- Zero product names, zero prices, zero CTAs anywhere in any field.
- Tags: CamelCase, no #, exactly 5 tags.
"""

# ── Account profiles ────────────────────────────────────────────────────────────
_ACCOUNT_PROFILES = {
    "account_1": (
        "ACCOUNT: HomeDecor & Lifestyle (account_1)\n"
        "Audience: Homemakers, interior design aspirants, nesting millennials — 18-45, female-skewed, USA/UK\n"
        "Tone: warm, sensory, aspirational — like a stylish friend sharing a beautiful discovery\n"
        "Goal: Maximum saves and impressions through pure aesthetic visual inspiration"
    ),
    "account_2": (
        "ACCOUNT: Tech & WFH (account_2)\n"
        "Audience: Tech enthusiasts, remote workers, creatives — 18-35, male-skewed, USA/India\n"
        "Tone: sharp, cinematic, premium — clean visuals that evoke focus and elevated taste\n"
        "Goal: Maximum saves and impressions through pure aesthetic visual inspiration"
    ),
}

# NOTE: Gemini uses response_mime_type='application/json' + system_instruction param.
# Cerebras gets system role message. Neither path duplicates the system prompt in user content.

# ── Hardcoded last-resort fallbacks — always VIRAL_PIN, one of the 4 styles ───
HARDCODED_FALLBACK: dict = {
    "account_1": {
        "pin_type":      "VIRAL_PIN",
        "strategy":      "Cozy Architecture Fallback",
        "visual_style":  "cozy_architecture",
        "vibe":          "Warm-lit cozy interior, wooden beams, stone fireplace, hygge atmosphere",
        "title":         "This Cozy Space Will Make You Want to Stay Forever",
        "description":   "There's a warmth here that feels almost impossible to leave. Wooden beams overhead, the soft crackle of a fire, textures that beg to be touched. This is what home is supposed to feel like.",
        "tags":          ["CozyAesthetic", "HyggeHome", "CozyArchitecture", "WarmInterior", "CozyVibes"],
        "visual_prompt": "cozy warm interior, wooden beams, stone fireplace, plush wool textures, amber candlelight, intimate reading nook, hygge atmosphere, architectural beauty, hyperrealistic, 4K ultra HD, photorealistic, highly detailed",
        "ratio":         "9:16",
    },
    "account_2": {
        "pin_type":      "VIRAL_PIN",
        "strategy":      "Cinematic Retro Fallback",
        "visual_style":  "cinematic_retro",
        "vibe":          "35mm film grain, vintage amber tones, nostalgic cinematic urban scene",
        "title":         "This Cinematic Scene Feels Like a Forgotten Dream",
        "description":   "Some moments deserve to be frozen in film. Warm amber light bleeding through dusty windows, the kind of stillness that makes time feel different. Vintage never goes out of style — it only deepens.",
        "tags":          ["CinematicRetro", "VintageAesthetic", "FilmGrain", "RetroVibes", "CinematicMood"],
        "visual_prompt": "film grain texture, vintage color grading, 35mm photography style, retro urban cafe scene, warm amber tones, nostalgic mood, soft bokeh, cinematic composition, hyperrealistic, 4K ultra HD, photorealistic, highly detailed",
        "ratio":         "9:16",
    },
}

# ── Prompt builder — always VIRAL_PIN, CMO picks best visual style from analytics ──
def _build_viral_prompt(profile: str, metrics_str: str, ratio: str) -> str:
    ratio_cfg  = _RATIOS[ratio]
    styles_str = json.dumps(
        {k: {"label": v["label"], "description": v["description"], "t2i_base": v["t2i_base"]}
         for k, v in VISUAL_STYLES.items()},
        indent=2
    )
    return f"""TASK: Generate a VIRAL_PIN strategy. Analyze analytics to select the best performing Visual Style, then craft a world-class aesthetic pin for it.

ACCOUNT PROFILE
{profile}

PERFORMANCE ANALYTICS (last 30 days)
{metrics_str}

4 VISUAL STYLES (pick the one best matching current analytics momentum)
{styles_str}

PIN SPECIFICATIONS
Image ratio: {ratio_cfg['label']} ({ratio_cfg['w']}x{ratio_cfg['h']}px)
Pin type: VIRAL_PIN -- 100% aesthetic AI-generated image, zero products, zero links

CREATIVE DIRECTION
1. STYLE SELECTION: Study the analytics. Pick the Visual Style gaining momentum or best fitting the account audience. If analytics are stagnant, pivot to a different style.
2. VISUAL ART DIRECTION: Expand the t2i_base of the chosen style into a hyper-specific T2I prompt. Add: lighting conditions, materials, textures, camera angle, mood, color temperature. No text overlays.
3. COPYWRITING: Write like an elite lifestyle photographer sharing a discovery. Evoke emotion and sensory detail. No prices, no CTAs, no product mentions.
4. TITLE: Lead with the strongest emotional or sensory hook. Make it feel like a discovery.

OUTPUT FORMAT (JSON only -- no other text)
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "Visual Style Pivot",
  "visual_style": "<key: green_minimalist | sunset_landscape | cozy_architecture | cinematic_retro>",
  "vibe": "<1-line mood direction for this specific pin, max 80 chars>",
  "title": "<emotionally compelling, curiosity-driven, max 90 chars>",
  "description": "<sensory lifestyle copy, 2-3 sentences, zero products/CTAs/prices, max 380 chars>",
  "tags": ["<Tag1>", "<Tag2>", "<Tag3>", "<Tag4>", "<Tag5>"],
  "visual_prompt": "<expanded T2I keywords from chosen style's t2i_base, hyper-specific, ends with: 4K ultra HD, photorealistic, highly detailed>",
  "ratio": "{ratio}"
}}"""


# ── Helpers ────────────────────────────────────────────────────────────────────
def _choose_pin_type() -> str:
    """Always VIRAL_PIN — 100% visual strategy, no affiliate routing."""
    return "VIRAL_PIN"


def _extract_json(raw: str) -> dict:
    """
    Robustly extract JSON from model output.
    Handles: markdown fences, leading/trailing text, whitespace, truncated responses.
    """
    cleaned  = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start    = cleaned.find("{")
    end      = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found. Raw: {cleaned[:200]}")
    json_str = cleaned[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON parse failed: {e}. Extracted: {json_str[:300]}")


def _validate(result: dict, account_key: str) -> None:
    required = ("pin_type", "strategy", "vibe", "title", "description", "tags", "visual_prompt")
    for field in required:
        if field not in result:
            raise KeyError(f"Missing '{field}' in CMO response for {account_key}.")
    if result.get("pin_type") != "VIRAL_PIN":
        raise ValueError(f"CMO returned non-VIRAL_PIN for {account_key} — forcing override.")


# ── Gemini call (primary) ──────────────────────────────────────────────────────
def _call_gemini_sync(prompt: str) -> str:
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY not configured.")
    response = _gemini_client.models.generate_content(
        model=GEMINI_CMO_MODEL,
        contents=prompt,
        config=_gtypes.GenerateContentConfig(
            system_instruction=_GEMINI_SYSTEM_INSTRUCTION,
            temperature=0.75,
            max_output_tokens=6000,
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
            temperature=0.75,
            max_tokens=6000,
        )
        return response.choices[0].message.content
    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "rate" in err_str.lower():
            raise RuntimeError(f"Cerebras rate-limited (429) — aborting: {e}") from e
        raise


# ── Main per-account orchestration — always VIRAL_PIN ─────────────────────────
def _call_cmo_for_account(account_key: str, metrics: dict, pin_type_override: str = None) -> dict:
    # pin_type_override is ignored — 100% visual strategy forces VIRAL_PIN always
    pin_type    = "VIRAL_PIN"
    ratio       = _pick_ratio()
    profile     = _ACCOUNT_PROFILES[account_key]
    metrics_str = json.dumps(metrics, indent=2)

    logger.info(f"   [{account_key}] pin=VIRAL_PIN | ratio={ratio}")

    prompt = _build_viral_prompt(profile, metrics_str, ratio)

    # PRIMARY: Gemini
    try:
        logger.info(f"   [{account_key}] Gemini (primary)...")
        raw    = _call_gemini_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["pin_type"] = "VIRAL_PIN"  # enforce even if model drifts
        result["ratio"]    = result.get("ratio", ratio)
        logger.info(f"   [{account_key}] Gemini succeeded | style={result.get('visual_style', '?')}")
        return result
    except Exception as gemini_err:
        logger.warning(f"   [{account_key}] Gemini failed: {gemini_err}")

    # FALLBACK: Cerebras (skip if 429)
    try:
        logger.info(f"   [{account_key}] Cerebras fallback...")
        raw    = _call_cerebras_sync(prompt)
        result = _extract_json(raw)
        _validate(result, account_key)
        result["pin_type"] = "VIRAL_PIN"  # enforce
        result["ratio"]    = result.get("ratio", ratio)
        logger.info(f"   [{account_key}] Cerebras succeeded | style={result.get('visual_style', '?')}")
        return result
    except RuntimeError as rate_err:
        logger.warning(f"   [{account_key}] {rate_err}")
        raise
    except Exception as cerebras_err:
        logger.warning(f"   [{account_key}] Cerebras failed: {cerebras_err}")
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

    imp      = _avg("Impressions")
    clicks   = _avg("Clicks")
    saves    = _avg("Saves")
    outbound = _avg("Outbound Clicks")

    if imp > 5000 and clicks < 100 and saves < 100:
        profile = "High-Impression / Low-Engagement"
    elif clicks > 200 or saves > 200:
        profile = "High-Engagement / Conversion-Ready"
    else:
        profile = "Stagnant"

    return {
        "impressions_avg": imp,
        "clicks_avg":      clicks,
        "outbound_avg":    outbound,
        "saves_avg":       saves,
        "profile":         profile,
    }


# ── LangGraph node ─────────────────────────────────────────────────────────────
async def node_cmo_mastermind(state: MastermindState) -> dict:
    """
    Node 2 — CMO Mastermind.
    Always VIRAL_PIN. CMO reads analytics, picks best Visual Style, generates content.
    Primary: Gemini | Fallback: Cerebras | Last resort: hardcoded strategy
    """
    trigger = state.get("cycle_trigger", "")

    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    label = "A1 only" if only_a1 else ("A2 only" if only_a2 else "Both")
    logger.info(f"[Node 2 - CMO] 100% VIRAL_PIN | {label} | trigger={trigger}")

    a1_metrics = _compute_metrics(state["a1_raw_analytics"])
    a2_metrics = _compute_metrics(state["a2_raw_analytics"])
    fallback   = False

    # Account 1
    if run_a1:
        logger.info(f"   A1 analytics profile: {a1_metrics['profile']}")
        try:
            a1_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_1", a1_metrics)
            logger.info(f"[Node 2] A1 -> VIRAL_PIN | style={a1_strategy.get('visual_style', '?')} | ratio={a1_strategy.get('ratio', '9:16')}")
        except Exception as e:
            logger.error(f"[Node 2] All CMO models failed for A1: {e}. Using hardcoded fallback.")
            a1_strategy = HARDCODED_FALLBACK["account_1"]
            fallback = True
    else:
        a1_strategy = {}

    # Account 2
    if run_a2:
        logger.info(f"   A2 analytics profile: {a2_metrics['profile']}")
        try:
            a2_strategy = await asyncio.to_thread(_call_cmo_for_account, "account_2", a2_metrics)
            logger.info(f"[Node 2] A2 -> VIRAL_PIN | style={a2_strategy.get('visual_style', '?')} | ratio={a2_strategy.get('ratio', '9:16')}")
        except Exception as e:
            logger.error(f"[Node 2] All CMO models failed for A2: {e}. Using hardcoded fallback.")
            a2_strategy = HARDCODED_FALLBACK["account_2"]
            fallback = True
    else:
        a2_strategy = {}

    return {
        "a1_cmo_strategy":    a1_strategy,
        "a2_cmo_strategy":    a2_strategy,
        "fallback_triggered": fallback,
    }
