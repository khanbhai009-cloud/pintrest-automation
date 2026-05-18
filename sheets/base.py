"""
sheets/base.py — Shared Google Sheets connection helpers.
Sabhi tracker/analytics/product files yahan se import karte hain.
"""
import json
import logging
import gspread
from google.oauth2.service_account import Credentials
from config import GOOGLE_CREDS_JSON, SPREADSHEET_ID

logger = logging.getLogger(__name__)

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]


def _get_client() -> gspread.Client:
    if not GOOGLE_CREDS_JSON:
        raise ValueError("GOOGLE_CREDS_JSON is not set.")
    creds_dict = json.loads(GOOGLE_CREDS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)


def _get_spreadsheet() -> gspread.Spreadsheet:
    return _get_client().open_by_key(SPREADSHEET_ID)


def _open_worksheet(sheet_name: str) -> gspread.Worksheet:
    return _get_spreadsheet().worksheet(sheet_name)
