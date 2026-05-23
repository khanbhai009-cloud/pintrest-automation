"""
sheets/products.py — Product CRUD operations on the main Products sheet.
Tab: configured via SHEET_NAME in config.py
"""
import logging
import gspread
from config import SHEET_NAME
from sheets.base import _get_client, SPREADSHEET_ID, _throttled_write, _throttled_read

logger = logging.getLogger(__name__)

_sheet_cache: gspread.Worksheet | None = None


def _get_sheet() -> gspread.Worksheet:
    global _sheet_cache
    if _sheet_cache is not None:
        return _sheet_cache
    client = _get_client()
    _sheet_cache = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
    logger.info("✅ Products sheet connected")
    return _sheet_cache


def get_pending_products(limit: int = 2, allowed_niches: list = None) -> list:
    def _read():
        sheet   = _get_sheet()
        records = sheet.get_all_records()
        return records

    records = _throttled_read(_read)
    pending = [r for r in records if r.get("Status") == "PENDING"]
    if allowed_niches:
        pending = [r for r in pending if r.get("niche") in allowed_niches]
    logger.info(f"📋 Found {len(pending)} pending products" + (f" for: {allowed_niches}" if allowed_niches else ""))
    return pending[:limit]


def mark_as_posted(product_name: str) -> bool:
    def _write():
        sheet      = _get_sheet()
        records    = sheet.get_all_records()
        headers    = sheet.row_values(1)
        status_col = headers.index("Status") + 1
        for i, record in enumerate(records, start=2):
            if record.get("product_name") == product_name:
                sheet.update_cell(i, status_col, "POSTED")
                logger.info(f"✅ Marked POSTED: {product_name[:30]}...")
                return True
        return False

    return _throttled_write(_write)


def save_products(products: list) -> None:
    if not products:
        return

    def _write():
        sheet = _get_sheet()
        rows  = []
        for p in products:
            rows.append([
                p.get("product_name", ""), p.get("product_id", ""), p.get("sale_price", ""),
                p.get("rating", ""), p.get("orders", ""), p.get("affiliate_link", ""),
                p.get("image_url", ""), p.get("keyword", ""), p.get("niche", "home"), "PENDING"
            ])
        sheet.append_rows(rows, value_input_option="RAW")
        logger.info(f"💾 Saved {len(rows)} products in 1 API call ✅")

    _throttled_write(_write)


def count_pending() -> int:
    def _read():
        sheet   = _get_sheet()
        return sheet.get_all_records()

    records = _throttled_read(_read)
    return sum(1 for r in records if r.get("Status") == "PENDING")


def get_all_products() -> list:
    def _read():
        return _get_sheet().get_all_records()

    return _throttled_read(_read)


def get_products_without_niche() -> list:
    def _read():
        return _get_sheet().get_all_records()

    records = _throttled_read(_read)
    return [r for r in records if not str(r.get("niche", "")).strip()]


def update_niche(product_name: str, niche: str) -> bool:
    def _write():
        sheet   = _get_sheet()
        records = sheet.get_all_records()
        headers = sheet.row_values(1)
        if "niche" not in headers:
            return False
        niche_col = headers.index("niche") + 1
        for i, record in enumerate(records, start=2):
            if record.get("product_name") == product_name:
                sheet.update_cell(i, niche_col, niche)
                logger.info(f"✅ Niche updated: {product_name[:30]}... → {niche}")
                return True
        return False

    return _throttled_write(_write)
