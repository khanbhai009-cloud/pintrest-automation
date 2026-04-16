"""
mastermind/node_cmo.py — Node 2: CMO Mastermind (Cerebras)

Text model  : Cerebras qwen-3-235b-a22b-instruct-2507 (OpenAI-compatible SDK)
Image model : Gemini gemini-2.5-flash-preview-image-generation (primary)
              OpenRouter black-forest-labs/flux-1.1-pro       (fallback 1)
              Pollinations.ai                                   (fallback 2)

Pin routing : 70% VIRAL_PIN / 30% AFFILIATE_PIN
Scheduler   : 10 pins/day — 5 per account — EST 7:30 AM → 7:30 PM
Trigger fmt : "scheduled-account1-VIRAL_PIN" or "scheduled-account2-AFFILIATE_PIN"

Rate-limit handling: tenacity exponential backoff 12s → 24s → 48s (3 attempts).
On total failure: hardcoded fallback keeps pipeline alive.
"""
import asyncio
import json
import logging
import random
import re

from cerebras.cloud.sdk import Cerebras
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import CEREBRAS_API_KEY, CEREBRAS_CMO_MODEL
from mastermind.state import MastermindState

logger = logging.getLogger(__name__)

_cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY) if CEREBRAS_API_KEY else None

# ── Hardcoded fallbacks ───────────────────────────────────────────────────────
HARDCODED_FALLBACK: dict = {
    "account_1": {
        "pin_type": "VIRAL_PIN",
        "strategy": "Visual Pivot",
        "vibe": "Satisfying ASMR/Luxury — warm, tactile home aesthetic with cozy kitchen textures",
        "title": "Cozy Home Aesthetic That Will Transform Your Space ✨",
        "description": "Create the most satisfying, organised home with these gorgeous finds. Pure aesthetic bliss for your Pinterest feed.",
        "tags": ["HomeAesthetic", "CozyHome", "HomeOrganization", "KitchenGoals", "HomeDecor"],
        "visual_prompt": "Satisfying ASMR flat-lay of luxurious kitchen gadgets on marble countertop, warm golden-hour lighting, perfect organisation, hyperrealistic, 8k",
    },
    "account_2": {
        "pin_type": "VIRAL_PIN",
        "strategy": "Visual Pivot",
        "vibe": "Apple-style Liquid Glassmorphism — ultra-clean premium tech aesthetic",
        "title": "Minimal WFH Setup That Looks Like a $10K Studio 🖥️",
        "description": "The cleanest desk setup inspiration for your home office. Frosted glass, gradient light, premium precision — pure tech aesthetic.",
        "tags": ["WFHSetup", "DeskSetup", "TechAesthetic", "HomeOffice", "MinimalDesk"],
        "visual_prompt": "Apple-style liquid glassmorphism desk setup, frosted glass panels, smarthome hub floating on soft blue-purple gradient, cinematic lighting, 8k",
    },
}

# ── System context injected into every prompt ────────────────────────────────
_SYSTEM_CONTEXT = """
SYSTEM CONTEXT (read carefully before generating):

You are the CMO AI of PINTERESTO — a fully autonomous Pinterest affiliate marketing system.

ARCHITECTURE:
  • This prompt is processed by: Cerebras qwen-3-235b-a22b-instruct-2507
  • Image generation (for VIRAL_PIN visual_prompt):
      Layer 1 → Gemini gemini-2.5-flash-preview-image-generation  (primary, 9:16 portrait)
      Layer 2 → OpenRouter black-forest-labs/flux-1.1-pro          (fallback 1)
      Layer 3 → Pollinations.ai                                     (fallback 2, free)
      Each layer: 2 attempts max, 3s delay on failure, 180s timeout
  • Execution agent: Groq llama-3.3-70b-versatile (Cerebras fallback)
  • Products database: Google Sheets "Approved Deals"
  • Post delivery: Make.com webhooks → Pinterest API
  • Image hosting: ImgBB (all images hosted here before posting)

SCHEDULER:
  • 10 pins/day total — 5 per account
  • Window: India 6 PM – 6 AM  =  USA EST 7:30 AM – 7:30 PM
  • Interleaved: Account1, Account2, Account1, Account2... (min 25-min gap between any pins)
  • Split: randomly 2 VIRAL + 3 AFFILIATE or 3 VIRAL + 2 AFFILIATE per account each day
  • Trigger format: "scheduled-account1-VIRAL_PIN" or "scheduled-account2-AFFILIATE_PIN"

PIN TYPE ROUTING (70/30):
  VIRAL_PIN    (70%) → T2I aesthetic image generated (your visual_prompt feeds Gemini/FLUX/Pollinations)
                       Affiliate link STRIPPED. Goal: impressions, saves, followers, reach.
  AFFILIATE_PIN (30%) → Raw product photo used directly (no AI image generated)
                        visual_prompt field must be "NONE"
                        Affiliate link KEPT. Goal: outbound clicks, conversions, revenue.

PINTEREST ALGORITHM KNOWLEDGE (use this to make smarter decisions):
  • Pinterest rewards: fresh content, keyword-rich titles/descriptions, tall 9:16 images
  • Saves (repins) are the #1 signal for organic reach boost
  • Outbound clicks signal conversion intent — Pinterest promotes boards with high CTR
  • Best performing content: aspirational lifestyle, "before/after", "how to", product reveals
  • Tags should be a mix of: 2 broad niche tags + 2 trending aesthetic tags + 1 brand/seasonal tag
  • Title should have primary keyword in first 20 chars for SEO
  • Description should feel human and organic, not robotic
"""

# ── Prompt templates ──────────────────────────────────────────────────────────
_VIRAL_PIN_PROMPT = """{system_context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CURRENT TASK: Generate a VIRAL_PIN strategy

ACCOUNT PROFILE:
{account_profile}

ANALYTICS DATA (last 30 days):
{metrics}

DECISION: Analytics show this account needs VIRAL reach content right now.
Your mission: Create a pin that gets MAXIMUM saves and impressions.
Pure aesthetic content — NO product promotion, NO affiliate links, NO CTA.

VISUAL PROMPT RULES (critical — this is fed directly to Gemini image AI):
  • Format: comma-separated descriptive keywords, no sentences
  • Style: ultra-realistic, cinematic, 9:16 portrait ratio
  • Include: lighting style, color palette, mood, specific objects/setting
  • Length: 100–200 characters max
  • Example: "cozy kitchen flatlay, marble countertop, golden hour lighting, warm tones, ASMR aesthetic, hyperrealistic, 8k"

OUTPUT ONLY valid raw JSON — no markdown fences, no explanation, no extra text:
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "Visual Pivot",
  "vibe": "punchy 1-line aesthetic direction under 100 chars — e.g. 'Warm luxe kitchen that makes you want to cook at midnight'",
  "title": "SEO-optimized title under 100 chars — primary keyword first, aspirational tone, curiosity hook",
  "description": "lifestyle description under 400 chars — pure inspiration, NO product names, NO CTAs, NO prices, NO links — make it feel like a human wrote it",
  "tags": ["BroadNicheTag", "TrendingAestheticTag", "AspirationalTag", "SeasonalOrMoodTag", "NicheSpecificTag"],
  "visual_prompt": "comma-separated T2I keywords under 200 chars, ultra-realistic, 9:16 Pinterest portrait"
}}"""

_AFFILIATE_PIN_PROMPT = """{system_context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
CURRENT TASK: Generate an AFFILIATE_PIN strategy

ACCOUNT PROFILE:
{account_profile}

ANALYTICS DATA (last 30 days):
{metrics}

DECISION: Analytics show this account is conversion-ready. Strike with an affiliate product pin.
Your mission: Create authentic copy that drives outbound clicks and purchases.
Raw product photo will be used directly — NO AI image generated (visual_prompt must be "NONE").

AFFILIATE COPY RULES:
  • Title: Lead with the biggest benefit or price hook — make them NEED to click
  • Description: Sound like a genuine recommendation from a friend, not an ad
  • Include 1-2 specific product benefits (not generic)
  • End description with a soft CTA: "Link in bio 🔗" or "Shop via link in bio ✨"
  • Tags: Mix product-specific + buyer-intent tags (people searching to buy, not just browse)

OUTPUT ONLY valid raw JSON — no markdown fences, no explanation, no extra text:
{{
  "pin_type": "AFFILIATE_PIN",
  "strategy": "Aggressive Affiliate Strike",
  "vibe": "authentic product recommendation tone under 100 chars — e.g. 'The gadget that actually changed my morning routine'",
  "title": "click-optimized title under 100 chars — lead with product benefit or price hook, create urgency",
  "description": "authentic product copy under 400 chars — 1-2 specific benefits, sounds human and genuine, ends with soft CTA like 'Link in bio 🔗'",
  "tags": ["ProductCategoryTag", "BuyerIntentTag", "NicheTag", "BenefitTag", "TrendingProductTag"],
  "visual_prompt": "NONE"
}}"""

_ACCOUNT_PROFILES = {
    "account_1": (
        "Account 1 — HomeDecor & Lifestyle\n"
        "  Niches  : home, kitchen, cozy, gadgets, organize\n"
        "  Boards  : Home Decor (ID: 909445787192886518), Kitchen (ID: 909445787192891736), "
        "Cozy (ID: 909445787192891741), Gadgets (ID: 909445787192891742), Organize (ID: 909445787192891737)\n"
        "  Aesthetic: Satisfying ASMR / Luxury warm — marble, gold tones, flatlay, warm lighting\n"
        "  Audience : Homemakers, interior design enthusiasts, 25-45 female-skewed USA/UK\n"
        "  Best content: ASMR organization clips, cozy kitchen setups, before/after home transforms"
    ),
    "account_2": (
        "Account 2 — Tech & WFH\n"
        "  Niches  : tech, budget, phone, smarthome, wfh\n"
        "  Boards  : Tech (ID: 1093952634426985800), Budget Finds (ID: 1093952634426985794), "
        "Phone (ID: 1093952634426985799), SmartHome (ID: 1093952634426985795), WFH (ID: 1093952634426985796)\n"
        "  Aesthetic: Apple-style Liquid Glassmorphism — frosted glass, minimal, blue-purple gradients\n"
        "  Audience : Tech enthusiasts, remote workers, gadget buyers, 20-35 male-skewed, USA/India\n"
        "  Best content: Desk setup reveals, budget tech finds under $50, smarthome automations"
    ),
}


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

    imp = _avg("Impressions")
    clicks = _avg("Clicks")
    saves = _avg("Saves")
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


def _extract_json(raw: str) -> dict:
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in Cerebras response.")
    return json.loads(cleaned[start:end])


def _choose_pin_type() -> str:
    return random.choices(["VIRAL_PIN", "AFFILIATE_PIN"], weights=[70, 30], k=1)[0]


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=12, min=12, max=120),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_cerebras_sync(prompt: str) -> str:
    """Call Cerebras qwen-3-235b-a22b-instruct-2507 synchronously (offloaded to thread)."""
    if not _cerebras_client:
        raise ValueError("CEREBRAS_API_KEY is not configured.")
    response = _cerebras_client.chat.completions.create(
        model=CEREBRAS_CMO_MODEL,
        messages=[
            {
                "role": "system",
                "content": "You are an expert Pinterest CMO. Always respond with valid raw JSON only — no markdown fences, no extra text.",
            },
            {
                "role": "user",
                "content": str(prompt),
            },
        ],
        temperature=0.4,
        max_tokens=900,
    )
    return response.choices[0].message.content


def _call_cerebras_for_account(account_key: str, metrics: dict, pin_type_override: str = None) -> dict:
    """
    Generate CMO strategy for one account using Cerebras.
    pin_type_override: if "VIRAL_PIN" or "AFFILIATE_PIN", skips the 70/30 random routing.
    """
    if pin_type_override in ("VIRAL_PIN", "AFFILIATE_PIN"):
        pin_type = pin_type_override
        logger.info(f"   [{account_key}] Scheduler override → {pin_type}")
    else:
        pin_type = _choose_pin_type()
        logger.info(f"   [{account_key}] 70/30 routing → {pin_type}")

    profile     = _ACCOUNT_PROFILES[account_key]
    metrics_str = json.dumps(metrics, indent=2)

    if pin_type == "VIRAL_PIN":
        prompt = _VIRAL_PIN_PROMPT.format(
            system_context=_SYSTEM_CONTEXT,
            account_profile=profile,
            metrics=metrics_str,
        )
    else:
        prompt = _AFFILIATE_PIN_PROMPT.format(
            system_context=_SYSTEM_CONTEXT,
            account_profile=profile,
            metrics=metrics_str,
        )

    raw    = _call_cerebras_sync(prompt)
    result = _extract_json(raw)

    required = ("pin_type", "strategy", "vibe", "title", "description", "tags", "visual_prompt")
    for field in required:
        if field not in result:
            raise KeyError(f"Missing '{field}' in Cerebras response for {account_key}.")

    return result


async def node_cmo_mastermind(state: MastermindState) -> dict:
    """
    Node 2 — CMO Mastermind (Cerebras qwen-3-235b-a22b-instruct-2507).
    Supports single-account triggers ("account1" or "account2" in cycle_trigger).
    Supports pin_type override embedded in trigger string (e.g., "scheduled-account1-VIRAL_PIN").
    On total failure → hardcoded fallback keeps pipeline alive.
    """
    trigger = state.get("cycle_trigger", "")

    # ── Determine which accounts to process ───────────────────────────────────
    only_a1 = "account1" in trigger and "account2" not in trigger
    only_a2 = "account2" in trigger and "account1" not in trigger
    run_a1  = not only_a2
    run_a2  = not only_a1

    # ── Extract optional pin_type override from trigger string ─────────────────
    a1_override = None
    a2_override = None
    if "VIRAL_PIN" in trigger:
        if only_a1:
            a1_override = "VIRAL_PIN"
        elif only_a2:
            a2_override = "VIRAL_PIN"
    elif "AFFILIATE_PIN" in trigger:
        if only_a1:
            a1_override = "AFFILIATE_PIN"
        elif only_a2:
            a2_override = "AFFILIATE_PIN"

    accounts_label = "A1 only" if only_a1 else ("A2 only" if only_a2 else "Both")
    logger.info(
        f"🧠 [Node 2 — CMO Mastermind] Cerebras ({CEREBRAS_CMO_MODEL}) "
        f"analysing {accounts_label} | trigger={trigger}"
    )

    a1_metrics = _compute_metrics(state["a1_raw_analytics"])
    a2_metrics = _compute_metrics(state["a2_raw_analytics"])

    fallback = False

    # ── Account 1 ─────────────────────────────────────────────────────────────
    if run_a1:
        logger.info(f"   A1 profile: {a1_metrics['profile']}")
        try:
            a1_strategy = await asyncio.to_thread(
                _call_cerebras_for_account, "account_1", a1_metrics, a1_override
            )
            logger.info(f"✅ [Node 2] A1 → {a1_strategy['pin_type']} / {a1_strategy['strategy']}")
        except Exception as e:
            logger.error(f"❌ [Node 2] Cerebras failed for A1: {e}. Using fallback.")
            a1_strategy = HARDCODED_FALLBACK["account_1"]
            fallback = True
    else:
        a1_strategy = {}

    # ── Account 2 ─────────────────────────────────────────────────────────────
    if run_a2:
        logger.info(f"   A2 profile: {a2_metrics['profile']}")
        try:
            a2_strategy = await asyncio.to_thread(
                _call_cerebras_for_account, "account_2", a2_metrics, a2_override
            )
            logger.info(f"✅ [Node 2] A2 → {a2_strategy['pin_type']} / {a2_strategy['strategy']}")
        except Exception as e:
            logger.error(f"❌ [Node 2] Cerebras failed for A2: {e}. Using fallback.")
            a2_strategy = HARDCODED_FALLBACK["account_2"]
            fallback = True
    else:
        a2_strategy = {}

    return {
        "a1_cmo_strategy":    a1_strategy,
        "a2_cmo_strategy":    a2_strategy,
        "fallback_triggered": fallback,
    }
