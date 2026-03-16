"""
tools/llm.py — Dual LLM: Groq (primary) + Cerebras (fallback)
Auto-switches on 429 or any error.
"""
import logging
from groq import Groq
from cerebras.cloud.sdk import Cerebras
from config import GROQ_API_KEY, CEREBRAS_API_KEY, GROQ_MODEL, CEREBRAS_MODEL

logger = logging.getLogger(__name__)

groq_client     = Groq(api_key=GROQ_API_KEY)
cerebras_client = Cerebras(api_key=CEREBRAS_API_KEY)


def chat(prompt: str, system: str = "", temperature: float = 0.7) -> str:
    """
    Send a chat message. Tries Groq first, falls back to Cerebras.
    Returns response text.
    """
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    # ── Try Groq first ──────────────────────────────────────
    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=messages,
            temperature=temperature,
        )
        logger.info("✅ LLM: Groq responded")
        return response.choices[0].message.content

    except Exception as e:
        logger.warning(f"⚠️ Groq failed ({e}) — switching to Cerebras")

    # ── Fallback: Cerebras ──────────────────────────────────
    try:
        response = cerebras_client.chat.completions.create(
            model=CEREBRAS_MODEL,
            messages=messages,
            temperature=temperature,
        )
        logger.info("✅ LLM: Cerebras responded")
        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"❌ Both LLMs failed: {e}")
        return "Sorry, AI service temporarily unavailable. Try again in a moment."
