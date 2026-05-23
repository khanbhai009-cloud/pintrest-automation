"""
tools/firebase_publisher.py — Firebase Firestore Blog Backend

Collections:
  blog_posts     — Document ID = slug
  collections    — Auto-updated niche/sub-niche groupings
  daily_counter  — Document ID = YYYY-MM-DD (blog post rate limiter)

Project: earn-d6f28 (Firebase project)
Auth: FIREBASE_CREDS_JSON env var (stringified service account JSON)
"""

import json
import logging
from datetime import date
from typing import Optional

from config import BLOG_BASE_URL, FIREBASE_CREDS_JSON

logger = logging.getLogger(__name__)

_db = None


def _get_db():
    """Lazy singleton — initialise Firebase Admin + return Firestore client."""
    global _db
    if _db is not None:
        return _db

    if not FIREBASE_CREDS_JSON:
        logger.error("❌ [Firebase] FIREBASE_CREDS_JSON not set — cannot connect.")
        return None

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        if not firebase_admin._apps:
            creds_dict = json.loads(FIREBASE_CREDS_JSON)
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred)
            logger.info("✅ [Firebase] App initialised (project: earn-d6f28)")

        _db = firestore.client()
        return _db

    except Exception as e:
        logger.error(f"❌ [Firebase] Init failed: {e}")
        return None


async def save_blog_post(blog_data: dict) -> str:
    """
    Save a complete blog post document to Firestore.

    Args:
        blog_data: Full blog dict including paragraphs, products, faq, niche, etc.

    Returns:
        Published blog URL string, or "" on failure.
    """
    try:
        from firebase_admin import firestore as _fs

        db = _get_db()
        if not db:
            return ""

        slug     = blog_data.get("slug", "")
        niche    = blog_data.get("niche", "home-decor")
        sub_niche = blog_data.get("sub_niche", "general")

        if not slug:
            logger.error("❌ [Firebase] blog_data missing 'slug' field.")
            return ""

        doc_data = {
            "slug":            slug,
            "title":           blog_data.get("title", ""),
            "seo_title":       blog_data.get("seo_title", ""),
            "meta_desc":       blog_data.get("meta_description", ""),
            "excerpt":         blog_data.get("excerpt", ""),
            "niche":           niche,
            "sub_niche":       sub_niche,
            "style_name":      blog_data.get("style_name", ""),
            "collection_tag":  blog_data.get("collection_tag", f"{niche}/{sub_niche}"),
            "image_url":       blog_data.get("image_url", ""),
            "pinterest_url":   blog_data.get("pinterest_url", ""),
            "paragraphs":      blog_data.get("paragraphs", []),
            "products":        blog_data.get("products", []),
            "faq":             blog_data.get("faq", []),
            "tags":            blog_data.get("tags", []),
            "primary_keyword": blog_data.get("primary_keyword", ""),
            "status":          "published",
            "views":           0,
            "account":         blog_data.get("account", ""),
            "created_at":      _fs.SERVER_TIMESTAMP,
            "updated_at":      _fs.SERVER_TIMESTAMP,
        }

        db.collection("blog_posts").document(slug).set(doc_data)

        blog_url = f"{BLOG_BASE_URL}/{niche}/{sub_niche}/{slug}"
        logger.info(f"✅ [Firebase] Blog post saved: {blog_url}")

        await _update_collection(db, blog_data)

        return blog_url

    except Exception as e:
        logger.error(f"❌ [Firebase] save_blog_post failed: {e}")
        return ""


async def _update_collection(db, blog_data: dict) -> None:
    """
    Upsert the 'collections' document for this blog post's collection_tag.
    Creates it if it doesn't exist; appends slug and increments pin_count if it does.
    """
    try:
        from firebase_admin import firestore as _fs

        niche         = blog_data.get("niche", "home-decor")
        sub_niche     = blog_data.get("sub_niche", "general")
        slug          = blog_data.get("slug", "")
        collection_tag = blog_data.get("collection_tag", f"{niche}/{sub_niche}")
        doc_id        = collection_tag.replace("/", "-")

        col_ref = db.collection("collections").document(doc_id)
        snap    = col_ref.get()

        if snap.exists:
            col_ref.update({
                "slug_list":   _fs.ArrayUnion([slug]),
                "pin_count":   _fs.Increment(1),
                "cover_image": blog_data.get("image_url", ""),
                "last_updated": _fs.SERVER_TIMESTAMP,
            })
        else:
            col_ref.set({
                "collection_tag": collection_tag,
                "niche":          niche,
                "sub_niche":      sub_niche,
                "title":          f"Top {sub_niche.title()} Ideas",
                "description":    f"Best {sub_niche} content curated for you.",
                "cover_image":    blog_data.get("image_url", ""),
                "slug_list":      [slug] if slug else [],
                "pin_count":      1,
                "last_updated":   _fs.SERVER_TIMESTAMP,
            })

        logger.info(f"✅ [Firebase] Collection updated: {doc_id}")

    except Exception as e:
        logger.error(f"❌ [Firebase] _update_collection failed: {e}")


async def check_and_increment_daily_counter(account: str = "account1") -> bool:
    """
    Check and increment today's blog post counter (per account).

    Limit: 5 blogs per account per day (10 total across both accounts).

    Args:
        account: "account1" or "account2"

    Returns:
        True  — proceed (limit not reached, counter incremented)
        False — skip (5 posts already published today for this account)
    """
    try:
        from firebase_admin import firestore as _fs

        db = _get_db()
        if not db:
            return False

        today   = str(date.today())
        doc_id  = f"{today}-{account}"
        doc_ref = db.collection("daily_counter").document(doc_id)
        snap    = doc_ref.get()
        limit   = 5

        if snap.exists:
            count = snap.to_dict().get("blog_count", 0)
            if count >= limit:
                logger.info(f"📊 [Firebase] Daily limit reached ({count}/{limit}) for {account} on {today}")
                return False
            doc_ref.update({"blog_count": _fs.Increment(1)})
            logger.info(f"📊 [Firebase] Daily counter [{account}]: {count + 1}/{limit}")
            return True
        else:
            doc_ref.set({"blog_count": 1, "date": today, "account": account})
            logger.info(f"📊 [Firebase] Daily counter [{account}] started: 1/{limit}")
            return True

    except Exception as e:
        logger.error(f"❌ [Firebase] check_and_increment_daily_counter failed: {e}")
        return False


async def get_daily_blog_counts() -> dict:
    """Return today's blog post counts for both accounts."""
    try:
        db = _get_db()
        if not db:
            return {"account1": 0, "account2": 0, "limit": 5}

        today = str(date.today())
        counts = {}
        for acct in ["account1", "account2"]:
            snap = db.collection("daily_counter").document(f"{today}-{acct}").get()
            counts[acct] = snap.to_dict().get("blog_count", 0) if snap.exists else 0
        counts["limit"] = 5
        return counts

    except Exception as e:
        logger.error(f"❌ [Firebase] get_daily_blog_counts failed: {e}")
        return {"account1": 0, "account2": 0, "limit": 5}


async def get_all_posts(limit: int = 20) -> list:
    """Fetch published posts ordered by created_at DESC."""
    try:
        db = _get_db()
        if not db:
            return []

        docs = (
            db.collection("blog_posts")
            .where("status", "==", "published")
            .order_by("created_at", direction="DESCENDING")
            .limit(limit)
            .stream()
        )
        return [d.to_dict() for d in docs]

    except Exception as e:
        logger.error(f"❌ [Firebase] get_all_posts failed: {e}")
        return []


async def get_post_by_slug(slug: str) -> Optional[dict]:
    """Fetch a single post by slug and increment its view count."""
    try:
        from firebase_admin import firestore as _fs

        db = _get_db()
        if not db:
            return None

        doc_ref = db.collection("blog_posts").document(slug)
        snap    = doc_ref.get()

        if not snap.exists:
            return None

        doc_ref.update({"views": _fs.Increment(1)})
        return snap.to_dict()

    except Exception as e:
        logger.error(f"❌ [Firebase] get_post_by_slug failed: {e}")
        return None
