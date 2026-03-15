import os
import logging
from tools.groq_ai import filter_product
from tools.google_drive import save_products
from tools.digistore import fetch_digistore_products
from config import MAX_PRODUCTS_TO_APPROVE

logger = logging.getLogger(__name__)

async def run_filter_bot():
    logger.info("🔍 Phase 1: Filter Bot started")
    api_key = os.getenv("DIGISTORE_API_KEY")
    if not api_key:
        logger.error("❌ DIGISTORE_API_KEY missing!")
        return []
    products = await fetch_digistore_products(api_key)
    if not products:
        logger.error("❌ No products fetched!")
        return []
    approved = []
    for product in products:
        if len(approved) >= MAX_PRODUCTS_TO_APPROVE:
            logger.info(f"✅ Max approve limit reached ({MAX_PRODUCTS_TO_APPROVE})")
            break
        if filter_product(product):
            approved.append(product)
    logger.info(f"📊 {len(approved)} approved / {len(products)} fetched")
    if approved:
        save_products(approved)
    return approved
