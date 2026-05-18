"""
sheets/prompt_tracker.py — Per-style prompt rotation tracker (Prompt_Tracker sheet tab).

Tab columns: tracker_key | last_idx
tracker_key format: "account_1__boho_aesthetic_study"
Local JSON fallback: data/prompt_tracker_local.json
"""
import json
import logging
import os
from sheets.base import _open_worksheet

logger = logging.getLogger(__name__)

_LOCAL_FILE = "data/prompt_tracker_local.json"


def load_prompt_tracker() -> dict:
    """
    Load per-style prompt rotation indices.
    Priority: Prompt_Tracker sheet tab → local JSON → empty dict.
    Sheet columns: tracker_key | last_idx
    """
    # 1. Try Google Sheets
    try:
        sheet   = _open_worksheet("Prompt_Tracker")
        records = sheet.get_all_records()
        if records:
            data = {
                str(r["tracker_key"]): int(r["last_idx"])
                for r in records
                if r.get("tracker_key") != ""
            }
            logger.info(f"✅ Prompt_Tracker loaded from Sheets — {len(data)} keys")
            return data
    except Exception as e:
        logger.warning(f"Prompt_Tracker Sheet load failed — {type(e).__name__}: {e} | trying local file")

    # 2. Local JSON fallback
    try:
        if os.path.exists(_LOCAL_FILE):
            with open(_LOCAL_FILE, "r") as f:
                data = json.load(f)
                logger.info(f"Prompt_Tracker loaded from local file — {len(data)} keys")
                return data
    except Exception as e:
        logger.warning(f"Prompt_Tracker local file failed — {type(e).__name__}: {e}")

    return {}


def save_prompt_tracker(tracker: dict) -> None:
    """
    Save per-style prompt rotation indices.
    Always writes local JSON first, then updates/appends rows in Prompt_Tracker sheet.
    Sheet columns: tracker_key | last_idx
    """
    # Always save locally first
    try:
        os.makedirs(os.path.dirname(_LOCAL_FILE), exist_ok=True)
        with open(_LOCAL_FILE, "w") as f:
            json.dump(tracker, f, indent=2)
    except Exception as e:
        logger.error(f"Prompt_Tracker local save failed — {type(e).__name__}: {e}")

    # Best-effort Sheets save
    try:
        sheet         = _open_worksheet("Prompt_Tracker")
        records       = sheet.get_all_records()
        existing_keys = {r["tracker_key"]: i + 2 for i, r in enumerate(records) if r.get("tracker_key")}

        if not records:
            sheet.append_row(["tracker_key", "last_idx"])

        for key, idx in tracker.items():
            if key in existing_keys:
                sheet.update(f"B{existing_keys[key]}", [[idx]])
            else:
                sheet.append_row([key, idx])

        logger.info(f"✅ Prompt_Tracker saved to Sheets — {len(tracker)} keys")
    except Exception as e:
        logger.warning(f"Prompt_Tracker Sheet save failed (local saved) — {type(e).__name__}: {e}")
