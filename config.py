import os
import itertools
from dotenv import load_dotenv
load_dotenv()

# ── API Keys (.env se) ──────────────────────────────────────
GROQ_API_KEY          = os.getenv("GROQ_API_KEY")
CEREBRAS_API_KEY      = os.getenv("CEREBRAS_API_KEY")
GROQ_MODEL            = "llama-3.3-70b-versatile"
CEREBRAS_MODEL        = "llama3.3-70b"
GOOGLE_CREDS_JSON     = os.getenv("GOOGLE_CREDS_JSON")
SPREADSHEET_ID        = os.getenv("SPREADSHEET_ID")
SHEET_NAME            = "Approved Deals"
RAPIDAPI_KEY          = os.getenv("RAPIDAPI_KEY")
ADMITAD_CAMPAIGN_CODE = os.getenv("ADMITAD_CAMPAIGN_CODE")

# ── Bot Settings ────────────────────────────────────────────
MIN_GRAVITY           = 50
DAILY_POST_LIMIT      = 2   # 2 accounts x 1 pin = 2 pins/day
LOW_STOCK_THRESHOLD   = 5
MAX_PRODUCTS_TO_FETCH = int(os.getenv("MAX_PRODUCTS_TO_FETCH", "20"))

# ── Pinterest Accounts ──────────────────────────────────────
# Webhook URLs .env mein | Board IDs yahan (sensitive nahi)
PINTEREST_ACCOUNTS = [
    {
        "name":        "Account1_HomeDecor",
        "webhook_url": os.getenv("MAKE_WEBHOOK_URL"),
        "niche":       "home",
        "boards": {
            "home":     "909445787192891740",  # Aesthetic Room Decor 2026
            "kitchen":  "909445787192886518",  # Home Decor Ideas
            "cozy":     "909445787192891741",  # Cozy Home Essentials
            "gadgets":  "909445787192891742",  # Home Gadgets & Smart Living
            "organize": "909445787192891737",  # Home Organization Ideas
            "default":  "909445787192886518",
        }
    },
    {
        "name":        "Account2_Tech",
        "webhook_url": os.getenv("MAKE_WEBHOOK_URL_2"),
        "niche":       "tech",
        "boards": {
            "tech":      "1093952634426985800",  # Cool Tech Gadgets
            "budget":    "1093952634426985794",  # Gadgets Under $20
            "phone":     "1093952634426985799",  # Phone Accessories
            "smarthome": "1093952634426985795",  # Smart Home Devices
            "wfh":       "1093952634426985796",  # Work From Home
            "default":   "1093952634426985800",
        }
    },
]

# ── Round Robin Rotator ─────────────────────────────────────
_account_cycle = itertools.cycle(PINTEREST_ACCOUNTS)

def get_next_account() -> dict:
    return next(_account_cycle)

# ── Backward Compatibility ──────────────────────────────────
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")
PINTEREST_BOARD  = "default"
