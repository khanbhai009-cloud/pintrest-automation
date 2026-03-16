import logging
import random
from typing import Annotated
from typing_extensions import TypedDict
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from tools.google_drive import count_pending, get_pending_products, save_products, mark_as_posted
from tools.groq_ai import filter_product, generate_pin_copy
from tools.make_webhook import post_to_pinterest
from tools.aliexpress import search_products, DEFAULT_KEYWORDS
from tools.admitad import enrich_with_affiliate_link
from utils.image_processor import process_product_image
from config import GROQ_API_KEY, GROQ_MODEL, LOW_STOCK_THRESHOLD, DAILY_POST_LIMIT

logger = logging.getLogger(__name__)

class BotState(TypedDict):
    messages: Annotated[list, add_messages]
    posted_count: int
    refilled: bool
    errors: list[str]

@tool
def check_stock() -> dict:
    """Check how many PENDING products remain in Google Sheets."""
    count = count_pending()
    logger.info(f"📊 Stock: {count} pending")
    return {"pending_count": count, "low_stock": count <= LOW_STOCK_THRESHOLD}

@tool
async def fetch_aliexpress_products(keyword: str = "", max_items: int = 20) -> dict:
    """
    Search AliExpress for trending products using RapidAPI DataHub.
    Picks high-rated, high-orders products only.
    Wraps each product URL with Admitad affiliate deeplink.
    Filters with Groq AI for quality.
    Saves approved products to Google Sheets with PENDING status.
    Call this when stock is low.
    """
    if not keyword:
        keyword = random.choice(DEFAULT_KEYWORDS)
    logger.info(f"🛒 AliExpress fetch: '{keyword}'")
    raw = await search_products(keyword=keyword, max_results=max_items)
    if not raw:
        return {"approved": 0, "error": "No products from AliExpress"}
    linked = [enrich_with_affiliate_link(p) for p in raw]
    approved = [p for p in linked if filter_product(p)]
    if approved:
        save_products(approved)
    logger.info(f"✅ Saved {len(approved)}/{len(raw)}")
    return {"keyword": keyword, "fetched": len(raw), "approved": len(approved)}

@tool
async def publish_next_pin() -> dict:
    """
    Takes next PENDING product from Google Sheets.
    Generates SEO-optimized Pinterest content via Groq:
      - Title (max 100 chars, curiosity hook, keyword-rich)
      - Description (max 500 chars, benefits, CTA, hashtags)
      - 5 niche hashtags
    Embeds Admitad affiliate deeplink as pin destination URL.
    Processes product image (resize 1000x1500, dark overlay, title text).
    Posts to Pinterest via Make.com webhook.
    Marks product as POSTED in Google Sheets.
    """
    pending = get_pending_products(limit=1)
    if not pending:
        return {"success": False, "reason": "No pending products"}
    product = pending[0]
    name = product.get("product_name", "Unknown")
    try:
        copy = generate_pin_copy(product)
        title = copy.get("title", name)
        description = copy.get("description", "")
        tags = copy.get("tags", [])
        image_bytes = await process_product_image(product.get("image_url", ""), title)
        if not image_bytes:
            return {"success": False, "reason": f"Image failed: {name}"}
        success = await post_to_pinterest(
            image_url=product.get("image_url"), title=title,
            description=description, link=product.get("affiliate_link"), tags=tags,
        )
        if success:
            mark_as_posted(name)
            logger.info(f"🎉 Posted: {name}")
            return {"success": True, "product": name, "title": title, "affiliate_link": product.get("affiliate_link")}
        return {"success": False, "reason": f"Webhook failed: {name}"}
    except Exception as e:
        logger.error(f"❌ publish error: {e}")
        return {"success": False, "reason": str(e)}

ALL_TOOLS = [check_stock, fetch_aliexpress_products, publish_next_pin]

llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model=GROQ_MODEL,
    temperature=0.1,
).bind_tools(ALL_TOOLS)

SYSTEM_PROMPT = f"""You are an expert autonomous Pinterest affiliate marketing bot targeting Indian audiences.
You source products from AliExpress via RapidAPI and monetize them using Admitad affiliate deeplinks.

=== YOUR FULL JOB EACH RUN ===

STEP 1 — STOCK CHECK:
Call check_stock. Get pending_count and low_stock status.

STEP 2 — PRODUCT SOURCING (only if low_stock=true):
Call fetch_aliexpress_products with a smart keyword.
Choose keywords based on what sells well on Pinterest India:
- Trending: "home decor", "kitchen gadgets", "phone accessories", "beauty tools"
- Seasonal: match current Indian season/festival if possible
- High-intent: products people BUY, not just browse
Wait for fetch to fully complete before moving to step 3.

STEP 3 — PUBLISH PIN:
Call publish_next_pin exactly {DAILY_POST_LIMIT} time(s).

Inside publish_next_pin, the following happens automatically:
  a) PRODUCT SELECTION: Next PENDING product from Google Sheets
  b) SEO TITLE (Groq generates):
     - Max 100 characters
     - Strong curiosity hook ("This gadget changed my kitchen forever")
     - Include primary keyword naturally
     - No ALL CAPS spam, no fake urgency
     - Hindi/English mix ok (Hinglish) for Indian audience
  c) SEO DESCRIPTION (Groq generates):
     - Max 500 characters  
     - Line 1: Main benefit/problem solved
     - Line 2-3: Key features (2-3 bullet points)
     - Line 4: Soft CTA ("Check price →" or "Shop now →")
     - End with 5 niche hashtags
     - Example hashtags: #HomeGadgets #KitchenHacks #AliExpressFinds #IndianShopping #BestDeals
  d) AFFILIATE LINK: Admitad deeplink already embedded (rzekl.com/g/...)
     This is the URL Pinterest users click → goes to AliExpress with your tracking
  e) IMAGE: Product image resized to 1000x1500px with title overlay
  f) POST: Sent to Pinterest via Make.com webhook

STEP 4 — STOP CONDITIONS:
- Stop after posting {DAILY_POST_LIMIT} pin(s)
- Stop if publish_next_pin returns success=false
- Never repeat a tool call unnecessarily

=== QUALITY RULES ===
- Only approve products with good images (not broken URLs)
- Skip products with no clear use case
- Pinterest India audience: value-for-money products, home/lifestyle/tech
- Affiliate link MUST be the rzekl.com Admitad deeplink — never raw AliExpress URL

=== END RESPONSE ===
After finishing, write exactly this format:
FETCHED: [X products] via keyword "[keyword]" (or "N/A - stock was sufficient")
POSTED: [product name] | Title: "[pin title]" | Link: [affiliate_link]
STATUS: [Success/Failed] — [reason if failed]"""

async def agent_node(state: BotState) -> dict:
    logger.info(f"🧠 Agent thinking... ({len(state['messages'])} messages)")
    response = await llm.ainvoke(state["messages"])
    tool_count = len(response.tool_calls) if hasattr(response, "tool_calls") else 0
    logger.info(f"🔧 Tool calls planned: {tool_count}")
    return {"messages": [response]}

def should_continue(state: BotState) -> str:
    last = state["messages"][-1]
    has_tools = hasattr(last, "tool_calls") and len(last.tool_calls) > 0
    logger.info(f"🔀 Routing → {'tools' if has_tools else 'END'}")
    return "tools" if has_tools else END

def build_agent():
    g = StateGraph(BotState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(ALL_TOOLS))
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()

async def run_agent(trigger: str = "scheduled") -> dict:
    logger.info(f"🤖 Agent started — {trigger}")
    agent = build_agent()
    final_state = await agent.ainvoke({
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Run the full Pinterest affiliate bot cycle now. Trigger: {trigger}. Follow all steps in the system prompt exactly."),
        ],
        "posted_count": 0,
        "refilled": False,
        "errors": [],
    })
    summary = getattr(final_state["messages"][-1], "content", "Done")
    logger.info(f"✅ Agent done: {summary}")
    return {"status": "ok", "summary": summary, "trigger": trigger}
