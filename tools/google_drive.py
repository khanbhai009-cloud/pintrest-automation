import gspread
import json
import logging
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDS_JSON, SPREADSHEET_ID, SHEET_NAME

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive"
]

# ─────────────────────────────────────────
# INTERNAL: Sheet connection
# ─────────────────────────────────────────
def _get_sheet():
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)


# ─────────────────────────────────────────
# PUBLIC API — use these in phases
# ─────────────────────────────────────────
def get_pending_products(limit: int = 2) -> list:
    """Fetch top N products with Status = PENDING"""
    sheet = _get_sheet()
    records = sheet.get_all_records()
    pending = [r for r in records if r.get("Status") == "PENDING"]
    logger.info(f"📋 Found {len(pending)} pending products")
    return pending[:limit]


def mark_as_posted(product_name: str) -> bool:
    """Update product Status to POSTED"""
    sheet = _get_sheet()
    records = sheet.get_all_records()
    headers = sheet.row_values(1)
    status_col = headers.index("Status") + 1

    for i, record in enumerate(records, start=2):
        if record.get("product_name") == product_name:
            sheet.update_cell(i, status_col, "POSTED")
            logger.info(f"✅ Marked POSTED: {product_name}")
            return True
    return False


def save_products(products: list) -> None:
    """Append approved products with PENDING status"""
    sheet = _get_sheet()
    for p in products:
        sheet.append_row([
            p.get("product_name"),
            p.get("gravity"),
            p.get("category"),
            p.get("affiliate_link"),
            p.get("image_url"),
            "PENDING"
        ])
    logger.info(f"💾 Saved {len(products)} products to sheet")


def count_pending() -> int:
    """Count how many PENDING products remain"""
    sheet = _get_sheet()
    records = sheet.get_all_records()
    count = sum(1 for r in records if r.get("Status") == "PENDING")
    return count
