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
    """
    Fetch AliExpress products by keyword. Wrap with Admitad affiliate link.
    Filter with Groq AI. Save approved to Google Sheets.
    Call ONCE when stock is low. If result is 0 products, STOP and report — do NOT retry.
    """
    if not keyword:
        keyword = random.choice(DEFAULT_KEYWORDS)
    logger.info(f"🛒 AliExpress fetch: '{keyword}'")
    raw = await search_products(keyword=keyword, max_results=max_items)
    if not raw:
        return {
            "approved": 0,
            "fetched": 0,
            "keyword": keyword,
            "error": "AliExpress API returned 0 products. Do NOT retry. Report this in summary."
        }
    linked   = [enrich_with_affiliate_link(p) for p in raw]
    approved = [p for p in linked if filter_product(p)]
    if approved:
        save_products(approved)
    logger.info(f"✅ Saved {len(approved)}/{len(raw)}")
    return {"keyword": keyword, "fetched": len(raw), "approved": len(approved)}

@tool
async def publish_next_pin() -> dict:
    """
    Get next PENDING product, generate Pinterest copy with Groq,
    post via Make.com to Pinterest, mark as POSTED in sheet.
    """
    pending = get_pending_products(limit=1)
    if not pending:
        return {"success": False, "reason": "No pending products in sheet"}
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

llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model=GROQ_MODEL,
    temperature=0.1,
).bind_tools(ALL_TOOLS)

SYSTEM_PROMPT = f"""You are an autonomous Pinterest affiliate marketing bot.

STRICT RULES — follow exactly:
1. Call check_stock ONCE.
2. If low_stock=true: call fetch_aliexpress_products ONCE with one keyword.
   - If it returns approved=0 or error: STOP immediately. Write summary and END.
   - Do NOT retry with another keyword. Do NOT call fetch again.
3. If stock is sufficient OR fetch succeeded: call publish_next_pin ONCE.
4. END after publish attempt.

NEVER call any tool more than once per run.
NEVER loop or retry on 0 results.

End with this exact format:
FETCHED: [X products] via "[keyword]" OR "Skipped — stock ok" OR "Failed — 0 results"
POSTED: [product name + title] OR "Skipped" OR "Failed — [reason]"
STATUS: Success / Partial / Failed"""

async def agent_node(state: BotState) -> dict:
    # Hard stop — prevent infinite loops
    if len(state["messages"]) > 12:
        logger.warning("⚠️ Max messages reached — forcing END")
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="FETCHED: Unknown\nPOSTED: Stopped — max iterations\nSTATUS: Failed — loop guard triggered")]}
    logger.info(f"🧠 Agent thinking... ({len(state['messages'])} messages)")
    response = await llm.ainvoke(state["messages"])
    logger.info(f"🔧 Tool calls: {len(response.tool_calls) if hasattr(response, 'tool_calls') else 0}")
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
            HumanMessage(content=f"Run Pinterest bot cycle. Trigger: {trigger}"),
        ],
        "posted_count": 0, "refilled": False, "errors": [],
    })
    summary = getattr(final_state["messages"][-1], "content", "Done")
    logger.info(f"✅ Agent done: {summary}")
    return {"status": "ok", "summary": summary, "trigger": trigger}
