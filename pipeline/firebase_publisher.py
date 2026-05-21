"""
pipeline/firebase_publisher.py — Blog Data → Firebase Firestore → Slug Return

PREREQUISITES:
  1. Firebase project banana hoga: https://console.firebase.google.com
  2. Firestore database enable karo (Native mode)
  3. Service account JSON download karo → Replit secrets me dalo:
       FIREBASE_CREDS_JSON = <service account JSON string>
       FIREBASE_PROJECT_ID = your-project-id
  4. Next.js blog site ka collection name set karo (default: "blogs")

COLLECTION STRUCTURE (Firestore "blogs" collection):
  /blogs/{slug}
    title       : string
    meta_desc   : string
    content_html: string
    image_url   : string
    keyword     : string
    niche       : string
    word_count  : number
    published_at: timestamp
    products    : array of {amazon_title, affiliate_url, price, rating, thumbnail}
    slug        : string
    status      : "published"

Next.js me access: /blog/{slug} → fetch from Firestore

RATE LIMITING: No rate limit on Firestore writes (generous free tier).
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Firestore collection name ─────────────────────────────────────────────
BLOGS_COLLECTION = os.getenv("FIREBASE_BLOGS_COLLECTION", "blogs")


# ══════════════════════════════════════════════════════════════════════════════
# FIREBASE CLIENT (Lazy Init)
# ══════════════════════════════════════════════════════════════════════════════

_db = None


def _get_db():
    """Firebase Firestore client — lazy init."""
    global _db
    if _db is not None:
        return _db

    try:
        import firebase_admin
        from firebase_admin import credentials, firestore

        creds_json = os.getenv("FIREBASE_CREDS_JSON", "")
        project_id = os.getenv("FIREBASE_PROJECT_ID", "")

        if not creds_json:
            raise RuntimeError(
                "FIREBASE_CREDS_JSON secret not set. "
                "Add your Firebase service account JSON to Replit secrets."
            )

        creds_dict = json.loads(creds_json)

        # Avoid re-initializing if already done
        if not firebase_admin._apps:
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred, {"projectId": project_id or creds_dict.get("project_id")})

        _db = firestore.client()
        logger.info("✅ [FirebasePublisher] Firestore client initialized.")
        return _db

    except ImportError:
        raise RuntimeError(
            "firebase-admin not installed. Run: pip install firebase-admin\n"
            "Ya GUIDE.md dekho installation steps ke liye."
        )
    except Exception as e:
        raise RuntimeError(f"Firebase init failed: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# CLEANER — Products ko safe Firestore format me convert karo
# ══════════════════════════════════════════════════════════════════════════════

def _clean_products(products: list) -> list:
    safe = []
    for p in products[:10]:  # max 10 per blog
        safe.append({
            "amazon_title":  str(p.get("amazon_title", ""))[:150],
            "affiliate_url": str(p.get("affiliate_url", "")),
            "amazon_url":    str(p.get("amazon_url", "")),
            "price":         str(p.get("price", "N/A")),
            "rating":        float(p.get("rating", 0)),
            "thumbnail":     str(p.get("thumbnail", "")),
            "category":      str(p.get("category", "")),
        })
    return safe


# ══════════════════════════════════════════════════════════════════════════════
# PUBLIC API
# ══════════════════════════════════════════════════════════════════════════════

def publish_blog_to_firebase(blog_data: dict) -> dict:
    """
    Blog data ko Firebase Firestore me push karo.

    Args:
        blog_data: generate_blog_post() ka output
            {slug, title, meta_desc, content_html, image_url, products, keyword, niche, word_count}

    Returns:
        {
            "success"    : bool,
            "slug"       : str,
            "blog_url"   : str,   # Next.js ke liye: /blog/{slug}
            "firebase_id": str,   # Firestore document ID
            "error"      : str | None
        }
    """
    slug = blog_data.get("slug", "untitled")

    try:
        db = _get_db()
    except RuntimeError as e:
        logger.error(f"❌ [FirebasePublisher] {e}")
        return {
            "success":     False,
            "slug":        slug,
            "blog_url":    f"/blog/{slug}",
            "firebase_id": "",
            "error":       str(e),
        }

    doc_data = {
        "slug":         slug,
        "title":        blog_data.get("title", ""),
        "meta_desc":    blog_data.get("meta_desc", ""),
        "content_html": blog_data.get("content_html", ""),
        "image_url":    blog_data.get("image_url", ""),
        "keyword":      blog_data.get("keyword", ""),
        "niche":        blog_data.get("niche", ""),
        "word_count":   blog_data.get("word_count", 0),
        "products":     _clean_products(blog_data.get("products", [])),
        "published_at": datetime.now(timezone.utc),
        "status":       "published",
    }

    try:
        # Use slug as document ID so Next.js can fetch by slug directly
        doc_ref = db.collection(BLOGS_COLLECTION).document(slug)
        doc_ref.set(doc_data)

        blog_url = f"/blog/{slug}"
        logger.info(f"✅ [FirebasePublisher] Blog published → Firestore ID: '{slug}'")
        logger.info(f"   Blog URL (Next.js): {blog_url}")

        return {
            "success":     True,
            "slug":        slug,
            "blog_url":    blog_url,
            "firebase_id": slug,
            "error":       None,
        }

    except Exception as e:
        logger.error(f"❌ [FirebasePublisher] Firestore write failed: {e}")
        return {
            "success":     False,
            "slug":        slug,
            "blog_url":    f"/blog/{slug}",
            "firebase_id": "",
            "error":       str(e),
        }


def get_blog_by_slug(slug: str) -> Optional[dict]:
    """
    Firestore se slug ke basis pe blog fetch karo.
    Testing/debugging ke liye useful.
    """
    try:
        db     = _get_db()
        doc    = db.collection(BLOGS_COLLECTION).document(slug).get()
        if doc.exists:
            return doc.to_dict()
        return None
    except Exception as e:
        logger.error(f"❌ [FirebasePublisher] Get blog failed: {e}")
        return None
