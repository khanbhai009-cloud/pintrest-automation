import os
from dotenv import load_dotenv
load_dotenv()

GROQ_API_KEY          = os.getenv("GROQ_API_KEY")
CEREBRAS_API_KEY      = os.getenv("CEREBRAS_API_KEY")
GROQ_MODEL            = "llama-3.3-70b-versatile"
CEREBRAS_MODEL        = "llama3.3-70b"
GOOGLE_CREDS_JSON     = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID        = os.getenv("SPREADSHEET_ID")
SHEET_NAME            = "Approved Deals"
MAKE_WEBHOOK_URL      = os.getenv("MAKE_WEBHOOK_URL")
PINTEREST_BOARD       = os.getenv("PINTEREST_BOARD", "Affiliate Deals")
RAPIDAPI_KEY          = os.getenv("RAPIDAPI_KEY")
ADMITAD_CAMPAIGN_CODE = os.getenv("ADMITAD_CAMPAIGN_CODE")
MIN_GRAVITY           = 50
DAILY_POST_LIMIT      = 1
LOW_STOCK_THRESHOLD   = 5
MAX_PRODUCTS_TO_FETCH = int(os.getenv("MAX_PRODUCTS_TO_FETCH", "20"))
