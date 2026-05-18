"""
sheets/setup.py — Auto-create all required Google Sheet tabs on app startup.

App restart hone par automatically:
  - Required tabs check karta hai
  - Jo missing ho → naya tab banata hai + headers inject karta hai
  - Jo already exist kare → touch nahi karta (idempotent)
"""
import logging
from config import GOOGLE_CREDS_JSON
from sheets.base import _get_spreadsheet

logger = logging.getLogger(__name__)

REQUIRED_SHEETS: dict[str, list] = {
    "Prompts_Master":  ["style_key", "account", "label", "description", "t2i_base", "niche_affinity", "tags"],
    "Style_Tracker":   ["account_1", "account_2"],
    "Prompt_Tracker":  ["tracker_key", "last_idx"],
    "Vision_Tracker":  ["date", "file_name", "style_key", "account", "status", "timestamp"],
    "Analytics_Log":   ["Date", "Impressions", "Clicks", "Outbound Clicks", "Saves"],
    "Analytics_logs2": ["Date", "Impressions", "Clicks", "Outbound Clicks", "Saves"],
}


def init_sheets() -> None:
    """
    App startup pe call karo — spreadsheet mein saari required tabs
    automatically bana deta hai + headers inject karta hai.
    GOOGLE_CREDS_JSON set nahi? → silently skip karta hai.
    """
    if not GOOGLE_CREDS_JSON:
        logger.warning("⚠️ [init_sheets] GOOGLE_CREDS_JSON not set — skipping auto-sheet creation.")
        return

    try:
        spreadsheet     = _get_spreadsheet()
        existing_titles = {ws.title for ws in spreadsheet.worksheets()}
        logger.info(f"📋 [init_sheets] Existing tabs: {existing_titles}")

        for sheet_name, headers in REQUIRED_SHEETS.items():
            if sheet_name not in existing_titles:
                ws = spreadsheet.add_worksheet(title=sheet_name, rows=1000, cols=len(headers))
                ws.append_row(headers)
                if sheet_name == "Style_Tracker":
                    ws.append_row([0, 0])
                logger.info(f"✅ [init_sheets] Created: '{sheet_name}' with headers {headers}")
            else:
                ws   = spreadsheet.worksheet(sheet_name)
                row1 = ws.row_values(1)
                if not row1:
                    ws.insert_row(headers, 1)
                    if sheet_name == "Style_Tracker":
                        ws.append_row([0, 0])
                    logger.info(f"✅ [init_sheets] Injected headers into empty tab: '{sheet_name}'")
                else:
                    logger.info(f"☑️  [init_sheets] Already set up: '{sheet_name}'")

        logger.info("🚀 [init_sheets] All required sheets verified/created successfully.")
    except Exception as e:
        logger.error(f"❌ [init_sheets] Failed — {type(e).__name__}: {e}")
