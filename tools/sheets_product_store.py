"""
tools/sheets_product_store.py
Saves fetched Amazon products (approved + rejected) to 'Approved Deals' Google Sheet.

Sheet columns (EXACT order — do NOT change):
  product_name | product_id | sale_price | rating | orders | affiliate_link | image_url | keyword | niche | Status

Status values:
  "primary"  — best match, used in blog
  "approved" — quality passed, saved for future use
  "rejected" — failed quality filter
"""
import logging

logger = logging.getLogger(__name__)

PRODUCT_SHEET_NAME = "Approved Deals"

SHEET_COLUMNS = [
    "product_name",   # col A
    "product_id",     # col B  (ASIN)
    "sale_price",     # col C
    "rating",         # col D
    "orders",         # col E  (reviews count)
    "affiliate_link", # col F
    "image_url",      # col G
    "keyword",        # col H
    "niche",          # col I
    "Status",         # col J
]


def _get_worksheet():
    """Open the Approved Deals worksheet using the shared sheets client."""
    from sheets.base import _open_worksheet
    return _open_worksheet(PRODUCT_SHEET_NAME)


def save_products_batch(
    keyword: str,
    niche: str,
    primary_asin: str,
    approved_products: list,
    rejected_products: list,
) -> int:
    """
    Append all products to 'Approved Deals' sheet in one batch call.

    Args:
        keyword:           The search keyword used (e.g. "purple bed sheets queen size")
        niche:             Account niche (e.g. "home", "tech")
        primary_asin:      ASIN of the product selected for blog (status="primary")
        approved_products: List of normalized product dicts (from _normalize_product)
        rejected_products: List of dicts with at least {product_id, product_name}

    Returns:
        Number of rows saved (0 on failure).
    """
    try:
        ws = _get_worksheet()
    except Exception as e:
        logger.error(f"[ProductStore] ❌ Cannot open sheet '{PRODUCT_SHEET_NAME}': {e}")
        return 0

    rows = []

    for product in approved_products:
        asin   = product.get("product_id", "")
        status = "primary" if asin == primary_asin else "approved"
        rows.append([
            product.get("product_name", "")[:100],
            asin,
            str(product.get("sale_price", "")),
            str(product.get("rating", "")),
            str(product.get("reviews", "")),
            product.get("affiliate_url", product.get("product_url", "")),
            product.get("image_url", ""),
            keyword,
            niche,
            status,
        ])

    for product in rejected_products:
        rows.append([
            product.get("product_name", "")[:100],
            product.get("product_id", product.get("asin", "")),
            str(product.get("sale_price", "")),
            str(product.get("rating", "")),
            str(product.get("reviews", "")),
            "",
            "",
            keyword,
            niche,
            "rejected",
        ])

    if not rows:
        logger.warning(f"[ProductStore] No rows to save for keyword='{keyword}'")
        return 0

    try:
        ws.append_rows(rows, value_input_option="RAW")
        logger.info(
            f"[ProductStore] ✅ Saved {len(rows)} rows for '{keyword}' | "
            f"approved={len(approved_products)} (1 primary) | rejected={len(rejected_products)}"
        )
        return len(rows)
    except Exception as e:
        logger.error(f"[ProductStore] ❌ append_rows failed for '{keyword}': {e}")
        return 0
