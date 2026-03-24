import httpx
import logging
from config import PINTEREST_ACCOUNTS

logger = logging.getLogger(__name__)

async def post_to_pinterest(
    image_url: str,
    title: str,
    description: str,
    link: str,
    tags: list,
    niche: str = "default",
    target_account: str = None
) -> bool:
    
    # Strictly target account find karo
    if target_account:
        account = next((a for a in PINTEREST_ACCOUNTS if a["name"] == target_account), PINTEREST_ACCOUNTS[0])
    else:
        account = next((a for a in PINTEREST_ACCOUNTS if a["niche"] == niche), PINTEREST_ACCOUNTS[0])

    board_id = account["boards"].get(niche, account["boards"]["default"])

    hashtags = " ".join([f"#{t.strip()}" for t in tags])
    caption  = f"{description}\n\n{hashtags}"

    payload = {
        "image_url": image_url,
        "title":     title[:100],
        "caption":   caption[:500],
        "link":      link,
        "board_id":  board_id,
    }

    logger.info(f"📌 [{account['name']}] Niche: {niche} → Board ID: {board_id}")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(account["webhook_url"], json=payload)

        if r.status_code == 200:
            logger.info(f"✅ [{account['name']}] Posted: {title[:50]}")
            return True
        else:
            logger.error(f"❌ [{account['name']}] Error {r.status_code}: {r.text}")
            return False

    except Exception as e:
        logger.error(f"❌ [{account['name']}] Webhook failed: {e}")
        return False
