import httpx
import logging
from langchain_core.tools import tool
from config import TAVILY_API_KEY
from tools.llm import chat  # Tumhara LLM tool extract karne ke liye

logger = logging.getLogger(__name__)

@tool
def get_trending_keyword(niche: str) -> str:
    """
    Searches the web for the most viral and trending TikTok/Pinterest product keyword for a given niche.
    Use this to find a fresh keyword BEFORE fetching products from AliExpress.
    """
    logger.info(f"🌐 Tavily: Searching viral trends for '{niche}'...")
    
    # Ye query AI ke liye perfect search result layegi
    query = f"top trending viral tiktok aesthetic {niche} products 2026"
    
    try:
        with httpx.Client(timeout=20) as client:
            response = client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": TAVILY_API_KEY,
                    "query": query,
                    "search_depth": "basic",
                    "include_answer": True # Tavily ko bol rahe direct answer de
                }
            )
        response.raise_for_status()
        data = response.json()
        
        # Data extract karna
        answer = data.get("answer", "")
        results = " ".join([res.get("content", "") for res in data.get("results", [])[:3]])
        
        # Ab Groq/Cerebras ko bolenge is kachre me se ek diamond (keyword) nikal ke de
        prompt = f"""Based on this web search for '{niche}' niche: {answer} {results}. 
        Extract strictly ONE highly searchable product name (max 3-4 words). 
        Example: 'levitating desk lamp' or 'mushroom night light'. 
        Return ONLY the keyword, nothing else."""
        
        keyword = chat(prompt, temperature=0.2).strip().lower()
        
        # Safai
        keyword = keyword.replace("'", "").replace('"', "").strip()
        logger.info(f"🔥 Found Viral Keyword: '{keyword}'")
        
        return keyword

    except Exception as e:
        logger.error(f"❌ Tavily search failed: {e}")
        return f"aesthetic {niche} products" # Fallback agar api fail hui
        