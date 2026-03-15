import os
from dotenv import load_dotenv

load_dotenv()

# ── Groq AI ─────────────────────────────
GROQ_API_KEY    = os.getenv("GROQ_API_KEY")
GROQ_MODEL      = "llama-3.3-70b-versatile"

# ── Google Sheets ────────────────────────
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON")  # full JSON as string
SPREADSHEET_ID    = os.getenv("SPREADSHEET_ID")
SHEET_NAME        = "Approved Deals"

# ── Make.com ─────────────────────────────
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")
PINTEREST_BOARD  = os.getenv("PINTEREST_BOARD", "Affiliate Deals")

# ── Bot Settings ─────────────────────────
MIN_GRAVITY         = 50     # ClickBank gravity threshold
DAILY_POST_LIMIT    = 2      # Pins per day
LOW_STOCK_THRESHOLD = 5      # Trigger refill below this
SEED_CSV_PATH       = "data/seed_products.csv"

# ─────────────────────────────────────────
# FUTURE: Add new API keys here
# e.g. STABILITY_AI_KEY = os.getenv("STABILITY_AI_KEY")
# ─────────────────────────────────────────
