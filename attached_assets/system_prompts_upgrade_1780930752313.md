# 🚀 Pinterest AI Pipeline — System Prompts Upgrade
# Firestore Board Routing + Trend Keyword Engine

---

## 📁 Step 1: New File — `tools/firebase_boards.py`

```python
import os
import time
import json
import firebase_admin
from firebase_admin import credentials, firestore

_db = None

def get_db():
    global _db
    if _db is not None:
        return _db
    if not firebase_admin._apps:
        # Option A: JSON file path
        cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
        # Option B: JSON string in env (HuggingFace Spaces me yeh use karo)
        cred_json = os.getenv("FIREBASE_CREDENTIALS_JSON")
        if cred_path and os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
        elif cred_json:
            cred = credentials.Certificate(json.loads(cred_json))
        else:
            raise ValueError("Firebase credentials nahi mili. FIREBASE_CREDENTIALS_JSON set karo.")
        firebase_admin.initialize_app(cred)
    _db = firestore.client()
    return _db

def get_boards(account: str) -> dict:
    """Firebase Firestore se active boards fetch karo, priority ke order mein"""
    db = get_db()
    docs = db.collection('boards').document(account).collection('items').stream()
    boards = {}
    for doc in docs:
        data = doc.to_dict()
        if data.get('active', True):
            boards[doc.id] = data
    # Priority ke hisab se sort karo
    return dict(sorted(boards.items(), key=lambda x: x[1].get('priority', 99)))

def get_active_trends(account: str, niche_key: str) -> list:
    """Ek niche ke active trend keywords fetch karo (expired check karta hai)"""
    db = get_db()
    doc = db.collection('trends').document(account).collection('items').document(niche_key).get()
    if not doc.exists:
        return []
    data = doc.to_dict()
    # expires_at milliseconds mein stored hai (JS Date.now() format)
    if data.get('expires_at', 0) < time.time() * 1000:
        return []  # Expired
    return data.get('keywords', [])

def get_all_active_trends(account: str) -> dict:
    """Saare active trend keyword sets fetch karo {niche_key: [kw1, kw2, ...]}"""
    db = get_db()
    docs = db.collection('trends').document(account).collection('items').stream()
    now = time.time() * 1000
    result = {}
    for doc in docs:
        data = doc.to_dict()
        if data.get('expires_at', 0) > now and data.get('keywords'):
            result[doc.id] = data['keywords']
    return result

def format_boards_for_prompt(boards: dict) -> str:
    """Boards ko AI-readable format mein convert karo"""
    if not boards:
        return "No boards configured."
    lines = []
    for niche_key, board in boards.items():
        kws = ", ".join(board.get('niche_keywords', []))
        lines.append(
            f"[{niche_key}] \"{board.get('board_name', niche_key)}\"\n"
            f"  Board ID  : {board.get('board_id', 'MISSING — set in Plinth app')}\n"
            f"  About     : {board.get('description', 'N/A')}\n"
            f"  Keywords  : {kws}\n"
            f"  Priority  : {board.get('priority', 99)}"
        )
    return "\n\n".join(lines)

def format_trends_for_prompt(trends: dict) -> str:
    """Active trends ko AI-readable format mein convert karo"""
    if not trends:
        return "No active trend keywords this week. Generic board keywords use honge."
    lines = []
    for niche_key, keywords in trends.items():
        lines.append(f"  [{niche_key}]: {', '.join(keywords[:10])}")
    return "\n".join(lines)
```

---

## 📁 Step 2: Update `MastermindState` — `graph.py`

```python
from typing import TypedDict, List, Dict, Optional

class MastermindState(TypedDict):
    # --- Existing ---
    account: str
    analytics_data: dict
    style_config: dict
    visual_prompt: str
    niche_affinity: str
    image_url: str
    pin_title: str
    pin_description: str
    pin_hashtags: list
    
    # --- NEW: Firebase ---
    boards: dict              # Firestore se fetch boards
    trend_keywords: dict      # {niche_key: [kw1, kw2]} — active only
    selected_board_id: str    # Pinterest board ID (CMO select karega)
    selected_board_niche: str # niche_key of selected board
    selected_board_name: str  # Board display name
    active_keywords: list     # Is niche ke active trend keywords
    primary_keyword: str      # Title ke pehle 40 chars mein aane wala keyword
    alt_text: str             # Pinterest SEO alt text
```

---

## 📁 Step 3: New Node — `nodes/node_firebase.py`

```python
from tools.firebase_boards import get_boards, get_all_active_trends

def node_firebase_loader(state: dict) -> dict:
    """
    CMO se PEHLE run hoga.
    Firestore se boards aur active trends load karta hai.
    """
    account = state.get("account", "account_1")
    print(f"[Firebase] Loading data for {account}...")
    
    try:
        boards = get_boards(account)
        trends = get_all_active_trends(account)
        print(f"[Firebase] ✅ {len(boards)} boards, {len(trends)} active trend sets")
    except Exception as e:
        print(f"[Firebase] ⚠️ Load failed: {e}. Empty data use karega.")
        boards, trends = {}, {}
    
    return {**state, "boards": boards, "trend_keywords": trends}
```

---

## 📁 Step 4: Updated CMO Prompt — `nodes/node_cmo.py`

```python
from tools.firebase_boards import format_boards_for_prompt, format_trends_for_prompt

CMO_SYSTEM_PROMPT = """
You are the Chief Marketing Officer AI for a Pinterest automation system.
Your job has TWO parts: (1) create the visual, (2) select the correct board.

━━━ PART 1: VISUAL CREATION ━━━
Design the next pin's visual concept, mood, and T2I prompt.
Be creative — reference seasonal trends and trending aesthetics.

━━━ PART 2: BOARD SELECTION (CRITICAL) ━━━

AVAILABLE BOARDS:
{boards_formatted}

ACTIVE TREND KEYWORDS THIS WEEK:
{trends_formatted}

BOARD SELECTION RULES:
1. Analyze the pin you just designed — what is its PRIMARY subject?
2. Match that subject to board keywords and description
3. STRICT matching rules:
   - Bedroom scene → bedroom_aesthetic ONLY
   - Garden/cottage/outdoor path/porch → cottage_garden ONLY
   - Living room/reading nook/cozy corner → cozy_living ONLY
   - Balcony/terrace/outdoor seating → balcony_outdoor ONLY
   - Desk/study/workspace → study_desk or cozy_wfh
   - Kawaii/pink gaming setup → kawaii_gaming ONLY
   - Pastel gaming room → pastel_gaming ONLY
   - Anime/Ghibli themed desk → anime_desk ONLY
4. Never mix niches (garden pin to bedroom board = WRONG)
5. Tie-breaker: lower priority number wins

TREND INJECTION:
- Check if selected board's niche_key has active trends above
- If yes: weave 1-2 trend keywords naturally into your visual prompt
- Set primary_keyword = single most relevant trend keyword
- If no active trends: primary_keyword = first board keyword

OUTPUT FORMAT (valid JSON only, no markdown):
{{
  "visual_prompt": "detailed image generation prompt...",
  "niche_affinity": "comma separated content tags",
  "style_label": "Short Style Name",
  "selected_board_id": "exact_board_id_from_above",
  "selected_board_niche": "niche_key",
  "selected_board_name": "Full Board Name",
  "primary_keyword": "main trend keyword",
  "active_keywords": ["kw1", "kw2", "kw3"],
  "board_selection_reason": "one line why this board was chosen"
}}
"""

def build_cmo_prompt(state: dict) -> str:
    return CMO_SYSTEM_PROMPT.format(
        boards_formatted=format_boards_for_prompt(state.get("boards", {})),
        trends_formatted=format_trends_for_prompt(state.get("trend_keywords", {})),
    )

# Node function mein:
def node_cmo(state: dict) -> dict:
    prompt = build_cmo_prompt(state)
    # ... apna existing LLM call karo prompt ke saath ...
    # CMO ke JSON output ko parse karo:
    # result = parse_cmo_output(llm_response)
    return {
        **state,
        "visual_prompt": result["visual_prompt"],
        "niche_affinity": result["niche_affinity"],
        "selected_board_id": result["selected_board_id"],
        "selected_board_niche": result["selected_board_niche"],
        "selected_board_name": result["selected_board_name"],
        "primary_keyword": result["primary_keyword"],
        "active_keywords": result["active_keywords"],
    }
```

---

## 📁 Step 5: Updated SEO Prompt — `nodes/node_seo.py`

```python
SEO_SYSTEM_PROMPT = """
You are a Pinterest SEO specialist. Write pin copy that ranks and saves.

PIN CONTEXT:
Board      : {board_name} ({board_niche})
Visual     : {visual_summary}
Primary KW : {primary_keyword}
Trend KWs  : {active_keywords_str}

━━━ TITLE (MOST IMPORTANT) ━━━
Pinterest indexes first 40 characters heavily.

FORMULA: [Primary Keyword] — [Hook/Number/Benefit]
✅ "Cozy Bedroom Ideas 2025 — 12 Dreamy Aesthetics"
✅ "Cottagecore Garden That Will Transform Your Space"
✅ "Kawaii Gaming Setup — Pink Aesthetic Desk Ideas"
❌ "Beautiful Room Decoration" (no keyword, no hook)
❌ "Amazing Home Decor" (too generic)

Rules:
- First 40 chars: primary_keyword MUST appear
- Total: 60-100 characters max
- Include number OR power word (Dreamy, Cozy, Ultimate, Perfect)

━━━ DESCRIPTION ━━━
- 150-250 words
- Open with primary_keyword in first sentence
- Naturally use 3-4 trend keywords throughout (don't stuff)
- Add one question mid-way (engagement boost)
- End soft CTA: "Save this for later 📌" or "Try this look →"
- NO hashtags inside description

━━━ HASHTAGS (exactly 15) ━━━
Mix:
- 3 mega tags (#HomeDecor #BedroomIdeas #InteriorDesign)
- 5 macro tags (#CozyBedroom #AestheticRoom #BedroomInspo)
- 4 micro tags (#DreamyBedroom2025 #CozyHomeAesthetic)
- 3 niche tags (trend keywords as hashtags, no spaces)
Always include #{PrimaryKeywordAsHashtag}

━━━ ALT TEXT ━━━
One descriptive sentence. Include primary_keyword naturally.
(Pinterest SEO ke liye important hai.)

OUTPUT (JSON only):
{{
  "title": "...",
  "description": "...",
  "hashtags": ["#tag1", "#tag2"],
  "alt_text": "..."
}}
"""

def build_seo_prompt(state: dict) -> str:
    keywords = state.get("active_keywords", [])
    primary  = state.get("primary_keyword", "")
    
    # Fallback: board keywords use karo agar trends nahi hain
    if not primary:
        board_niche = state.get("selected_board_niche", "")
        board = state.get("boards", {}).get(board_niche, {})
        bkws = board.get("niche_keywords", [])
        primary = bkws[0] if bkws else "home decor ideas"
        keywords = bkws[:5]
    
    pk_hashtag = "".join(w.capitalize() for w in primary.split())
    
    return SEO_SYSTEM_PROMPT.format(
        board_name=state.get("selected_board_name", "Home Decor"),
        board_niche=state.get("selected_board_niche", "home_decor"),
        visual_summary=state.get("visual_prompt", "")[:200],
        primary_keyword=primary,
        active_keywords_str=", ".join(keywords) if keywords else "none this week",
        PrimaryKeywordAsHashtag=pk_hashtag,
    )
```

---

## 📁 Step 6: Update `graph.py` — Firebase Node Add Karo

```python
from langgraph.graph import StateGraph, END
from nodes.node_firebase import node_firebase_loader
from nodes.node_cmo import node_cmo
from nodes.node_seo import node_seo
from nodes.node_execute import node_execute

def build_graph():
    g = StateGraph(MastermindState)
    
    g.add_node("firebase_loader", node_firebase_loader)  # ← NEW (pehla)
    g.add_node("cmo", node_cmo)
    g.add_node("seo", node_seo)
    g.add_node("execute", node_execute)
    
    g.set_entry_point("firebase_loader")         # ← pehle firebase load
    g.add_edge("firebase_loader", "cmo")
    g.add_edge("cmo", "seo")
    g.add_edge("seo", "execute")
    g.add_edge("execute", END)
    
    return g.compile()
```

---

## 📁 Step 7: Update `node_execute.py` — Dynamic Board ID

```python
def node_execute(state: dict) -> dict:
    board_id = state.get("selected_board_id", "")
    
    # Fallback agar CMO ne board_id nahi diya
    if not board_id:
        boards = state.get("boards", {})
        if boards:
            board_id = list(boards.values())[0].get("board_id", "")
        print(f"[Execute] ⚠️ No board_id from CMO, using fallback: {board_id}")
    
    payload = {
        "image_url"   : state.get("image_url"),
        "title"       : state.get("pin_title"),
        "description" : state.get("pin_description"),
        "hashtags"    : " ".join(state.get("pin_hashtags", [])),
        "alt_text"    : state.get("alt_text", ""),
        "board_id"    : board_id,              # ← Ab dynamic hai!
        "board_name"  : state.get("selected_board_name"),
        "account"     : state.get("account"),
    }
    # ... Make.com webhook call ...
```

---

## 📦 HuggingFace Spaces Setup

Firebase credentials ko Spaces secrets mein daal:

```
Secret name : FIREBASE_CREDENTIALS_JSON
Secret value: {entire service account JSON as single line string}
```

Service account JSON kaise milega:
```
Firebase Console
  → Project Settings
  → Service Accounts
  → Generate New Private Key
  → JSON download hoga
  → Uss JSON ko single line mein convert karo
  → HuggingFace Secrets mein paste karo
```

Single line convert karo (Python):
```python
import json
with open('serviceAccountKey.json') as f:
    print(json.dumps(json.load(f)))  # Yeh output copy karo
```

---

## ✅ Testing Checklist

```
[ ] Plinth app mein boards add kiye (Board IDs daale)
[ ] Kam se kam 1 niche ke trend keywords daale
[ ] FIREBASE_CREDENTIALS_JSON env variable set hai
[ ] node_firebase_loader logs mein boards dikh rahe hain
[ ] CMO output mein selected_board_id aa raha hai
[ ] SEO title ke pehle 40 chars mein primary_keyword hai
[ ] Make.com webhook mein sahi board_id ja raha hai
[ ] Pinterest mein pin sahi board pe post hua ✅
```

---

## 📊 Complete Flow

```
Pipeline Start
  ↓
node_firebase_loader
  → Firestore fetch: boards/{account}/items/*
  → Firestore fetch: trends/{account}/items/*
  → state: {boards: {...}, trend_keywords: {...}}
  ↓
node_cmo
  → Boards + trends prompt mein inject hote hain
  → Visual create karta hai
  → Board select karta hai (strict niche matching)
  → primary_keyword set karta hai
  → state: {visual_prompt, selected_board_id, primary_keyword, active_keywords}
  ↓
node_seo
  → primary_keyword → title ke first 40 chars mein
  → active_keywords → description mein weave
  → 15 hashtags generate karta hai (3 mega + 5 macro + 4 micro + 3 niche)
  → state: {pin_title, pin_description, pin_hashtags, alt_text}
  ↓
node_execute
  → Image generate
  → Make.com webhook → board_id (DYNAMIC) → Pinterest
  → Correct board pe post ✅
```
