"""
mastermind/node_execute.py — Node 4: Execution Engine
Routes CMO-approved strategy + SEO copy through the existing image pipeline
and Make.com/Pinterest webhooks for each account.

Rules:
  - Wraps EVERY external call in try/except — never crashes the graph.
  - Logs all errors to terminal and updates publish_status cleanly.
  - Respects strategy: "Algorithmic Viral-Bait (No links)" → strips affiliate link.
  - Both accounts execute in parallel via asyncio.gather.
"""
import asyncio
import logging

from mastermind.state import MastermindState
from tools.google_drive import get_pending_products, mark_as_posted
from tools.make_webhook import post_to_pinterest
from utils.image_processor import process_product_image

logger = logging.getLogger(__name__)

# ── Per-account routing config — mirrors PINTEREST_ACCOUNTS in config.py ──────
_ACCOUNT_CONFIG = {
    "account_1": {
        "name":   "Account1_HomeDecor",
        "niches": ["home", "kitchen", "cozy", "gadgets", "organize"],
    },
    "account_2": {
        "name":   "Account2_Tech",
        "niches": ["tech", "budget", "phone", "smarthome", "wfh"],
    },
}


async def _execute_for_account(
    account_key: str,
    seo_copy: dict,
    cmo_strategy: dict,
) -> dict:
    """
    Full publish pipeline for one account:
      1. Fetch next PENDING product from the correct niche pool.
      2. Process product image (add overlay).
      3. Determine affiliate link based on strategy.
      4. Fire Make.com webhook → Pinterest.
      5. Mark product as POSTED in Google Sheets.

    Returns a status dict — never raises.
    """
    cfg = _ACCOUNT_CONFIG[account_key]
    account_name = cfg["name"]
    strategy_name = cmo_strategy.get("strategy", "")

    # ── Step 1: Fetch next pending product ───────────────────────────────────
    try:
        products = get_pending_products(limit=1, allowed_niches=cfg["niches"])
    except Exception as e:
        logger.error(f"❌ [{account_name}] get_pending_products failed: {e}")
        return {"success": False, "message": f"Product fetch failed: {e}", "account": account_name}

    if not products:
        logger.warning(f"⚠️  [{account_name}] No pending products in niches {cfg['niches']}. Skipping.")
        return {"success": False, "message": "No pending products available.", "account": account_name}

    product = products[0]
    niche = product.get("niche") or cfg["niches"][0]
    image_url = product.get("image_url", "")
    product_name = product.get("product_name", "Amazing Find")

    # ── Step 2: Build final title / description / tags ───────────────────────
    title = (seo_copy.get("title") or product_name)[:100]
    description = seo_copy.get("description", "")
    tags = seo_copy.get("tags") or []

    # ── Step 3: Image processing (existing pipeline — untouched) ─────────────
    try:
        await process_product_image(image_url, title)
        # process_product_image returns bytes; webhook uses the original image_url.
        # The bytes would be used if switching to direct API upload in future.
        logger.info(f"🖼️  [{account_name}] Image overlay generated for: {title[:50]}")
    except Exception as e:
        logger.warning(f"⚠️  [{account_name}] Image processing failed ({e}) — continuing with raw URL.")

    # ── Step 4: Determine affiliate link based on CMO strategy ───────────────
    affiliate_link = product.get("affiliate_link") or product.get("product_url", "")
    if "Viral-Bait" in strategy_name:
        affiliate_link = ""   # No links for pure viral content
        logger.info(f"🎯  [{account_name}] Strategy 'Viral-Bait' → affiliate link removed.")

    # ── Step 5: Fire webhook (existing post_to_pinterest — untouched) ─────────
    try:
        success = await post_to_pinterest(
            image_url=image_url,
            title=title,
            description=description,
            link=affiliate_link,
            tags=tags,
            niche=niche,
            target_account=account_name,
        )
    except Exception as e:
        logger.error(f"❌ [{account_name}] Webhook call raised exception: {e}")
        return {"success": False, "message": f"Webhook exception: {e}", "account": account_name}

    if not success:
        logger.error(f"❌ [{account_name}] Webhook returned failure status.")
        return {"success": False, "message": "Webhook returned failure.", "account": account_name}

    # ── Step 6: Mark as POSTED in Google Sheets ───────────────────────────────
    try:
        mark_as_posted(product_name)
    except Exception as e:
        logger.warning(f"⚠️  [{account_name}] mark_as_posted failed ({e}) — pin was published but Sheet not updated.")

    logger.info(f"✅ [{account_name}] Posted — '{title[:60]}' | niche={niche} | strategy={strategy_name}")
    return {
        "success": True,
        "message": f"Posted: {title[:60]}",
        "account": account_name,
        "niche": niche,
        "strategy": strategy_name,
        "product": product_name,
    }


async def node_execution_engine(state: MastermindState) -> dict:
    """
    Node 4 — Execution Engine.
    Runs both accounts in parallel (asyncio.gather).
    Any exception from either account is caught and returned as a failure status.
    The graph loop never crashes here.
    """
    logger.info("🚀 [Node 4 — Execution Engine] Publishing pins for both accounts in parallel...")

    results = await asyncio.gather(
        _execute_for_account("account_1", state["a1_final_seo_copy"], state["a1_cmo_strategy"]),
        _execute_for_account("account_2", state["a2_final_seo_copy"], state["a2_cmo_strategy"]),
        return_exceptions=True,
    )

    a1_status = results[0]
    a2_status = results[1]

    # Normalise exceptions from gather into status dicts
    if isinstance(a1_status, Exception):
        logger.error(f"❌ [Account 1] Uncaught exception in gather: {a1_status}")
        a1_status = {"success": False, "message": str(a1_status), "account": "Account1_HomeDecor"}

    if isinstance(a2_status, Exception):
        logger.error(f"❌ [Account 2] Uncaught exception in gather: {a2_status}")
        a2_status = {"success": False, "message": str(a2_status), "account": "Account2_Tech"}

    a1_icon = "✅" if a1_status["success"] else "❌"
    a2_icon = "✅" if a2_status["success"] else "❌"
    logger.info(
        f"📊 [Node 4 — Done] "
        f"A1 {a1_icon} {a1_status.get('message', '')} | "
        f"A2 {a2_icon} {a2_status.get('message', '')}"
    )

    return {
        "a1_publish_status": a1_status,
        "a2_publish_status": a2_status,
    }
