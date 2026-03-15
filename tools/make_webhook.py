import httpx
import logging
from config import MAKE_WEBHOOK_URL, PINTEREST_BOARD

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────
# Make.com Scenario expected input:
# {
#   "image_url": "https://...",
#   "title":     "Pin title",
#   "caption":   "Description + #tags",
#   "link":      "https://affiliate.link",
#   "board":     "Board Name"
# }
# ─────────────────────────────────────────

async def post_to_pinterest(
    image_url: str,
    title: str,
    description: str,
    link: str,
    tags: list
) -> bool:
    """Send pin to Make.com webhook → Pinterest"""
    
    hashtags = " ".join([f"#{t.strip()}" for t in tags])
    caption = f"{description}\n\n{hashtags}"

    payload = {
        "image_url": image_url,
        "title": title[:100],
        "caption": caption[:500],
        "link": link,
        "board": PINTEREST_BOARD
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(MAKE_WEBHOOK_URL, json=payload)

        if response.status_code == 200:
            logger.info(f"📌 Posted to Pinterest: {title[:50]}")
            return True
        else:
            logger.error(f"❌ Make.com error {response.status_code}: {response.text}")
            return False

    except Exception as e:
        logger.error(f"❌ Webhook failed: {e}")
        return False

# ─────────────────────────────────────────
# FUTURE: Add post_to_instagram(), post_to_telegram()
# for Level 3 multi-platform blast
# ─────────────────────────────────────────
