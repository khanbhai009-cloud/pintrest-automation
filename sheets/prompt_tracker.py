import logging
from sheets.base import _open_worksheet

logger = logging.getLogger(__name__)

def load_prompt_tracker() -> dict:
    """
    Load per-style prompt rotation indices.
    Reads ONLY from Google Sheets.
    Sheet columns: tracker_key | last_idx
    """
    try:
        sheet = _open_worksheet("Prompt_Tracker")
        records = sheet.get_all_records()
        if records:
            data = {}
            for r in records:
                key = r.get("tracker_key", "")
                val = r.get("last_idx", 0)
                # Ignore empty rows or header rows if they accidentally come up
                if key != "" and key != "tracker_key":
                    try:
                        data[str(key)] = int(val)
                    except ValueError:
                        continue # Agar value number nahi hai toh ignore karo
            
            logger.info(f"✅ Prompt_Tracker loaded from Sheets — {len(data)} keys")
            return data
    except Exception as e:
        logger.warning(f"Prompt_Tracker Sheet load failed — {type(e).__name__}: {e}")

    # Agar sheet khali hai ya error aaya toh empty dict return karo
    return {}


def save_prompt_tracker(tracker: dict) -> None:
    """
    Save per-style prompt rotation indices.
    Writes ONLY to Google Sheets.
    Sheet columns: tracker_key | last_idx
    """
    try:
        sheet = _open_worksheet("Prompt_Tracker")
        records = sheet.get_all_records()
        # Find which row each key is on (adding 2 because row 1 is header, list is 0-indexed)
        existing_keys = {r["tracker_key"]: i + 2 for i, r in enumerate(records) if r.get("tracker_key")}

        # Agar sheet puri khali hai toh pehle headers daalo
        if not records and not existing_keys:
            sheet.append_row(["tracker_key", "last_idx"])

        for key, idx in tracker.items():
            if key in existing_keys:
                # Update existing row
                sheet.update(f"B{existing_keys[key]}", [[idx]])
            else:
                # Add new row
                sheet.append_row([key, idx])

        logger.info(f"✅ Prompt_Tracker saved to Sheets — {len(tracker)} keys")
    except Exception as e:
        logger.error(f"❌ Prompt_Tracker Sheet save failed — {type(e).__name__}: {e}")

