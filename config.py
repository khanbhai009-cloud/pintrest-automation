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
RAPIDAPI_KEY          = os.getenv("RAPIDAPI_KEY")
TAVILY_API_KEY        = os.getenv("TAVILY_API_KEY")
AMAZON_STORE_ID       = "swiftmart0008-20"
MIN_GRAVITY           = 50
DAILY_POST_LIMIT      = 2   
LOW_STOCK_THRESHOLD   = 5
MAX_PRODUCTS_TO_FETCH = int(os.getenv("MAX_PRODUCTS_TO_FETCH", "20"))

PINTEREST_ACCOUNTS = [
    {
        "name":        "Account1_HomeDecor",
        "webhook_url": os.getenv("MAKE_WEBHOOK_URL"),
        "niche":       "home",
        "boards": {
            "home":     "909445787192886518",  
            "kitchen":  "909445787192891736",  
            "cozy":     "909445787192891741",  
            "gadgets":  "909445787192891742",  
            "organize": "909445787192891737",  
            "default":  "909445787192886518",
        }
    },
    {
        "name":        "Account2_Tech",
        "webhook_url": os.getenv("MAKE_WEBHOOK_URL_2"),
        "niche":       "tech",
        "boards": {
            "tech":      "1093952634426985800",  
            "budget":    "1093952634426985794",  
            "phone":     "1093952634426985799",  
            "smarthome": "1093952634426985795",  
            "wfh":       "1093952634426985796",  
            "default":   "1093952634426985800",
        }
    },
]
