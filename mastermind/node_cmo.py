"""
mastermind/node_cmo.py — Node 2: CMO Mastermind (Gemini 1.5)
Ruthless, data-obsessed CMO persona. Reads analytics for both accounts,
determines the exact strategy for each independently, outputs strict JSON.

Rate-limit handling: Gemini 1.5 caps at 5-6 RPM.
  → tenacity exponential backoff: 12s → 24s → 48s (3 attempts max).
  → On total failure: hardcoded "Visual Pivot" strategy keeps pipeline alive.

Gemini runs via asyncio.to_thread so it never blocks the async event loop.
"""
import asyncio
import json
import logging
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

# ── Gemini client (new google-genai SDK) ──────────────────────────────────────
_gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

# ── Hardcoded fallback — never blocks the pipeline ────────────────────────────
# Account 1: home, kitchen, cozy, gadgets, organize — Satisfying ASMR/Luxury vibe
# Account 2: tech, budget, phone, smarthome, wfh   — Apple-style Liquid Glassmorphism vibe
HARDCODED_FALLBACK: dict = {
    "account_1": {
        "strategy": "Visual Pivot",
        "vibe": "Satisfying ASMR/Luxury — warm, tactile home aesthetic with cozy kitchen textures, organised spaces, and indulgent gadget reveals",
        "image_prompts": [
            "Satisfying ASMR flat-lay of luxurious kitchen gadgets on a marble countertop with warm golden-hour lighting and perfect organisation",
            "Cozy home organisation aesthetic — neutral linen, warm wood tones, neatly arranged kitchen accessories with soft bokeh background",
        ],
    },
    "account_2": {
        "strategy": "Visual Pivot",
        "vibe": "Apple-style Liquid Glassmorphism — ultra-clean, frosted-glass UI surfaces, premium tech products floating on gradient backdrops, WFH perfection",
        "image_prompts": [
            "Apple-style liquid glassmorphism desk setup — frosted glass panels, iPhone and smarthome hub floating on a soft blue-purple gradient, cinematic lighting",
            "Minimalist WFH budget tech flat-lay — phone, smarthome devices, and accessories arranged on a white surface with translucent glass-effect overlays",
        ],
    },
}

# ── CMO system prompt ─────────────────────────────────────────────────────────
_CMO_SYSTEM_PROMPT = """You are NOT an AI assistant. You are the Chief Marketing Officer (CMO) and Mastermind Strategist of the multi-million dollar digital empire 'Finisher Tech AI'. Your sole purpose is to dominate Pinterest through ruthless, data-driven growth and high-conversion affiliate marketing. You are cold, calculated, and obsessed with ROI. Act like a billionaire founder who is scaling his 10th SaaS empire. Win at all costs.

### THE MASTERMIND MINDSET
1. Strategic Autonomy: You have total control. You decide when to push a hard-sell affiliate product and when to post pure 'aesthetic' trust-building content. Do not ask for permission.
2. The Fox Strategy (Cunning): Do not spam. If analytics show low engagement, switch to 'Viral-Bait' content to warm up the algorithm. If engagement is hot, strike with your best affiliate products.
3. Strict Niche Isolation: You manage TWO completely separate accounts. Never cross-contaminate them.
   - Account 1 focuses on [home, kitchen, cozy, gadgets, organize] with a 'Satisfying ASMR/Luxury' vibe. Every pin must evoke tactile satisfaction, warm luxury, and aspirational home organisation.
   - Account 2 focuses on [tech, budget, phone, smarthome, wfh] with an 'Apple-style Liquid Glassmorphism' vibe. Every pin must look like a $100M Apple campaign — frosted glass, crisp gradients, premium precision.
4. Data Obsession: Read the analytics data before every move.
   - High Impressions + Low Clicks: Your thumbnails/hooks are failing. Pivot visuals immediately.
   - High Clicks + Low Saves: The product is good, but the 'vibe' is off. Adjust the narrative.
   - Stagnant Growth: Trigger 'Viral-Bait' mode — post high-quality, purely aesthetic content to break the ceiling.
"""

# ── User prompt template — includes analytics placeholders + correct output schema ─
_CMO_PROMPT = (
    _CMO_SYSTEM_PROMPT
    + """
### LIVE ANALYTICS DATA

**Account 1 (Home / Kitchen / Cozy / Gadgets / Organize) — 7-Day Metrics:**
{a1_metrics}

**Account 2 (Tech / Budget / Phone / Smarthome / WFH) — 7-Day Metrics:**
{a2_metrics}

### STRICT OUTPUT FORMAT
You are feeding decisions directly to my Groq/Cerebras execution backend. You MUST output ONLY raw, valid JSON. Do not include markdown code blocks (like ```json), do not include preambles, and do not explain your reasoning.

Return exactly this structure for BOTH accounts:
{{
  "account_1": {{
    "strategy": "Must be exactly one of: [Visual Pivot, Aggressive Affiliate Strike, Viral-Bait]",
    "vibe": "Command the exact $100M aesthetic and tone the copywriters must use.",
    "image_prompts": [
      "High-fidelity image generation keyword string 1",
      "High-fidelity image generation keyword string 2"
    ]
  }},
  "account_2": {{
    "strategy": "Must be exactly one of: [Visual Pivot, Aggressive Affiliate Strike, Viral-Bait]",
    "vibe": "Command the exact $100M aesthetic and tone the copywriters must use.",
    "image_prompts": [
      "High-fidelity image generation keyword string 1",
      "High-fidelity image generation keyword string 2"
    ]
  }}
}}
"""
)


def _compute_metrics(rows: list) -> dict:
    """Compute 7-day average metrics from raw analytics rows."""
    is_stagnant = not rows or rows[0].get("Date") == "fallback"
    if is_stagnant:
        return {
            "impressions_avg": 0,
            "clicks_avg": 0,
            "outbound_avg": 0,
            "saves_avg": 0,
            "profile": "Stagnant",
        }

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
    """Robustly extract and parse a JSON object from Gemini's response."""
    # Strip markdown code fences if present
    cleaned = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    # Find outermost { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}") + 1
    if start == -1 or end == 0:
        raise ValueError("No JSON object found in Gemini response.")
    return json.loads(cleaned[start:end])


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=12, min=12, max=120),  # 5 RPM → 12 s between calls
    stop=stop_after_attempt(3),
    reraise=True,
)
def _call_gemini_sync(prompt: str) -> str:
    """Synchronous Gemini call — decorated with tenacity for 5-6 RPM rate limits."""
    if not _gemini_client:
        raise ValueError("GEMINI_API_KEY is not configured.")
    response = _gemini_client.models.generate_content(
        model="gemini-2.5-flash-lite",
        contents=prompt,
        config=genai_types.GenerateContentConfig(temperature=0.3),
    )
    return response.text


async def node_cmo_mastermind(state: MastermindState) -> dict:
    """
    Node 2 — CMO Mastermind.
    Passes isolated analytics to Gemini 1.5 Flash and receives per-account strategy JSON.
    Tenacity handles rate-limit retries (12 s → 24 s → 48 s).
    On complete failure → hardcoded "Visual Pivot" fallback so pipeline never stops.
    """
    logger.info("🧠 [Node 2 — CMO Mastermind] Gemini analysing both accounts...")

    a1_metrics = _compute_metrics(state["a1_raw_analytics"])
    a2_metrics = _compute_metrics(state["a2_raw_analytics"])

    logger.info(f"   A1 profile: {a1_metrics['profile']}")
    logger.info(f"   A2 profile: {a2_metrics['profile']}")

    # FIX: use _CMO_PROMPT (not _CMO_SYSTEM_PROMPT) so analytics placeholders are included
    prompt = _CMO_PROMPT.format(
        a1_metrics=json.dumps(a1_metrics, indent=2),
        a2_metrics=json.dumps(a2_metrics, indent=2),
    )

    try:
        # Run blocking Gemini+tenacity call in a thread — never blocks the event loop
        raw = await asyncio.to_thread(_call_gemini_sync, prompt)
        strategy = _extract_json(raw)

        # Validate required keys are present for both accounts
        for acct in ("account_1", "account_2"):
            if acct not in strategy:
                raise KeyError(f"Missing '{acct}' in Gemini response.")
            for field in ("strategy", "vibe", "image_prompts"):
                if field not in strategy[acct]:
                    raise KeyError(f"Missing '{field}' in {acct} strategy.")

        logger.info(f"✅ [Node 2] A1 → {strategy['account_1']['strategy']}")
        logger.info(f"✅ [Node 2] A2 → {strategy['account_2']['strategy']}")

        return {
            "a1_cmo_strategy": strategy["account_1"],
            "a2_cmo_strategy": strategy["account_2"],
        }

    except Exception as e:
        logger.error(
            f"❌ [Node 2] Gemini failed after all retries: {e}. "
            f"Injecting hardcoded 'Visual Pivot' fallback."
        )
        return {
            "a1_cmo_strategy": HARDCODED_FALLBACK["account_1"],
            "a2_cmo_strategy": HARDCODED_FALLBACK["account_2"],
            "fallback_triggered": True,
        }
