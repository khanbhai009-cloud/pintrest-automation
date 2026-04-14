import gspread
import json
import logging
from datetime import datetime, timedelta
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDS_JSON, SPREADSHEET_ID, SHEET_NAME

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

_sheet_cache = None

def _get_sheet():
    global _sheet_cache
    if _sheet_cache is not None:
        return _sheet_cache 
    try:
        creds_dict = json.loads(GOOGLE_CREDS_JSON)
        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        _sheet_cache = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        logger.info("✅ Sheet connected")
        return _sheet_cache
    except Exception as e:
        logger.exception("❌ Sheet connection failed:")
        raise

# 🔥 FIX: Multi-Niche list filtering support
def get_pending_products(limit: int = 2, allowed_niches: list = None) -> list:
    sheet   = _get_sheet()
    records = sheet.get_all_records()
    pending = [r for r in records if r.get("Status") == "PENDING"]
    
    if allowed_niches:
        pending = [r for r in pending if r.get("niche") in allowed_niches]
        
    logger.info(f"📋 Found {len(pending)} pending products" + (f" for: {allowed_niches}" if allowed_niches else ""))
    return pending[:limit]

def mark_as_posted(product_name: str) -> bool:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    status_col = headers.index("Status") + 1
    for i, record in enumerate(records, start=2):
        if record.get("product_name") == product_name:
            sheet.update_cell(i, status_col, "POSTED")
            logger.info(f"✅ Marked POSTED: {product_name[:30]}...")
            return True
    return False

def save_products(products: list) -> None:
    if not products: return
    sheet = _get_sheet()
    rows = []
    for p in products:
        rows.append([
            p.get("product_name", ""), p.get("product_id", ""), p.get("sale_price", ""),
            p.get("rating", ""), p.get("orders", ""), p.get("affiliate_link", ""),
            p.get("image_url", ""), p.get("keyword", ""), p.get("niche", "home"), "PENDING"
        ])
    sheet.append_rows(rows, value_input_option="RAW")
    logger.info(f"💾 Saved {len(rows)} products in 1 API call ✅")

def count_pending() -> int:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    count = sum(1 for r in records if r.get("Status") == "PENDING")
    return count

def get_all_products() -> list:
    sheet = _get_sheet()
    return sheet.get_all_records()

def get_products_without_niche() -> list:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    empty = [r for r in records if not str(r.get("niche", "")).strip()]
    return empty

def update_niche(product_name: str, niche: str) -> bool:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    if "niche" not in headers: return False
    niche_col = headers.index("niche") + 1
    for i, record in enumerate(records, start=2):
        if record.get("product_name") == product_name:
            sheet.update_cell(i, niche_col, niche)
            logger.info(f"✅ Niche updated: {product_name[:30]}... → {niche}")
            return True
    return False


# ── Mastermind CEO — Analytics ────────────────────────────────────────────────

def _open_worksheet(sheet_name: str):
    """Open a named worksheet from the configured spreadsheet."""
    if not GOOGLE_CREDS_JSON:
        raise ValueError("GOOGLE_CREDS_JSON is not set.")
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(sheet_name)


def get_analytics_rows(sheet_name: str, days: int = 7) -> list:
    """
    Fetch the last `days` days of Pinterest analytics from a named sheet tab.
    Expected columns: Date, Impressions, Clicks, Outbound Clicks, Saves.

    Returns a list of dicts (one per day). Raises on connection error so the
    calling node can catch it and apply the stagnant-profile fallback.
    """
    ws = _open_worksheet(sheet_name)
    records = ws.get_all_records()

    if not records:
        logger.warning(f"⚠️  [{sheet_name}] Sheet is empty — no analytics rows.")
        return []

    # Try to filter to last `days` calendar days by Date column
    cutoff = datetime.now() - timedelta(days=days)
    filtered = []
    parse_errors = 0

    for row in records:
        raw_date = str(row.get("Date", "")).strip()
        if not raw_date:
            continue
        parsed = None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%d-%m-%Y", "%B %d, %Y"):
            try:
                parsed = datetime.strptime(raw_date, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            parse_errors += 1
            filtered.append(row)   # Keep unparseable rows rather than drop them
        elif parsed >= cutoff:
            filtered.append(row)

    if parse_errors:
        logger.warning(f"⚠️  [{sheet_name}] {parse_errors} rows had unparseable dates — included as-is.")

    # If date filtering produced nothing, fall back to last `days` rows
    if not filtered:
        filtered = records[-days:]
        logger.info(f"ℹ️  [{sheet_name}] Date filter returned 0 rows — using last {days} rows.")

    logger.info(f"✅ [{sheet_name}] {len(filtered)} analytics rows loaded.")
    return filtered
