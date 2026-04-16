"""
mastermind/node_cmo.py — Node 2: CMO Mastermind (Gemini)
Determines pin type (70% VIRAL_PIN / 30% AFFILIATE_PIN) per account, then
calls Gemini with the appropriate prompt to generate pin-ready content JSON.

Rate-limit handling: tenacity exponential backoff 12s → 24s → 48s (3 attempts).
On total failure: hardcoded fallback keeps pipeline alive.
"""
import asyncio
import json
import logging
import random
import re

from google import genai
from google.genai import types as genai_types
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import GEMINI_API_KEY
from mastermind.state import MastermindState

logger = logging.getLogger(__name__)

_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

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

# ── Prompt templates ──────────────────────────────────────────────────────────
_VIRAL_PIN_PROMPT = """You are the CMO of a Pinterest empire. A data analysis shows this account needs VIRAL aesthetic content to grow reach.

ACCOUNT PROFILE:
{account_profile}

ANALYTICS DATA:
{metrics}

Your task: Generate a VIRAL_PIN — pure aesthetic, no sales pitch, no affiliate links. Goal is reach and saves.

OUTPUT ONLY raw JSON (no markdown, no explanation):
{{
  "pin_type": "VIRAL_PIN",
  "strategy": "Visual Pivot",
  "vibe": "short punchy aesthetic command under 120 chars",
  "title": "trendy SEO title under 100 chars, evoke aspiration and curiosity",
  "description": "engaging aesthetic description under 400 chars, NO sales pitch, NO CTA, NO product mention — pure lifestyle/inspiration",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "visual_prompt": "highly detailed T2I prompt under 200 chars, comma-separated keywords, ultra-realistic Pinterest portrait style"
}}"""

_AFFILIATE_PIN_PROMPT = """You are the CMO of a Pinterest empire. Analytics show this account is ready to convert — strike with an affiliate product pin.

ACCOUNT PROFILE:
{account_profile}

ANALYTICS DATA:
{metrics}

Your task: Generate an AFFILIATE_PIN — authentic product-focused copy with a strong CTA. No AI image will be generated (raw product photo used instead).

OUTPUT ONLY raw JSON (no markdown, no explanation):
{{
  "pin_type": "AFFILIATE_PIN",
  "strategy": "Aggressive Affiliate Strike",
  "vibe": "product-focused authentic tone under 120 chars",
  "title": "click-optimized title under 100 chars, lead with the product benefit or price hook",
  "description": "authentic product description under 400 chars, include 1-2 benefits, end with strong CTA like 'Link in bio' or 'Shop via link in bio'",
  "tags": ["tag1", "tag2", "tag3", "tag4", "tag5"],
  "visual_prompt": "NONE"
}}"""

_ACCOUNT_PROFILES = {
    "account_1": "Account 1 — niches: home, kitchen, cozy, gadgets, organize. Vibe: Satisfying ASMR / Luxury warm aesthetic.",
    "account_2": "Account 2 — niches: tech, budget, phone, smarthome, wfh. Vibe: Apple-style Liquid Glassmorphism, premium precision.",
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
        raise ValueError("No JSON object found in Gemini response.")
    return json.loads(cleaned[start:end])


def _choose_pin_type() -> str:
    return random.choices(["VIRAL_PIN", "AFFILIATE_PIN"], weights=[70, 30], k=1)[0]


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=12, min=12, max=120),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_gemini_sync(prompt: str) -> str:
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY is not configured.")
    response = _gemini_client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=str(prompt),
        config=genai_types.GenerateContentConfig(temperature=0.3),
    )
    return response.text


def _call_gemini_for_account(account_key: str, metrics: dict, pin_type_override: str = None) -> dict:
    """
    Generate CMO strategy for one account.
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
        prompt = _VIRAL_PIN_PROMPT.format(account_profile=profile, metrics=metrics_str)
    else:
        prompt = _AFFILIATE_PIN_PROMPT.format(account_profile=profile, metrics=metrics_str)

    raw    = _call_gemini_sync(prompt)
    result = _extract_json(raw)

    required = ("pin_type", "strategy", "vibe", "title", "description", "tags", "visual_prompt")
    for field in required:
        if field not in result:
            raise KeyError(f"Missing '{field}' in Gemini response for {account_key}.")

    return result


async def node_cmo_mastermind(state: MastermindState) -> dict:
    """
    Node 2 — CMO Mastermind.
    Supports single-account triggers ("account1" or "account2" in cycle_trigger).
    Supports pin_type override embedded in trigger string (e.g., "scheduled-account1-VIRAL_PIN").
    On complete failure → hardcoded fallback keeps pipeline alive.
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
    logger.info(f"🧠 [Node 2 — CMO Mastermind] Gemini analysing {accounts_label} | trigger={trigger}")

    a1_metrics = _compute_metrics(state["a1_raw_analytics"])
    a2_metrics = _compute_metrics(state["a2_raw_analytics"])

    fallback = False

    # ── Account 1 ─────────────────────────────────────────────────────────────
    if run_a1:
        logger.info(f"   A1 profile: {a1_metrics['profile']}")
        try:
            a1_strategy = await asyncio.to_thread(
                _call_gemini_for_account, "account_1", a1_metrics, a1_override
            )
            logger.info(f"✅ [Node 2] A1 → {a1_strategy['pin_type']} / {a1_strategy['strategy']}")
        except Exception as e:
            logger.error(f"❌ [Node 2] Gemini failed for A1: {e}. Using fallback.")
            a1_strategy = HARDCODED_FALLBACK["account_1"]
            fallback = True
    else:
        a1_strategy = {}

    # ── Account 2 ─────────────────────────────────────────────────────────────
    if run_a2:
        logger.info(f"   A2 profile: {a2_metrics['profile']}")
        try:
            a2_strategy = await asyncio.to_thread(
                _call_gemini_for_account, "account_2", a2_metrics, a2_override
            )
            logger.info(f"✅ [Node 2] A2 → {a2_strategy['pin_type']} / {a2_strategy['strategy']}")
        except Exception as e:
            logger.error(f"❌ [Node 2] Gemini failed for A2: {e}. Using fallback.")
            a2_strategy = HARDCODED_FALLBACK["account_2"]
            fallback = True
    else:
        a2_strategy = {}

    return {
        "a1_cmo_strategy":   a1_strategy,
        "a2_cmo_strategy":   a2_strategy,
        "fallback_triggered": fallback,
    }
