import logging
import random
import time
from typing import Annotated
from typing_extensions import TypedDict

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI  # For Cerebras Fallback
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
from tools.tavily_search import get_trending_keyword

logger = logging.getLogger(__name__)

CURRENT_TRIGGER = None

class BotState(TypedDict):
    messages:     Annotated[list, add_messages]
    posted_count: int
    refilled:     bool
    errors:       list[str]

@tool
def fill_missing_niches() -> dict:
    """
    Scan Google Sheet for products with an empty niche column.
    Use AI to detect the correct niche from the product name and keyword.
    Call ONCE at the start of every run.
    """
    products = get_products_without_niche()
    if not products: 
        return {"updated": 0, "message": "All products already have niche set ✅"}

    VALID_NICHES = ["home", "kitchen", "cozy", "gadgets", "organize", "tech", "budget", "phone", "smarthome", "wfh"]
    updated = 0

    for p in products:
        name = p.get("product_name", "")
        keyword = p.get("keyword", "")
        prompt = f"Categorization expert. Product: {name}. Keyword: {keyword}. Available niches: {VALID_NICHES}. Choose SINGLE best exact match."
        try:
            niche = chat(prompt, temperature=0.1).strip().lower()
            if niche not in VALID_NICHES: 
                niche = "home"
            update_niche(name, niche)
            updated += 1
            logger.info(f"🏷️ Niche set: {name[:40]}... → {niche}")
            time.sleep(2.5) # Protects Google Sheets API quota
        except Exception as e:
            logger.error(f"❌ Niche detect failed: {name[:30]} — {e}")
            time.sleep(2.5)

    return {"updated": updated, "total": len(products), "message": f"✅ {updated}/{len(products)} niches filled"}

@tool
def analyze_niche_stock() -> dict:
    """
    AI selects a specific sub-niche (board) and checks its stock.
    Prevents sheet overflow by forcing existing stock usage if sheet has > 150 items.
    Call ONCE after filling niches.
    """
    global CURRENT_TRIGGER
    if CURRENT_TRIGGER in ["manual-account1", "scheduled-account1"]:
        allowed_niches = ["home", "kitchen", "cozy", "gadgets", "organize"]
    else:
        allowed_niches = ["tech", "budget", "phone", "smarthome", "wfh"]

    total_pending = count_pending()
    pending_all = get_pending_products(limit=200, allowed_niches=allowed_niches)
    
    stock_map = {n: 0 for n in allowed_niches}
    for p in pending_all:
        if p.get("niche") in stock_map:
            stock_map[p.get("niche")] += 1

    # 🔥 GUARD: 150 Limit Set Here
    if total_pending > 150:
        available_niches = [n for n, count in stock_map.items() if count > 0]
        if available_niches:
            chosen_niche = random.choice(available_niches)
            logger.info(f"🛑 Sheet limit reached ({total_pending} items)! Forcing AI to use existing stock from: '{chosen_niche}'")
            return {"selected_niche": chosen_niche, "stock_count": stock_map[chosen_niche], "needs_fetching": False}

    chosen_niche = random.choice(allowed_niches)
    count = stock_map[chosen_niche]
    
    logger.info(f"🎯 AI Selected Board Niche: '{chosen_niche}' | Stock: {count} | Total Sheet: {total_pending}")
    return {"selected_niche": chosen_niche, "stock_count": count, "needs_fetching": count == 0}

@tool
async def fetch_aliexpress_products(niche: str, keyword: str = "") -> dict:
    """
    Fetches trending products strictly for the selected niche.
    Requires 'keyword' fetched from Step 3 (Trend Hijacking).
    """
    # 1. Tavily wala fresh keyword sabse pehle try karenge!
    keywords_to_try = [keyword] if keyword else []
    
    # 2. Safety (Fallback) ke liye purane hardcoded keywords bhi add kar lenge
    # Agar kisi wajah se Tavily ka keyword fail hua, toh sheet khali nahi rahegi
    fallback_list = KEYWORDS_BY_NICHE.get(niche, DEFAULT_KEYWORDS)
    if fallback_list:
        import random
        keywords_to_try.extend(random.sample(fallback_list, min(2, len(fallback_list))))
    
    for attempt, kw in enumerate(keywords_to_try, 1):
        logger.info(f"🛒 [Attempt {attempt}/{len(keywords_to_try)}] Fetching for '{niche}' (Keyword: {kw})")
        
        # AliExpress API ko direct naya keyword bhej diya 🚀
        raw = await search_products(keyword=kw, max_results=20, niche=niche)
        
        if not raw:
            logger.warning(f"⚠️ 0 products found for '{kw}'. Trying next...")
            continue
            
        linked   = [enrich_with_affiliate_link(p) for p in raw]
        approved = [p for p in linked if filter_product(p)]
        
        if approved:
            # Force Correct Tag before saving
            for p in approved: 
                p["niche"] = niche
            save_products(approved)
            logger.info(f"✅ Success! Saved {len(approved)} products on attempt {attempt}.")
            return {"keyword": kw, "niche": niche, "fetched": len(raw), "approved": len(approved)}
        else:
            logger.warning(f"⚠️ AI rejected all products for '{kw}'. Trying next...")

    return {"approved": 0, "fetched": 0, "error": "Failed after all keyword attempts."}

@tool
async def publish_next_pin(niche: str) -> dict:
    """
    Get next PENDING product for the specific niche, generate viral copy, and publish.
    Call ONCE. 
    CRITICAL: The 'niche' parameter MUST be the EXACT same string returned by analyze_niche_stock's 'selected_niche' field.
    Do NOT call this if fetch_aliexpress_products returned approved=0.
    """
    global CURRENT_TRIGGER
    target_account = "Account1_HomeDecor" if "account1" in str(CURRENT_TRIGGER) else "Account2_Tech"

    pending = get_pending_products(limit=1, allowed_niches=[niche])
    if not pending: 
        return {"success": False, "reason": f"No products for niche: {niche}"}

    product = pending[0]
    name    = product.get("product_name", "Unknown")

    try:
        copy        = generate_pin_copy(product)
        title       = copy.get("title", name)
        description = copy.get("description", "")
        tags        = copy.get("tags", [])

        image_bytes = await process_product_image(product.get("image_url", ""), title)
        if not image_bytes: 
            return {"success": False, "reason": "Image processing failed"}

        success = await post_to_pinterest(
            image_url=product.get("image_url"), title=title, description=description,
            link=product.get("affiliate_link"), tags=tags, niche=niche,
            target_account=target_account
        )

        if success:
            mark_as_posted(name)
            logger.info(f"🎉 Posted: {name[:40]}... [{niche}] to {target_account}!")
            return {"success": True, "product": name, "title": title, "niche": niche}
        return {"success": False, "reason": "Webhook failed"}

    except Exception as e:
        logger.error(f"❌ publish error: {e}")
        return {"success": False, "reason": str(e)}

ALL_TOOLS = [fill_missing_niches, analyze_niche_stock, get_trending_keyword, fetch_aliexpress_products, publish_next_pin]

# 🔥 CEREBRAS FALLBACK SETUP 🔥
primary_llm = ChatGroq(api_key=GROQ_API_KEY, model=GROQ_MODEL, temperature=0.1).bind_tools(ALL_TOOLS)
fallback_llm = ChatOpenAI(api_key=CEREBRAS_API_KEY, base_url="https://api.cerebras.ai/v1", model=CEREBRAS_MODEL, temperature=0.1).bind_tools(ALL_TOOLS)

# Agar Groq 429 Limit marega, toh ye automatically Cerebras pe shift ho jayega!
llm = primary_llm.with_fallbacks([fallback_llm])

# 🔥 ELITE STRATEGIST SYSTEM PROMPT 🔥
SYSTEM_PROMPT = f"""You are PINTERESTO — an Elite AI Strategist and Senior Affiliate Marketing Director. You are a highly intelligent autonomous entity managing {len(PINTEREST_ACCOUNTS)} high-traffic Pinterest business accounts.

You possess the mindset of a top-tier Growth Hacker with over 10 years of experience in dominating Pinterest algorithms and maximizing affiliate revenue. You make calculated, data-driven, and highly efficient decisions. You do not guess, you do not retry blindly, and you execute with lethal precision.

═══════════════════════════════════════
EXECUTION PROTOCOL — FOLLOW EXACTLY
═══════════════════════════════════════
STEP 1 → CALL fill_missing_niches()
STEP 2 → CALL analyze_niche_stock() (Note: Pay attention to 'selected_niche' and 'needs_fetching')

STEP 3 → TREND HIJACKING (CONDITIONAL)
   - IF 'needs_fetching' is TRUE: CALL get_trending_keyword(niche="<selected_niche>"). Wait for the viral keyword.
   - IF 'needs_fetching' is FALSE: SKIP THIS STEP ENTIRELY.

STEP 4 → FETCH PRODUCTS (CONDITIONAL)
   - IF you performed Step 3: CALL fetch_aliexpress_products(niche="<selected_niche>", keyword="<keyword_from_step_3>").
   - IF you skipped Step 3: SKIP THIS STEP ENTIRELY.

STEP 5 → PUBLISH
   - CALL publish_next_pin(niche="<selected_niche>")

STEP 6 → END

MANDATORY END FORMAT:
NICHES FILLED: [X products updated]
TARGET BOARD: "[selected_niche]"
FETCHED: [X approved] via "[keyword]" OR "Skipped (stock existed)" OR "Failed (0 approved)"
POSTED: "[product title]" to [niche] board OR "Failed"
STATUS: Success / Partial / Failed"""

async def agent_node(state: BotState) -> dict:
    if len(state["messages"]) > 14:
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content="NICHES FILLED: Unknown\nTARGET BOARD: Unknown\nFETCHED: Unknown\nPOSTED: Stopped — loop guard\nSTATUS: Failed")]}
    logger.info(f"🧠 AI Strategist thinking... ({len(state['messages'])} messages)")
    response = await llm.ainvoke(state["messages"])
    return {"messages": [response]}

def should_continue(state: BotState) -> str:
    last = state["messages"][-1]
    return "tools" if hasattr(last, "tool_calls") and len(last.tool_calls) > 0 else END

def build_agent():
    g = StateGraph(BotState)
    g.add_node("agent", agent_node)
    g.add_node("tools", ToolNode(ALL_TOOLS))
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_continue, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()

async def run_agent(trigger: str = "scheduled") -> dict:
    global CURRENT_TRIGGER
    CURRENT_TRIGGER = trigger
    logger.info(f"🚀 AI Strategist started — {trigger}")
    agent = build_agent()
    final_state = await agent.ainvoke({
        "messages": [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=f"Run cycle. Trigger: {trigger}")],
        "posted_count": 0, "refilled": False, "errors": [],
    })
    summary = getattr(final_state["messages"][-1], "content", "Done")
    logger.info(f"✅ AI Strategist done:\n{summary}")
    return {"status": "ok", "summary": summary, "trigger": trigger}
