"""
sheets/base.py — Shared Google Sheets connection helpers.
Sabhi tracker/analytics/product files yahan se import karte hain.

Singleton gspread client — ek baar authenticate, baar baar reuse.
"""
import json
import logging
import time
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDS_JSON, SPREADSHEET_ID

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]

# ── Singleton client cache ─────────────────────────────────────────────────
_client: gspread.Client | None = None
_spreadsheet: gspread.Spreadsheet | None = None

# Minimum seconds between consecutive Sheets API write calls (rate-limit guard)
_WRITE_MIN_GAP = 1.2
_last_write_ts: float = 0.0


def _get_client() -> gspread.Client:
    global _client
    if _client is not None:
        return _client
    if not GOOGLE_CREDS_JSON:
        raise ValueError("GOOGLE_CREDS_JSON is not set.")
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    _client = gspread.authorize(creds)
    return _client


def _get_spreadsheet() -> gspread.Spreadsheet:
    global _spreadsheet
    if _spreadsheet is not None:
        return _spreadsheet
    _spreadsheet = _get_client().open_by_key(SPREADSHEET_ID)
    return _spreadsheet


def _open_worksheet(sheet_name: str) -> gspread.Worksheet:
    return _get_spreadsheet().worksheet(sheet_name)


def _throttled_write(fn):
    """
    Wrapper: Sheets write calls ke beech mein minimum gap enforce karta hai
    taaki per-minute quota hit na ho.
    """
    global _last_write_ts
    now = time.monotonic()
    gap = now - _last_write_ts
    if gap < _WRITE_MIN_GAP:
        time.sleep(_WRITE_MIN_GAP - gap)
    result = fn()
    _last_write_ts = time.monotonic()
    return result


def reset_client() -> None:
    """Force a fresh connection on next call (e.g. after auth expiry)."""
    global _client, _spreadsheet
    _client = None
    _spreadsheet = None
