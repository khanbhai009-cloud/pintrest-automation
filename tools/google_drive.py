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

def _get_sheet():
    try:
        # Pata lagate hain ki JSON sahi se load ho raha hai ya nahi
        try:
            creds_dict = json.loads(GOOGLE_CREDS_JSON)
        except Exception as json_err:
            logger.exception("❌ JSON Decode Error: Aapke GOOGLE_CREDS_JSON ka format galat hai.")
            raise json_err

        creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)
        logger.info("✅ Sheet connected")
        return sheet
        
    except Exception as e:
        # logger.exception poora traceback (error ki detail) terminal mein print karega
        logger.exception("❌ Sheet connection failed ki poori details:")
        raise

def get_pending_products(limit: int = 2) -> list:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    pending = [r for r in records if r.get("Status") == "PENDING"]
    logger.info(f"📋 Found {len(pending)} pending products")
    return pending[:limit]

def mark_as_posted(product_name: str) -> bool:
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
    sheet = _get_sheet()
    for p in products:
        sheet.append_row([
            p.get("product_name", ""),
            p.get("product_id", ""),
            p.get("sale_price", ""),
            p.get("rating", ""),
            p.get("orders", ""),
            p.get("affiliate_link", ""),
            p.get("image_url", ""),
            p.get("keyword", ""),
            "PENDING"
        ])
    logger.info(f"💾 Saved {len(products)} products to sheet")

def count_pending() -> int:
    sheet = _get_sheet()
    records = sheet.get_all_records()
    count = sum(1 for r in records if r.get("Status") == "PENDING")
    logger.info(f"📊 Pending count: {count}")
    return count

def get_all_products() -> list:
    sheet = _get_sheet()
    return sheet.get_all_records()
