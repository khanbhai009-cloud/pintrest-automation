import os
from dotenv import load_dotenv

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = "llama-3.3-70b-versatile"

GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = "Sheet1"

MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")
PINTEREST_BOARD = os.getenv("PINTEREST_BOARD", "COOL OUTFITS")

DIGISTORE_API_KEY = os.getenv("DIGISTORE_API_KEY")

MAX_PRODUCTS_TO_FETCH = 50
MAX_PRODUCTS_TO_APPROVE = 20
DAILY_POST_LIMIT = 2
LOW_STOCK_THRESHOLD = 5

ALLOWED_CATEGORIES = ["health","fitness","weight loss","diet","beauty","spirituality","self help","make money","internet marketing"]
BLOCKED_CATEGORIES = ["adult","gambling","casino","dating"]
