"""
mastermind/node_firebase_publisher.py — Node 7: Firebase Publisher

Merges blog_content + blog_products + image_url → calls save_blog_post().
Pinterest pin is already live — this node MUST NOT crash or raise.
All errors are caught and logged; pipeline continues regardless.

State input:  should_create_blog, blog_content, blog_products, last_posted_image_url
State output: blog_url (str), blog_published (bool)
"""

import logging

logger = logging.getLogger(__name__)


async def node_firebase_publisher(state: dict) -> dict:
    """
    Node 7 — Firebase Publisher.
    Skips gracefully if should_create_blog is False or blog_content is empty.
    """
    if not state.get("should_create_blog"):
        logger.info("🔥 [FirebasePublisher] Skipping — should_create_blog=False")
        return {**state, "blog_url": "", "blog_published": False}

    blog_content = state.get("blog_content", {})
    if not blog_content:
        logger.warning("🔥 [FirebasePublisher] Skipping — blog_content is empty")
        return {**state, "blog_url": "", "blog_published": False}

    # ── Merge blog_content + blog_products + image_url ────────────────────────
    blog_data = dict(blog_content)
    blog_data["products"]   = state.get("blog_products", [])
    blog_data["image_url"]  = state.get("last_posted_image_url", blog_data.get("image_url", ""))

    try:
        from tools.firebase_publisher import save_blog_post

        blog_url = await save_blog_post(blog_data)

        if blog_url:
            logger.info(f"🔥 Blog saved: {blog_url}")
            return {**state, "blog_url": blog_url, "blog_published": True}
        else:
            logger.warning("🔥 [FirebasePublisher] save_blog_post returned empty URL — pin still live ✅")
            return {**state, "blog_url": "", "blog_published": False}

    except Exception as e:
        logger.error(f"❌ Firebase failed: {e} — pin still live ✅")
        return {**state, "blog_url": "", "blog_published": False}
