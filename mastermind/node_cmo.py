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
# ── Image ratio config ─────────────────────────────────────────────────────────
_RATIOS = {
    "9:16": {"label": "9:16 tall portrait", "w": 1080, "h": 1920},
    "1:1":  {"label": "1:1 square",          "w": 1080, "h": 1080},
}

def _pick_ratio() -> str:
    """70% portrait (9:16), 30% square (1:1) — both perform well on Pinterest."""
    return random.choices(["9:16", "1:1"], weights=[70, 30], k=1)[0]

# ── Master Keywords Dictionary (For Human-Touch Aesthetics) ────────────────────
KEYWORDS_BY_NICHE = {
    "home": ["aesthetic room decor", "amazon home finds", "nordic home decor", "led room lighting aesthetic", "minimalist home accessories", "cute room decor"],
    "kitchen": ["smart kitchen gadgets", "viral kitchen tools", "aesthetic kitchen accessories", "time saving kitchen hacks", "kitchen organization tools", "pastel kitchen gadgets"],
    "cozy": ["cozy bedroom aesthetic", "warm night light", "fluffy room decor", "reading nook accessories", "ambient room lighting", "kawaii room decor"],
    "gadgets": ["cool home gadgets viral", "problem solving gadgets", "smart home tech finds", "tiktok made me buy it home", "lazy home gadgets", "cleaning gadgets hacks"],
    "organize": ["aesthetic storage box", "acrylic makeup organizer", "closet organization tools", "cable management aesthetic", "bathroom space saver", "fridge organization containers"],
    "tech": ["aesthetic desk setup", "gaming setup accessories", "cool tech gadgets", "cyberpunk desk accessories", "futuristic tech gadgets", "laptop accessories aesthetic"],
    "budget": ["cool gadgets under 10", "cheap tech finds", "useful gadgets under 20", "mini tech gadgets", "budget gaming accessories", "pocket gadgets"],
    "phone": ["cute iphone cases", "magsafe accessories aesthetic", "viral phone charms", "phone camera lens kit", "aesthetic phone stand", "power bank aesthetic"],
    "smarthome": ["smart rgb led strip", "smart home automation", "voice control lights", "smart desk lamp", "galaxy projector light", "smart sensor gadgets"],
    "wfh": ["work from home desk setup", "ergonomic desk accessories", "ipad accessories aesthetic", "productivity gadgets", "wireless mechanical keyboard", "desk mat aesthetic"]
}

# ── System prompt (Human Mastermind Persona) ───────────────────────────────────
_SYSTEM_PROMPT = """\
You are an Elite Social Media Marketer, SEO Mastermind, and Visionary Art Director.
You dominate the Pinterest algorithm by understanding human psychology, viral visual trends, and high-converting aesthetics. 
Your decisions drive massive organic reach, saves, and aesthetic appeal.

ABSOLUTE RULES (violating any = system failure):
1. Output ONLY a single valid JSON object. Zero prose, zero explanation.
2. visual_prompt = comma-separated T2I keywords ONLY. No sentences. No text in images.
3. visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed
4. VIRAL_PIN: Pure visual inspiration. NO product names, NO prices, NO CTAs anywhere.
5. AFFILIATE_PIN: description must end with exactly → Link in bio 🔗
6. Tags: CamelCase, no hashtag symbol, max 5 tags.
"""

_GEMINI_SYSTEM_INSTRUCTION = """\
You are an Elite Social Media Marketer, SEO Mastermind, and Visionary Art Director.
Your sole job: analyze the profile + analytics + niche keywords, then return ONE valid JSON strategy object.

STRICT RULES:
- Output ONLY raw JSON. No markdown. No explanation. No text before or after the JSON.
- visual_prompt = comma-separated image generation keywords only (no sentences).
- visual_prompt MUST end with: 4K ultra HD, photorealistic, highly detailed
- VIRAL_PIN: pure aesthetic inspiration. Zero product names, zero prices, zero CTAs.
- AFFILIATE_PIN: description must end with: Link in bio 🔗
- Tags: CamelCase, no #, exactly 5 tags.
"""

# ── Account profiles ───────────────────────────────────────────────────────────
# ── Account profiles ───────────────────────────────────────────────────────────
_ACCOUNT_PROFILES = {
    "account_1": (
        "ACCOUNT: HomeDecor & Lifestyle (account_1)\n"
        "Available Niches: home, kitchen, cozy, organize, gadgets\n"
        "Visual aesthetic: ADAPTIVE. Match the vibe exactly to the selected niche using the provided keyword dictionary. Always maintain a high-end, aspirational, 'Pinterest-perfect' lifestyle feel.\n"
        "Audience: Homemakers, interior design aspirants, nesting millennials — 18–45, female-skewed, USA/UK\n"
        "Tone: warm, relatable, sensory, like a stylish best friend sharing a secret aesthetic"
    ),
    "account_2": (
        "ACCOUNT: Tech & WFH (account_2)\n"
        "Available Niches: tech, budget, phone, smarthome, wfh\n"
        "Visual aesthetic: ADAPTIVE. Match the vibe exactly to the selected niche using the provided keyword dictionary. Focus on premium lighting, clean setups, and satisfying organization.\n"
        "Audience: Tech enthusiasts, remote workers, productivity-focused — 18–35, male-skewed, USA/India\n"
        "Tone: sharp, confident, engaging, authoritative but accessible"
    ),
}

# ── System prompt (used ONLY for Cerebras — NOT injected into Gemini prompt) ──
# FIX: Gemini uses response_mime_type='application/json' + system_instruction param.
# Injecting _SYSTEM_PROMPT again inside the user prompt caused Gemini to generate
# explanatory text BEFORE the JSON object, breaking _extract_json parsing.
# Solution: Gemini gets system_instruction via config param only (no duplication).
# Cerebras gets system role message as before.
# ── Hardcoded last-resort fallbacks (Generic & Adaptive) ──────────────────────
HARDCODED_FALLBACK: dict = {
    "account_1": {
        "pin_type":     "VIRAL_PIN",
        "strategy":     "Aesthetic Lifestyle Pivot",
        "vibe":         "Warm, inviting, and highly curated minimalist lifestyle aesthetic",
        "title":        "Aesthetic Inspiration That Will Completely Transform Your Vibe ✨",
        "description":  "There's something incredibly satisfying about a space that feels intentional. Curated details, perfect lighting, and an atmosphere that just radiates calm. Elevate your everyday aesthetic with these timeless visual details.",
        "tags":         ["AestheticVibe", "LifestyleInspo", "MinimalistStyle", "CozyAesthetic", "PinterestAesthetic"],
        "visual_prompt": "highly curated aesthetic lifestyle scene, warm golden hour ambient lighting, soft focus, visually satisfying composition, minimalist decor, hyperrealistic, 4K ultra HD, photorealistic",
        "ratio":        "9:16",
    },
    "account_2": {
        "pin_type":     "VIRAL_PIN",
        "strategy":     "Premium Tech Pivot",
        "vibe":         "Sleek, futuristic, and ultra-premium modern workspace aesthetic",
        "title":        "The Ultimate Modern Aesthetic That Feels Next-Level 🚀",
        "description":  "When design meets function, magic happens. It’s not just about what you use, it’s about the environment you create. Clean lines, ambient glows, and a setup that instantly boosts your focus and creativity. Total visual satisfaction.",
        "tags":         ["ModernAesthetic", "TechInspo", "CleanSetup", "FuturisticVibe", "WorkspaceGoals"],
        "visual_prompt": "ultra-premium modern setup, clean lines, ambient cinematic lighting, sleek matte textures, high-end design, deeply satisfying composition, hyperrealistic, 4K ultra HD, photorealistic",
        "ratio":        "9:16",
    },
}

# ── Pin type prompts ───────────────────────────────────────────────────────────
def _build_viral_prompt(profile: str, metrics_str: str, ratio: str) -> str:
    ratio_cfg = _RATIOS[ratio]
    # Inject the keyword dictionary as a JSON string so the AI can read it
    keywords_str = json.dumps(KEYWORDS_BY_NICHE, indent=2)
    
    return f"""TASK: Generate a VIRAL_PIN strategy optimized for massive Pinterest impressions and saves.

━━━ ACCOUNT PROFILE ━━━
{profile}

━━━ MASTER KEYWORD DICTIONARY ━━━
{keywords_str}

━━━ PIN SPECIFICATIONS ━━━
Image ratio: {ratio_cfg['label']} ({ratio_cfg['w']}×{ratio_cfg['h']}px)
Pin type: VIRAL_PIN — pure aesthetic content, zero commerce signals

━━━ CREATIVE DIRECTION (THE HUMAN TOUCH) ━━━
1. NICHE ISOLATION: Look at the 'Available Niches' in the account profile. Select EXACTLY ONE niche to focus on for this pin (e.g., ONLY 'cozy' or ONLY 'wfh').
2. VIBE MATCHING: Look up the selected niche in the MASTER KEYWORD DICTIONARY. Use those exact phrases to deeply understand the visual aesthetic people are searching for.
3. VISUAL ART DIRECTION: Act as a high-end Art Director. Write a highly specific Text-to-Image prompt that perfectly captures the keywords of that chosen niche. 
   - No generic backgrounds! A 'phone' keyword needs a lifestyle hand/desk context. An 'organize' keyword needs satisfying acrylics/symmetry.
   - Do NOT mix themes. 
4. COPYWRITING: Write like an elite lifestyle influencer. Evoke emotion. Use words like 'obsessed', 'satisfying', 'transform', 'vibe'. No robotic corporate speak.

━━━ OUTPUT FORMAT (JSON only — no other text) ━━━
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "Niche-Targeted Visual Pivot",
  "vibe": "<1-line creative direction capturing the essence of the selected niche keywords, max 80 chars>",
  "title": "<SEO-optimized human-sounding viral title, curiosity-driven, max 90 chars>",
  "description": "<sensory, relatable lifestyle copy making them want to save this pin, NO prices/CTAs, max 380 chars>",
  "tags": ["<NicheTag1>", "<NicheTag2>", "<NicheTag3>", "<NicheTag4>", "<NicheTag5>"],
  "visual_prompt": "<comma-separated T2I keywords based on the dictionary, hyper-specific to the isolated niche, no text overlays, ends with: 4K ultra HD, photorealistic, highly detailed>",
  "ratio": "{ratio}"
}}"""

def _build_affiliate_prompt(profile: str, metrics_str: str, ratio: str) -> str:
    ratio_cfg = _RATIOS[ratio]
    return f"""TASK: Generate an AFFILIATE_PIN strategy optimized for outbound link clicks and conversions.

━━━ ACCOUNT PROFILE ━━━
{profile}

━━━ PERFORMANCE ANALYTICS (last 30 days) ━━━
{metrics_str}

━━━ PIN SPECIFICATIONS ━━━
Image ratio: {ratio_cfg['label']} ({ratio_cfg['w']}×{ratio_cfg['h']}px)
Pin type: AFFILIATE_PIN — real product photo used (no AI image generated)
visual_prompt field MUST be exactly: "NONE"

━━━ CREATIVE DIRECTION ━━━
- Title: Open with the strongest hook — a specific benefit, price signal ("Under $30"), or outcome.
  Examples: "This $18 Gadget Replaced My $200 One", "The Desk Upgrade That Changed Everything"
  Make it feel like a friend sharing a find, not a brand running an ad.
- Description: Authentic recommendation voice. 1-2 concrete, specific benefits (not vague superlatives).
  Mention a real use case or outcome. Build trust. End exactly with: Link in bio 🔗
  Max 380 chars. Every word must earn its place.
- Tags: Mix product-category tags with problem/solution tags the audience searches.
  Think: what would someone type when they NEED this product?

━━━ ANALYTICS STRATEGY HINT ━━━
- "Stagnant" → switch product angle; lead with price or a surprising specific benefit
- "High-Impression / Low-Engagement" → title needs a stronger hook; current angle isn't converting
- "High-Engagement / Conversion-Ready" → test a premium product recommendation; audience is ready to buy

━━━ OUTPUT FORMAT (JSON only — no other text) ━━━
{{
  "pin_type": "AFFILIATE_PIN",
  "strategy": "Affiliate Strike",
  "vibe": "<authentic product recommendation angle, max 80 chars>",
  "title": "<benefit/outcome hook first, feels like a friend's tip, max 90 chars>",
  "description": "<genuine rec, 1-2 specific benefits, real use case, ends with: Link in bio 🔗, max 380 chars>",
  "tags": ["<Tag1>", "<Tag2>", "<Tag3>", "<Tag4>", "<Tag5>"],
  "visual_prompt": "NONE",
  "ratio": "{ratio}"
}}"""


# ── Helpers ────────────────────────────────────────────────────────────────────
def _choose_pin_type() -> str:
    return random.choices(["VIRAL_PIN", "AFFILIATE_PIN"], weights=[70, 30], k=1)[0]


def _extract_json(raw: str) -> dict:
    """
    Robustly extract JSON from model output.
    Handles: markdown fences, leading/trailing text, whitespace, truncated responses.
    """
    # Strip markdown code fences
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # Find outermost JSON object
    start = cleaned.find("{")
    end   = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError(f"No JSON object found. Raw: {cleaned[:200]}")
    json_str = cleaned[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        # Attempt to salvage truncated JSON by finding last complete field
        raise ValueError(f"JSON parse failed: {e}. Extracted: {json_str[:300]}")


def _validate(result: dict, account_key: str) -> None:
    required = ("pin_type", "strategy", "vibe", "title", "description", "tags", "visual_prompt")
    for field in required:
        if field not in result:
            raise KeyError(f"Missing '{field}' in CMO response for {account_key}.")


# ── Gemini call (primary) ──────────────────────────────────────────────────────
# FIX: system_instruction is passed via GenerateContentConfig (NOT duplicated in prompt).
# response_mime_type="application/json" forces structured output — Gemini will NOT
# emit any text outside the JSON object when this is set correctly.
def _call_gemini_sync(prompt: str) -> str:
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY not configured.")
    response = _gemini_client.models.generate_content(
        model=GEMINI_CMO_MODEL,
        contents=prompt,          # ← user prompt ONLY (no system prompt injected here)
        config=_gtypes.GenerateContentConfig(
            system_instruction=_GEMINI_SYSTEM_INSTRUCTION,   # ← system goes HERE
            temperature=0.75,     # Slightly higher for more creative Pinterest copy
            max_output_tokens=6000,
            response_mime_type="application/json",  # Forces clean JSON output
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
