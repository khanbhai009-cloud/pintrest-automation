"""
pipeline/orchestrator.py — Full Pipeline Orchestrator

Ye file sab steps ko ek chain me jodhti hai.
Main.py me sirf ek endpoint banana hoga jo run_full_pipeline() ya
run_pipeline_for_keyword() call kare — baaki sab automatic.

FULL PIPELINE FLOW:
  Step 1 → keyword_agent       : Aaj ke keywords fetch karo
  Step 2 → pin_content_agent   : Keyword → Title + Description + Hashtags
  Step 3 → prompt_selector     : Keyword → Best T2I prompt
  Step 4 → image_creator       : Prompt → Image generate karo → ImgBB URL
  Step 5 → product_extractor   : Image → Physical products list
  Step 6 → amazon_fetcher      : Products → Amazon search + verify + affiliate
  Step 7 → blog_agent          : Image + Products + Content → SEO Blog HTML
  Step 8 → firebase_publisher  : Blog → Firebase Firestore → Slug
  Step 9 → pinterest_publisher : Image + Content + Blog URL → Pinterest Pin

USAGE (from main.py — when you're ready):
  from pipeline import run_full_pipeline, run_pipeline_for_keyword

  # Single keyword
  result = await run_pipeline_for_keyword(
      keyword = "aesthetic bedroom wall decor ideas 2025",
      niche   = "home",
      account = "acc1",
  )

  # Full day run (all today's keywords)
  results = await run_full_pipeline(account="acc1")
"""

import asyncio
import logging
import time
from typing import List, Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
# RESULT SCHEMA
# ══════════════════════════════════════════════════════════════════════════════

def _empty_result(keyword: str, error: str) -> dict:
    return {
        "keyword":       keyword,
        "success":       False,
        "error":         error,
        "image_url":     None,
        "blog_slug":     None,
        "blog_url":      None,
        "pin_posted":    False,
        "products_found": 0,
        "steps_completed": [],
    }


# ══════════════════════════════════════════════════════════════════════════════
# SINGLE KEYWORD PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

async def run_pipeline_for_keyword(
    keyword: str,
    niche:   str = "home",
    account: str = "acc1",
) -> dict:
    """
    Ek keyword ke liye full pipeline run karo.

    Args:
        keyword : Viral Pinterest keyword
        niche   : Board niche
        account : "acc1" (HomeDecor) ya "acc2" (Tech)

    Returns:
        {
            "keyword"         : str,
            "success"         : bool,
            "error"           : str | None,
            "image_url"       : str | None,
            "blog_slug"       : str | None,
            "blog_url"        : str | None,   # /blog/{slug}
            "pin_posted"      : bool,
            "products_found"  : int,
            "steps_completed" : list[str],
            "pin_content"     : dict,
            "products"        : list,
        }
    """
    steps    = []
    start_ts = time.time()
    logger.info(f"\n{'='*60}")
    logger.info(f"🚀 [Orchestrator] START: '{keyword[:60]}'")
    logger.info(f"{'='*60}")

    # ── STEP 2: Pin Content ────────────────────────────────────────────────
    try:
        from pipeline.pin_content_agent import generate_pin_content
        logger.info("📋 [Step 2] Generating pin content...")
        pin_content = generate_pin_content(keyword, niche)
        steps.append("pin_content")
        logger.info(f"   ✅ Title: '{pin_content.get('title','')[:60]}'")
    except Exception as e:
        logger.error(f"❌ [Step 2] Pin content failed: {e}")
        return _empty_result(keyword, f"Step 2 (pin_content) failed: {e}")

    # ── STEP 3: Prompt Selection ───────────────────────────────────────────
    try:
        from pipeline.prompt_selector import select_best_prompt
        logger.info("🎨 [Step 3] Selecting T2I prompt...")
        t2i_prompt = select_best_prompt(keyword, niche)
        steps.append("prompt_selected")
        logger.info(f"   ✅ Prompt ({len(t2i_prompt)} chars): {t2i_prompt[:60]}...")
    except Exception as e:
        logger.error(f"❌ [Step 3] Prompt selection failed: {e}")
        return _empty_result(keyword, f"Step 3 (prompt_selector) failed: {e}")

    # ── STEP 4: Image Generation ───────────────────────────────────────────
    image_url = None
    try:
        from tools.image_creator import generate_pin_image
        logger.info("🖼️  [Step 4] Generating image...")
        image_url = await generate_pin_image(t2i_prompt, ratio="9:16")
        if image_url:
            steps.append("image_generated")
            logger.info(f"   ✅ Image: {image_url[:60]}")
        else:
            logger.warning("   ⚠️ Image generation returned None — continuing without image.")
    except Exception as e:
        logger.error(f"❌ [Step 4] Image generation failed: {e}")
        # Non-fatal — continue without image

    # ── STEP 5: Product Extraction ─────────────────────────────────────────
    extracted_products = []
    if image_url:
        try:
            from pipeline.product_extractor import extract_products_from_image
            logger.info("🔍 [Step 5] Extracting products from image...")
            extracted_products = extract_products_from_image(image_url)
            steps.append("products_extracted")
            logger.info(f"   ✅ {len(extracted_products)} products extracted.")
        except Exception as e:
            logger.warning(f"⚠️ [Step 5] Product extraction failed: {e} — continuing.")

    # ── STEP 6: Amazon Fetch ───────────────────────────────────────────────
    amazon_products = []
    if extracted_products:
        try:
            from pipeline.amazon_fetcher import fetch_amazon_products
            logger.info("🛒 [Step 6] Fetching Amazon products...")
            amazon_products = await fetch_amazon_products(extracted_products)
            steps.append("amazon_fetched")
            logger.info(f"   ✅ {len(amazon_products)} Amazon products linked.")
        except Exception as e:
            logger.warning(f"⚠️ [Step 6] Amazon fetch failed: {e} — continuing.")

    # ── STEP 7: Blog Generation ────────────────────────────────────────────
    blog_data = None
    try:
        from pipeline.blog_agent import generate_blog_post
        logger.info("📝 [Step 7] Generating SEO blog post...")
        blog_data = generate_blog_post(
            keyword     = keyword,
            pin_content = pin_content,
            image_url   = image_url or "",
            products    = amazon_products,
        )
        steps.append("blog_generated")
        logger.info(f"   ✅ Blog '{blog_data['slug']}' — {blog_data['word_count']} words")
    except Exception as e:
        logger.error(f"❌ [Step 7] Blog generation failed: {e}")
        return {
            **_empty_result(keyword, f"Step 7 (blog_agent) failed: {e}"),
            "image_url":     image_url,
            "steps_completed": steps,
            "pin_content":   pin_content,
            "products":      amazon_products,
        }

    # ── STEP 8: Firebase Publish ───────────────────────────────────────────
    firebase_result = {"success": False, "slug": blog_data["slug"], "blog_url": f"/blog/{blog_data['slug']}"}
    try:
        from pipeline.firebase_publisher import publish_blog_to_firebase
        logger.info("🔥 [Step 8] Publishing blog to Firebase...")
        firebase_result = publish_blog_to_firebase(blog_data)
        if firebase_result["success"]:
            steps.append("firebase_published")
            logger.info(f"   ✅ Firebase: {firebase_result['blog_url']}")
        else:
            logger.warning(f"   ⚠️ Firebase publish failed: {firebase_result.get('error')} — using fallback slug.")
    except Exception as e:
        logger.warning(f"⚠️ [Step 8] Firebase publish exception: {e} — continuing with slug.")

    blog_slug = firebase_result.get("slug", blog_data["slug"])
    blog_url  = firebase_result.get("blog_url", f"/blog/{blog_slug}")

    # ── STEP 9: Pinterest Pin ──────────────────────────────────────────────
    pin_result = {"success": False}
    if image_url:
        try:
            from pipeline.pinterest_publisher import publish_pin
            logger.info("📌 [Step 9] Posting pin to Pinterest...")
            pin_result = await publish_pin(
                image_url   = image_url,
                pin_content = pin_content,
                blog_slug   = blog_slug,
                account     = account,
            )
            if pin_result["success"]:
                steps.append("pin_posted")
                logger.info(f"   ✅ Pin posted → {pin_result.get('account')} | link={pin_result.get('pin_link','')[:50]}")
            else:
                logger.warning(f"   ⚠️ Pin post failed: {pin_result.get('error')}")
        except Exception as e:
            logger.warning(f"⚠️ [Step 9] Pinterest post failed: {e}")
    else:
        logger.warning("⚠️ [Step 9] No image — skipping Pinterest post.")

    elapsed = round(time.time() - start_ts, 1)
    logger.info(f"\n✅ [Orchestrator] DONE: '{keyword[:50]}' in {elapsed}s")
    logger.info(f"   Steps: {' → '.join(steps)}")
    logger.info(f"{'='*60}\n")

    return {
        "keyword":          keyword,
        "success":          True,
        "error":            None,
        "image_url":        image_url,
        "blog_slug":        blog_slug,
        "blog_url":         blog_url,
        "pin_posted":       pin_result.get("success", False),
        "products_found":   len(amazon_products),
        "steps_completed":  steps,
        "pin_content":      pin_content,
        "products":         amazon_products,
        "elapsed_sec":      elapsed,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FULL DAY RUN (All keywords for today)
# ══════════════════════════════════════════════════════════════════════════════

async def run_full_pipeline(
    account:       Optional[str] = None,
    max_pins:      int = 15,
    delay_between: int = 120,  # seconds between pins (2 min — respectful to APIs)
) -> List[dict]:
    """
    Aaj ke saare keywords ke liye pipeline run karo.

    Args:
        account       : "acc1", "acc2", ya None (both)
        max_pins      : Max pins to post today (default 15, hard cap 20)
        delay_between : Seconds between consecutive pins (default 120s)

    Returns:
        List of result dicts (one per keyword processed)
    """
    from pipeline.keyword_agent import get_todays_keywords

    logger.info(f"🌅 [Orchestrator] Full day run | account={account or 'both'} | max={max_pins}")

    keywords = get_todays_keywords(account=account, limit=max_pins)
    if not keywords:
        logger.info("ℹ️ [Orchestrator] No keywords for today.")
        return []

    results  = []
    success  = 0
    failed   = 0

    for i, kw_obj in enumerate(keywords, 1):
        logger.info(f"\n🔢 [{i}/{len(keywords)}] '{kw_obj.keyword}'")

        result = await run_pipeline_for_keyword(
            keyword = kw_obj.keyword,
            niche   = kw_obj.niche,
            account = kw_obj.account,
        )
        results.append(result)

        if result["success"]:
            success += 1
        else:
            failed += 1

        # Delay between pins (unless last one)
        if i < len(keywords):
            logger.info(f"⏳ Waiting {delay_between}s before next pin...")
            await asyncio.sleep(delay_between)

    logger.info(
        f"\n🏁 [Orchestrator] Day complete: "
        f"{success} success / {failed} failed / {len(results)} total"
    )
    return results


# ══════════════════════════════════════════════════════════════════════════════
# STANDALONE TEST
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    async def _test():
        result = await run_pipeline_for_keyword(
            keyword = "aesthetic bedroom wall decor ideas 2025",
            niche   = "home",
            account = "acc1",
        )
        import json
        print(json.dumps({k: v for k, v in result.items() if k != "products"}, indent=2))

    asyncio.run(_test())
