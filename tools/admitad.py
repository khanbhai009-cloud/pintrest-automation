import logging
from config import AMAZON_STORE_ID  # config.py mein ye add zaroor karna

logger = logging.getLogger(__name__)

def make_affiliate_link(product_url: str) -> str:
    if not AMAZON_STORE_ID:
        logger.warning("⚠️ AMAZON_STORE_ID not set in config — using raw URL")
        return product_url
        
    # Agar URL mein pehle se tag nahi hai, toh append kar do
    if "tag=" not in product_url:
        connector = "&" if "?" in product_url else "?"
        return f"{product_url}{connector}tag={AMAZON_STORE_ID}"
    
    return product_url

def enrich_with_affiliate_link(product: dict) -> dict:
    # agent.py isko call karega AliExpress wale flow ke hisaab se
    product["affiliate_link"] = make_affiliate_link(product.get("product_url", ""))
    return product
