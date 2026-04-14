import logging
import random
import time
from typing import Annotated
from typing_extensions import TypedDict

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI 
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from tools.google_drive import (
    count_pending, get_pending_products, save_products,
    mark_as_posted, get_products_without_niche, update_niche
)
from tools.groq_ai import filter_product, generate_pin_copy
from tools.make_webhook import post_to_pinterest
from tools.aliexpress import search_products, KEYWORDS_BY_NICHE, DEFAULT_KEYWORDS
from tools.admitad import enrich_with_affiliate_link
from utils.image_processor import process_product_image
from tools.llm import chat
from config import GROQ_API_KEY, GROQ_MODEL, CEREBRAS_API_KEY, CEREBRAS_MODEL, PINTEREST_ACCOUNTS

logger = logging.getLogger(__name__)
CURRENT_TRIGGER = None

class BotState(TypedDict):
    messages:     Annotated[list, add_messages]
    posted_count: int
    refilled:     bool
    errors:       list[str]

@tool
def fill_missing_niches() -> dict:
    """Scan Google Sheet for products with an empty niche column."""
    products = get_products_without_niche()
    if not products: return {"updated": 0, "message": "All products already have niche set ✅"}
    VALID_NICHES = ["home", "kitchen", "cozy", "gadgets", "organize", "tech", "budget", "phone", "smarthome", "wfh"]
    updated = 0
    for p in products:
        name, keyword = p.get("product_name", ""), p.get("keyword", "")
        prompt = f"Categorization expert. Product: {name}. Available niches: {VALID_NICHES}. Choose SINGLE best exact match."
        try:
            niche = chat(prompt, temperature=0.1).strip().lower()
            if niche not in VALID_NICHES: niche = "home"
            update_niche(name, niche); updated += 1
            time.sleep(2.5)
        except Exception as e: logger.error(f"❌ Niche failed: {e}"); time.sleep(2.5)
    return {"updated": updated, "message": f"✅ {updated} niches filled"}

@tool
def analyze_niche_stock() -> dict:
    """AI selects a board and checks stock. Forces existing stock if > 150 items."""
    global CURRENT_TRIGGER
    allowed_niches = ["home", "kitchen", "cozy", "gadgets", "organize"] if "account1" in str(CURRENT_TRIGGER) else ["tech", "budget", "phone", "smarthome", "wfh"]
    total_pending = count_pending()
    pending_all = get_pending_products(limit=200, allowed_niches=allowed_niches)
    stock_map = {n: 0 for n in allowed_niches}
    for p in pending_all:
        if p.get("niche") in stock_map: stock_map[p.get("niche")] += 1
    if total_pending > 150:
        available_niches = [n for n, count in stock_map.items() if count > 0]
        chosen_niche = random.choice(available_niches) if available_niches else random.choice(allowed_niches)
        return {"selected_niche": chosen_niche, "stock_count": stock_map.get(chosen_niche, 0), "needs_fetching": False}
    chosen_niche = random.choice(allowed_niches)
    return {"selected_niche": chosen_niche, "stock_count": stock_map[chosen_niche], "needs_fetching": stock_map[chosen_niche] == 0}

@tool
async def fetch_aliexpress_products(niche: str, keyword: str = "") -> dict:
    """Fetches trending Amazon products for the selected niche. If no keyword, picks from niche list."""
    # 1. Agar keyword nahi hai, toh random niche keyword pick karo
    keywords_to_try = [keyword] if keyword else random.sample(KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS), 2)
    
    for attempt, kw in enumerate(keywords_to_try, 1):
        logger.info(f"🛒 Fetching for '{niche}' (Keyword: {kw})")
        raw = await search_products(keyword=kw, max_results=20, niche=niche)
        if not raw: continue
        linked = [enrich_with_affiliate_link(p) for p in raw]
        approved = [p for p in linked if filter_product(p)]
        if approved:
            for p in approved: p["niche"] = niche
            save_products(approved)
            return {"keyword": kw, "niche": niche, "fetched": len(raw), "approved": len(approved)}
    return {"approved": 0, "fetched": 0, "error": "Failed after all attempts."}

@tool
async def publish_next_pin(niche: str) -> dict:
    """Get next PENDING product for the niche and publish to Pinterest."""
    global CURRENT_TRIGGER
    target_account = "Account1_HomeDecor" if "account1" in str(CURRENT_TRIGGER) else "Account2_Tech"
    pending = get_pending_products(limit=1, allowed_niches=[niche])
    if not pending: return {"success": False, "reason": f"No products for {niche}"}
    product = pending[0]
    try:
        copy = generate_pin_copy(product)
        title, desc, tags = copy.get("title", "Amazon Find"), copy.get("description", ""), copy.get("tags", [])
        image_bytes = await process_product_image(product.get("image_url", ""), title)
        if not image_bytes: return {"success": False, "reason": "Image failed"}
        success = await post_to_pinterest(image_url=product.get("image_url"), title=title, description=desc, link=product.get("affiliate_link"), tags=tags, niche=niche, target_account=target_account)
        if success:
            mark_as_posted(product.get("product_name"))
            return {"success": True, "product": product.get("product_name"), "niche": niche}
    except Exception as e: return {"success": False, "reason": str(e)}
    return {"success": False}

# 🔥 REMOVED get_trending_keyword FROM HERE
ALL_TOOLS = [fill_missing_niches, analyze_niche_stock, fetch_aliexpress_products, publish_next_pin]

def _build_llm():
    _primary = ChatGroq(api_key=GROQ_API_KEY or "placeholder", model=GROQ_MODEL, temperature=0.1).bind_tools(ALL_TOOLS)
    _fallback = ChatOpenAI(api_key=CEREBRAS_API_KEY or "placeholder", base_url="https://api.cerebras.ai/v1", model=CEREBRAS_MODEL, temperature=0.1).bind_tools(ALL_TOOLS)
    return _primary.with_fallbacks([_fallback])

llm = _build_llm()

# 🔥 UPDATED PROTOCOL (No Step 3/Tavily)
SYSTEM_PROMPT = f"""You are PINTERESTO. Follow this exact protocol:
STEP 1 → CALL fill_missing_niches()
STEP 2 → CALL analyze_niche_stock()
STEP 3 → IF 'needs_fetching' is TRUE: CALL fetch_aliexpress_products(niche="<selected_niche>")
STEP 4 → CALL publish_next_pin(niche="<selected_niche>")
STEP 5 → END

MANDATORY END FORMAT:
NICHES FILLED: [X products updated]
TARGET BOARD: "[selected_niche]"
FETCHED: [X approved] OR "Skipped"
POSTED: "[product title]"
STATUS: Success/Failed"""

async def agent_node(state: BotState) -> dict:
    if len(state["messages"]) > 14: return {"messages": [SystemMessage(content="Loop Guard Triggered")]}
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}

def should_continue(state: BotState):
    last = state["messages"][-1]
    return "tools" if hasattr(last, "tool_calls") and len(last.tool_calls) > 0 else END

def build_agent():
    g = StateGraph(BotState)
    g.add_node("agent", agent_node); g.add_node("tools", ToolNode(ALL_TOOLS))
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()

async def run_agent(trigger: str = "scheduled"):
    global CURRENT_TRIGGER
    CURRENT_TRIGGER = trigger
    agent = build_agent()
    final_state = await agent.ainvoke({"messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=f"Run cycle: {trigger}")], "posted_count": 0, "refilled": False, "errors": []})
    summary = final_state["messages"][-1].content
    logger.info(f"✅ Summary:\n{summary}")
    return {"status": "ok", "summary": summary}
