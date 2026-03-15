import csv
import logging
from tools.groq_ai import filter_product
from tools.google_drive import save_products
from config import SEED_CSV_PATH

logger = logging.getLogger(__name__)


async def run_filter_bot(csv_path: str = SEED_CSV_PATH):
    """Phase 1: Load CSV → AI filter → Save to Google Sheets"""
    logger.info("🔍 Phase 1: Filter Bot started")

    # Load products from CSV
    products = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            products.append(dict(row))

    logger.info(f"📦 Loaded {len(products)} raw products")

    # AI filter each product
    approved = []
    for product in products:
        if filter_product(product):
            approved.append(product)

    logger.info(f"✅ Approved: {len(approved)}/{len(products)}")

    # Save approved to Google Sheets
    if approved:
        save_products(approved)

    return approved

# ─────────────────────────────────────────
# FUTURE: swap load_csv_from_file() with
# load_from_clickbank_api() when API approved
# ─────────────────────────────────────────
