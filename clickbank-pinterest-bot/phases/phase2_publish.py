import logging
from tools.google_drive import get_pending_products, mark_as_posted
from tools.groq_ai import generate_pin_copy
from tools.make_webhook import post_to_pinterest
from utils.image_processor import process_product_image
from config import DAILY_POST_LIMIT

logger = logging.getLogger(__name__)


async def run_publisher_bot():
    """Phase 2: Fetch pending → Generate content → Post → Mark done"""
    logger.info("📌 Phase 2: Publisher Bot started")

    pending = get_pending_products(limit=DAILY_POST_LIMIT)

    if not pending:
        logger.info("⚠️ No pending products. Skipping.")
        return 0

    posted = 0

    for product in pending:
        name = product.get("product_name", "Unknown")

        try:
            # Step 1: Generate AI copy
            copy = generate_pin_copy(product)
            title       = copy.get("title", name)
            description = copy.get("description", "")
            tags        = copy.get("tags", [])

            # Step 2: Process image (download + overlay)
            image_bytes = await process_product_image(
                product.get("image_url", ""),
                title
            )

            if not image_bytes:
                logger.warning(f"⚠️ Image failed for {name}, skipping")
                continue

            # Step 3: Post via Make.com → Pinterest
            # Note: Make.com will handle the actual image upload
            # Pass original image_url, Make.com downloads + posts it
            success = await post_to_pinterest(
                image_url=product.get("image_url"),
                title=title,
                description=description,
                link=product.get("affiliate_link"),
                tags=tags
            )

            # Step 4: Update status in sheet
            if success:
                mark_as_posted(name)
                posted += 1
                logger.info(f"🎉 Done: {name}")

        except Exception as e:
            logger.error(f"❌ Error posting {name}: {e}")
            continue

    logger.info(f"📊 Today's result: {posted}/{len(pending)} pins posted")
    return posted
