"""
pipeline/pinterest_publisher.py — Pin Upload to Pinterest via Make.com Webhook

Ye file existing tools/make_webhook.py ka thin wrapper hai.
Blog URL (Next.js slug URL) pin ke link me use hoti hai.

FLOW:
  Pin ka link = blog website base URL + slug
  e.g. https://yourblog.com/blog/aesthetic-bedroom-wall-decor-ideas-2025

SETUP:
  BLOG_BASE_URL secret set karo Replit me:
    BLOG_BASE_URL = https://yourblog.com
  (trailing slash mat lagana)
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ── Blog base URL ──────────────────────────────────────────────────────────
BLOG_BASE_URL = os.getenv("BLOG_BASE_URL", "")  # e.g. https://yourblog.com


# ══════════════════════════════════════════════════════════════════════════════
# ACCOUNT NAME MAPPER
# ══════════════════════════════════════════════════════════════════════════════

_ACCOUNT_MAP = {
    "acc1": "Account1_HomeDecor",
    "acc2": "Account2_Tech",
}


def _resolve_account_name(account: str) -> str:
    """acc1/acc2 ko Pinterest account name me convert karo."""
    return _ACCOUNT_MAP.get(account.lower(), "Account1_HomeDecor")


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

async def publish_pin(
    image_url:   str,
    pin_content: dict,
    blog_slug:   str,
    account:     str = "acc1",
) -> dict:
    """
    Pinterest pe pin post karo.

    Args:
        image_url   : ImgBB hosted image URL
        pin_content : generate_pin_content() ka output {title, description, hashtags, niche, board_suggestion}
        blog_slug   : Firebase se mila slug (e.g. "aesthetic-bedroom-wall-decor-2025")
        account     : "acc1" (HomeDecor) ya "acc2" (Tech)

    Returns:
        {
            "success"   : bool,
            "pin_link"  : str,   # Blog URL jo pin me attach hai
            "account"   : str,
            "error"     : str | None
        }
    """
    from tools.make_webhook import post_to_pinterest

    title       = pin_content.get("title", "")[:100]
    description = pin_content.get("description", "")
    hashtags    = pin_content.get("hashtags", [])
    niche       = pin_content.get("niche", "home")

    # Blog URL build karo
    if BLOG_BASE_URL:
        pin_link = f"{BLOG_BASE_URL.rstrip('/')}/blog/{blog_slug}"
    else:
        pin_link = f"/blog/{blog_slug}"
        logger.warning("⚠️ [PinterestPublisher] BLOG_BASE_URL not set — using relative URL as link.")

    account_name = _resolve_account_name(account)
    alt_text     = f"{title} — {niche} inspiration"

    logger.info(
        f"📌 [PinterestPublisher] Posting to {account_name} | "
        f"niche={niche} | link={pin_link[:60]}"
    )

    try:
        success = await post_to_pinterest(
            image_url      = image_url,
            title          = title,
            description    = description,
            link           = pin_link,
            tags           = hashtags,
            niche          = niche,
            target_account = account_name,
            alt_text       = alt_text,
        )

        if success:
            logger.info(f"✅ [PinterestPublisher] Pin posted: '{title[:50]}'")
        else:
            logger.error(f"❌ [PinterestPublisher] Webhook returned failure.")

        return {
            "success":  success,
            "pin_link": pin_link,
            "account":  account_name,
            "error":    None if success else "Webhook returned non-200 response",
        }

    except Exception as e:
        logger.error(f"❌ [PinterestPublisher] Exception: {e}")
        return {
            "success":  False,
            "pin_link": pin_link,
            "account":  account_name,
            "error":    str(e),
        }
