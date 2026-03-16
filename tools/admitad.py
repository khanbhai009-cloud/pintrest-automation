import logging
from urllib.parse import quote
from config import ADMITAD_CAMPAIGN_CODE

logger = logging.getLogger(__name__)
DEEPLINK_BASE = "https://rzekl.com/g/{code}/?i=5&ulp={encoded_url}"

def make_affiliate_link(product_url: str) -> str:
    if not ADMITAD_CAMPAIGN_CODE:
        logger.warning("⚠️ ADMITAD_CAMPAIGN_CODE not set — using raw URL")
        return product_url
    encoded = quote(product_url, safe="")
    return DEEPLINK_BASE.format(code=ADMITAD_CAMPAIGN_CODE, encoded_url=encoded)

def enrich_with_affiliate_link(product: dict) -> dict:
    product["affiliate_link"] = make_affiliate_link(product.get("product_url", ""))
    return product
