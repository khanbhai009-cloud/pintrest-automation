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
    messages:     Annotated[list, add_messages]
    posted_count: int
    refilled:     bool
    errors:       list[str]

@tool
def check_stock() -> dict:
    """Check how many PENDING products remain in Google Sheets."""
    count = count_pending()
    logger.info(f"📊 Stock: {count} pending")
    return {"pending_count": count, "low_stock": count <= LOW_STOCK_THRESHOLD}

@tool
async def fetch_aliexpress_products(keyword: str = "", max_items: int = 20) -> dict:
    """Fetch AliExpress products, wrap with Admitad link, Groq filter, save to sheet. Call when stock is low."""
    if not keyword:
        keyword = random.choice(DEFAULT_KEYWORDS)
    logger.info(f"🛒 AliExpress fetch: '{keyword}'")
    raw = await search_products(keyword=keyword, max_results=max_items)
    if not raw:
        return {"approved": 0, "error": "No products from AliExpress"}
    linked   = [enrich_with_affiliate_link(p) for p in raw]
    approved = [p for p in linked if filter_product(p)]
    if approved:
        save_products(approved)
    logger.info(f"✅ Saved {len(approved)}/{len(raw)} products")
    return {"keyword": keyword, "fetched": len(raw), "approved": len(approved)}

@tool
async def publish_next_pin() -> dict:
    """Get next PENDING product, generate copy with Groq, post via Make.com to Pinterest, mark POSTED."""
    pending = get_pending_products(limit=1)
    if not pending:
        return {"success": False, "reason": "No pending products"}
    product = pending[0]
    name    = product.get("product_name", "Unknown")
    try:
        copy        = generate_pin_copy(product)
        title       = copy.get("title", name)
        description = copy.get("description", "")
        tags        = copy.get("tags", [])
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
            return {"success": True, "product": name, "title": title}
        return {"success": False, "reason": f"Webhook failed: {name}"}
    except Exception as e:
        logger.error(f"❌ publish error: {e}")
        return {"success": False, "reason": str(e)}

ALL_TOOLS = [check_stock, fetch_aliexpress_products, publish_next_pin]
llm = ChatGroq(api_key=GROQ_API_KEY, model=GROQ_MODEL, temperature=0.1).bind_tools(ALL_TOOLS)

SYSTEM_PROMPT = f"""You are an autonomous Pinterest affiliate marketing bot.
Products from AliExpress. Affiliate links are Admitad deeplinks.
Each run:
1. check_stock → see pending count.
2. If low_stock=true: call fetch_aliexpress_products with a good keyword.
3. Call publish_next_pin exactly {DAILY_POST_LIMIT} time(s).
4. Stop when done or if publish returns success=false.
End with 2-line summary: fetched count + posted result."""

async def agent_node(state: BotState) -> dict:
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}

def should_continue(state: BotState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END

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
    agent       = build_agent()
    final_state = await agent.ainvoke({
        "messages": [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=f"Run the Pinterest bot cycle. Trigger: {trigger}"),
        ],
        "posted_count": 0, "refilled": False, "errors": [],
    })
    summary = getattr(final_state["messages"][-1], "content", "Done")
    logger.info(f"✅ Agent done: {summary}")
    return {"status": "ok", "summary": summary, "trigger": trigger}
