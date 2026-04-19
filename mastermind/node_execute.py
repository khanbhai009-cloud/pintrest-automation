"""
mastermind/node_execute.py — 100% Visual Strategy

Every post is a VIRAL_PIN:
- No product sourcing, no affiliate links, no Google Sheets product dependency.
- CMO strategy provides: visual_prompt, title, description, tags, ratio, visual_style.
- generate_pin_image() creates the image (OpenRouter -> Pollinations fallback).
- Image is uploaded to ImgBB, then posted to Pinterest via Make.com webhook.
"""
import asyncio
import logging
from mastermind.state import MastermindState
from tools.image_creator import generate_pin_image
from tools.make_webhook import post_to_pinterest

logger = logging.getLogger(__name__)

# ── Per-account routing ────────────────────────────────────────────────────────
_ACCOUNT_CONFIG = {
    "account_1": {"name": "Account1_HomeDecor", "default_niche": "home"},
    "account_2": {"name": "Account2_Tech",      "default_niche": "tech"},
}

# ── Execution Pipeline ─────────────────────────────────────────────────────────

async def _execute_for_account(account_key: str, cmo_strategy: dict) -> dict:
    cfg          = _ACCOUNT_CONFIG[account_key]
    account_name = cfg["name"]
    visual_style = cmo_strategy.get("visual_style", "green_minimalist")
    ratio        = cmo_strategy.get("ratio", "9:16")

    title         = str(cmo_strategy.get("title", "Aesthetic Inspiration"))[:100]
    description   = str(cmo_strategy.get("description", ""))
    tags          = list(cmo_strategy.get("tags", []))
    visual_prompt = str(cmo_strategy.get("visual_prompt", ""))

    logger.info(
        f"[{account_name}] VIRAL_PIN | style={visual_style} | ratio={ratio} | "
        f"prompt={visual_prompt[:60]}..."
    )

    # ── Generate AI image (OpenRouter -> Pollinations fallback) ────────────────
    if not visual_prompt:
        visual_prompt = f"aesthetic {visual_style.replace('_', ' ')} photography, ultra-realistic, 4K ultra HD, photorealistic, highly detailed"

    imgbb_url = await generate_pin_image(visual_prompt=visual_prompt, ratio=ratio)

    if not imgbb_url:
        logger.error(f"[{account_name}] Image generation failed — all layers exhausted.")
        return {"success": False, "message": "Image generation failed.", "account": account_name}

    logger.info(f"[{account_name}] Image ready: {imgbb_url[:60]}...")

    # ── Post to Pinterest (no affiliate link) ──────────────────────────────────
    try:
        success = await post_to_pinterest(
            image_url=imgbb_url,
            title=title,
            description=description,
            link="",          # No affiliate links — 100% visual strategy
            tags=tags,
            niche=cfg["default_niche"],
            target_account=account_name,
        )
    except Exception as e:
        return {"success": False, "message": str(e), "account": account_name}

    if success:
        logger.info(f"[{account_name}] Posted successfully.")
        return {
            "success":       True,
            "message":       f"VIRAL_PIN posted | style={visual_style}",
            "account":       account_name,
            "visual_style":  visual_style,
            "image_url":     imgbb_url,
        }

    return {"success": False, "message": "Webhook returned failure.", "account": account_name}


# ── Entry Point ────────────────────────────────────────────────────────────────

async def node_execution_engine(state: MastermindState) -> dict:
    trigger = state.get("cycle_trigger", "scheduled")
    logger.info(f"[Node 3 - Execute] Trigger: {trigger} | 100% VIRAL_PIN mode")

    a1_status = {"success": False, "message": "Skipped", "account": "Account1_HomeDecor"}
    a2_status = {"success": False, "message": "Skipped", "account": "Account2_Tech"}

    only_a1 = trigger == "manual-account1" or (
        "account1" in trigger and "account2" not in trigger
    )
    only_a2 = trigger == "manual-account2" or (
        "account2" in trigger and "account1" not in trigger
    )

    if only_a1:
        a1_status = await _execute_for_account("account_1", state["a1_cmo_strategy"])
    elif only_a2:
        a2_status = await _execute_for_account("account_2", state["a2_cmo_strategy"])
    else:
        # Both accounts — sequential with a small gap
        a1_status = await _execute_for_account("account_1", state["a1_cmo_strategy"])
        await asyncio.sleep(5)
        a2_status = await _execute_for_account("account_2", state["a2_cmo_strategy"])

    return {"a1_publish_status": a1_status, "a2_publish_status": a2_status}
