# BACKEND CODE GENERATION PROMPTS — Pinteresto v4 Blog System
### Firebase Backend — Ready-to-use AI Prompts
**Use:** Claude / GPT-4 / Gemini ko yeh prompts do → seedha code milega
**May 2026**

---

## HOW TO USE THESE PROMPTS

```
1. Ek prompt copy karo
2. Claude / AI ko do
3. Code milega → apne project mein paste karo
4. Next prompt lo → repeat
5. Sab ho jaaye → backend ready!
```

---

## PROMPT 1 — Firebase Publisher Tool

```
You are an expert Python backend developer.

I have an existing Pinterest automation system called "Pinteresto v3".
I need you to create a NEW file: tools/firebase_publisher.py

This file will save blog post data to Firebase Firestore.

EXISTING SYSTEM CONTEXT:
- Python async codebase (FastAPI + asyncio)
- config.py has: FIREBASE_CREDS_JSON (stringified JSON), BLOG_BASE_URL
- Uses firebase-admin Python SDK
- All functions are async where possible

FIREBASE COLLECTIONS NEEDED:
1. "blog_posts" — Main collection, document ID = slug
2. "collections" — Auto-updated when posts saved (niche/sub-niche grouping)
3. "daily_counter" — Document ID = YYYY-MM-DD date string

BLOG POST DOCUMENT SCHEMA:
{
  slug, title, seo_title, meta_desc, excerpt,
  niche, sub_niche, style_name, collection_tag,
  image_url, pinterest_url,
  paragraphs: [{id: int, text: str}],
  products: [{name, price, affiliate_url, insert_after_para: int}],
  faq: [{question, answer}],
  tags: [str], primary_keyword, status, views, created_at, updated_at, account
}

COLLECTIONS DOCUMENT SCHEMA:
{
  collection_tag, niche, sub_niche, title, description,
  cover_image, slug_list: [str], pin_count, last_updated
}

FUNCTIONS TO CREATE:
1. _get_db() → Firebase client (lazy init, singleton pattern)
2. async save_blog_post(blog_data: dict) → str (returns blog_url)
   - Save to blog_posts collection
   - Auto-call _update_collection()
   - Build blog_url: {BLOG_BASE_URL}/{niche}/{sub_niche}/{slug}
3. async _update_collection(db, blog_data) → None
   - If collection exists: add slug to slug_list, increment pin_count
   - If not: create new collection document
   - Title logic: f"Top {sub_niche.title()} Ideas"
4. async check_and_increment_daily_counter() → bool
   - Document ID = str(date.today())
   - If exists and blog_count >= 2: return False
   - If exists and count < 2: increment + return True
   - If not exists: create with blog_count=1, return True
5. async get_all_posts(limit=20) → list[dict]
   - Filter: status == "published"
   - Order: created_at DESC
6. async get_post_by_slug(slug: str) → dict | None
   - Increment views on fetch

IMPORTANT:
- Firebase init only once (check firebase_admin._apps)
- Use firestore.SERVER_TIMESTAMP for timestamps
- Use firestore.Increment() for counters
- All errors should be caught and logged, not raised
- collection_tag document ID: collection_tag.replace("/", "-")

Return complete, production-ready Python code.
```

---

## PROMPT 2 — node_blog_trigger.py

```
You are an expert Python developer working on an async AI pipeline.

I need you to create: mastermind/node_blog_trigger.py

CONTEXT — Existing System (Pinteresto v3):
- LangGraph state machine with 3 nodes already running
- State object: MastermindState (TypedDict)
- Each node receives full state dict, returns updated state dict
- All nodes are async functions

EXISTING STATE FIELDS (already present, do not redefine):
  a1_cmo_strategy: dict  — has keys: pin_type, style_name, ratio, title, description, tags, visual_prompt
  a2_cmo_strategy: dict
  cycle_trigger: str     — "account1", "account2", or "both"

NEW STATE FIELDS THIS NODE WILL ADD:
  should_create_blog: bool
  last_posted_image_url: str  — already set by agent after pin is posted

THIS NODE'S JOB:
  Decide: should we create a blog post for this pin?

LOGIC:
1. Check if FIREBASE_CREDS_JSON env var is set → if not, return should_create_blog=False
2. Check if last_posted_image_url is present in state → if empty, return False
3. Import and call: check_and_increment_daily_counter() from tools.firebase_publisher
   → if returns False (limit reached), return should_create_blog=False
4. Check pin_type from active account's cmo_strategy:
   - Determine active account from cycle_trigger
   - Only proceed if pin_type == "VIRAL_PIN"
5. If all checks pass: return should_create_blog=True

FUNCTION SIGNATURE:
  async def node_blog_trigger(state: dict) -> dict

PRINT STATEMENTS:
  "📝 Blog trigger: GO" or "📝 Blog trigger: SKIP — [reason]"

Return complete Python code only.
```

---

## PROMPT 3 — node_product_researcher.py

```
You are an expert Python AI developer.

Create: mastermind/node_product_researcher.py

CONTEXT — Pinteresto v3 System:
- Uses Google Gemini (google-genai SDK) for vision tasks
- Uses httpx for async HTTP
- tools/aliexpress.py has: fetch_products_for_keyword(keyword, limit) async function
  Returns list of: {product_name, sale_price, rating, affiliate_link, image_url, product_url}
- tools/admitad.py has: build_affiliate_link(url) → str
- config.py has: GEMINI_API_KEY

STATE INPUT (from previous nodes):
  should_create_blog: bool
  last_posted_image_url: str  — ImgBB URL of the Pinterest pin image
  a1_cmo_strategy / a2_cmo_strategy: dict with style_name, tags
  cycle_trigger: str

STATE OUTPUT (add to state):
  blog_products: list[dict]
  Each product: {name, price, affiliate_url, insert_after_para: int, why_fits: str}

FUNCTION SIGNATURE:
  async def node_product_researcher(state: dict) -> dict

LOGIC:
1. If not state.get("should_create_blog"): return state unchanged
2. Get active strategy based on cycle_trigger
3. Download image from last_posted_image_url → base64 encode
4. Call Gemini Vision (gemini-2.5-flash model) with image + prompt:
   - Identify 4-5 physical products from the aesthetic image
   - Return JSON array: [{product_name, search_keyword, price_range, why_fits, suggested_para: int}]
   - suggested_para: which paragraph number this product fits after (1-8)
5. For each identified product:
   - Call fetch_products_for_keyword(search_keyword, limit=1)
   - If result found: build affiliate link via build_affiliate_link()
   - Build product dict with insert_after_para from suggested_para
6. Max 4 products in final list
7. If any product lookup fails: skip it, continue with rest (no crash)

GEMINI VISION CALL:
- Use google.genai Client
- Pass image as inline_data with mime_type image/jpeg
- Force JSON response (clean parsing)
- Handle ``` json ``` wrapping in response

PRINT: "🛍️ Products researched: {count} found"

Return complete async Python code.
```

---

## PROMPT 4 — node_blog_writer.py

```
You are an expert Python developer specializing in AI content generation.

Create: mastermind/node_blog_writer.py

CONTEXT — Pinteresto v3:
- Uses Google Gemini (google-genai SDK)
- config.py has: GEMINI_API_KEY
- Target audience: Women 25-44, US-based, love aesthetic home decor

STATE INPUT:
  should_create_blog: bool
  blog_products: list[dict]  — [{name, price, affiliate_url, insert_after_para, why_fits}]
  a1_cmo_strategy / a2_cmo_strategy: dict — {style_name, title, description, tags, visual_prompt}
  last_posted_image_url: str
  cycle_trigger: str

STATE OUTPUT (add to state):
  blog_content: dict with ALL fields below

BLOG CONTENT SCHEMA (blog_content dict):
{
  "title": str,           — SEO title max 60 chars
  "slug": str,            — URL-friendly slug
  "seo_title": str,       — meta title 55-60 chars
  "meta_description": str,— 150-160 chars with CTA
  "primary_keyword": str,
  "excerpt": str,         — teaser 150 chars
  "tags": list[str],      — 5 tags
  "niche": str,           — e.g. "home-decor"
  "sub_niche": str,       — e.g. "kitchen"
  "collection_tag": str,  — e.g. "home-decor/kitchen"
  "image_url": str,       — same as last_posted_image_url
  "style_name": str,
  "paragraphs": [         — 8-10 paragraphs
    {"id": 1, "text": "..."},
    {"id": 2, "text": "..."},
    ...
  ],
  "faq": [                — 3 FAQ items for Google snippets
    {"question": "...", "answer": "..."},
    ...
  ]
}

NOTE: Products are already in state["blog_products"] with insert_after_para set.
The blog writer just needs to write paragraphs that MENTION those products naturally.
Products will be injected by Next.js frontend based on insert_after_para.

GEMINI PROMPT STRATEGY:
- Use response_mime_type="application/json" for clean JSON
- model: gemini-2.5-flash
- Tell Gemini: write 8-10 paragraphs, each ~120-150 words
- Each paragraph should naturally mention context of the product
  that will appear after it (based on blog_products list)
- Include niche/sub_niche assignment logic in prompt
- FAQ: 3 questions a US home decor buyer would Google

NICHE MAPPING LOGIC (in prompt to Gemini):
  style_name "Kitchen" related → niche: home-decor, sub_niche: kitchen
  style_name "Bedroom" related → niche: home-decor, sub_niche: bedroom
  style_name "Tech/Gaming" related → niche: tech-setup, sub_niche: desk-setup
  collection_tag = niche + "/" + sub_niche

FUNCTION SIGNATURE:
  async def node_blog_writer(state: dict) -> dict

PRINT: "✍️ Blog written: {title}"

Return complete async Python code.
```

---

## PROMPT 5 — node_firebase_publisher.py

```
You are a Python backend developer.

Create: mastermind/node_firebase_publisher.py

CONTEXT:
- tools/firebase_publisher.py has: save_blog_post(blog_data: dict) → str (returns blog_url)
- blog_url format: {BLOG_BASE_URL}/{niche}/{sub_niche}/{slug}

STATE INPUT:
  should_create_blog: bool
  blog_content: dict     — full blog data with paragraphs, niche, sub_niche, etc
  blog_products: list    — products with insert_after_para
  last_posted_image_url: str
  cycle_trigger: str

STATE OUTPUT:
  blog_url: str          — published URL or "" if failed
  blog_published: bool

LOGIC:
1. If not should_create_blog or not blog_content: return state unchanged
2. Merge blog_content + blog_products + image_url into one blog_data dict
3. Call: blog_url = await save_blog_post(blog_data)
4. If success: blog_published=True, blog_url=url
5. If any exception: log error, blog_published=False, blog_url=""
   CRITICAL: Pinterest pin is already live — DO NOT crash or raise

IMPORTANT:
- blog_data passed to save_blog_post must include "products" key (from blog_products)
- Try/except MUST wrap the entire save operation
- Print success: "🔥 Blog saved: {blog_url}"
- Print failure: "❌ Firebase failed: {error} — pin still live ✅"

FUNCTION SIGNATURE:
  async def node_firebase_publisher(state: dict) -> dict

Return complete Python code.
```

---

## PROMPT 6 — mastermind/state.py UPDATE

```
You are a Python developer.

I have an existing mastermind/state.py with MastermindState TypedDict.
Add these NEW fields to the existing TypedDict (do not remove any existing fields):

EXISTING FIELDS (keep all of these):
  a1_raw_analytics: list
  a2_raw_analytics: list
  a1_cmo_strategy: dict
  a2_cmo_strategy: dict
  cycle_trigger: str
  a1_publish_status: dict
  a2_publish_status: dict

NEW FIELDS TO ADD:
  should_create_blog: bool
  blog_products: list
  blog_content: dict
  blog_url: str
  blog_published: bool
  last_posted_image_url: str

Use Optional[] with default None where appropriate since these fields
won't exist at pipeline start.

Return the complete updated state.py file.
```

---

## PROMPT 7 — mastermind/graph.py UPDATE

```
You are a Python developer working with LangGraph.

I have an existing mastermind/graph.py with a 3-node LangGraph pipeline:
  Node 1: "data_intelligence"  (node_data_intelligence)
  Node 2: "cmo_mastermind"     (node_cmo_mastermind)
  Node 3: "agent_executor"     (node_agent_executor)
  Current END: after agent_executor

ADD these 4 new nodes AFTER agent_executor:
  Node 4: "blog_trigger"       (node_blog_trigger)
  Node 5: "product_researcher" (node_product_researcher)
  Node 6: "blog_writer"        (node_blog_writer)
  Node 7: "firebase_publisher" (node_firebase_publisher)

IMPORT ADDITIONS (add to existing imports):
  from mastermind.node_blog_trigger import node_blog_trigger
  from mastermind.node_product_researcher import node_product_researcher
  from mastermind.node_blog_writer import node_blog_writer
  from mastermind.node_firebase_publisher import node_firebase_publisher

EDGE CHANGES:
  REMOVE: agent_executor → END
  ADD:    agent_executor → blog_trigger
  ADD:    blog_trigger → product_researcher
  ADD:    product_researcher → blog_writer
  ADD:    blog_writer → firebase_publisher
  ADD:    firebase_publisher → END

Keep ALL existing code exactly as-is.
Only add the new nodes, imports, and edges.

Return the complete updated graph.py file.
```

---

## PROMPT 8 — config.py UPDATE

```
You are a Python developer.

I have an existing config.py that loads environment variables.
Add these 2 new environment variables to the existing file:

# Blog — Firebase (V4 Addition)
FIREBASE_CREDS_JSON = os.getenv("FIREBASE_CREDS_JSON", "")
BLOG_BASE_URL       = os.getenv("BLOG_BASE_URL", "https://yourblog.vercel.app")

Keep ALL existing variables exactly as-is.
Just add these 2 new lines in a new section at the bottom.

Return the addition only (not full file — just the 4 lines to add).
```

---

## PROMPT 9 — tools/make_webhook.py UPDATE

```
You are a Python developer.

I have an existing tools/make_webhook.py.
The main function signature is:
  async def post_to_pinterest(image_url, title, description, link, tags, niche, target_account) -> bool

Make this ONE change:
1. Add blog_url: str = "" as a new optional parameter
2. In the payload dict, change the "link" field:
   - If blog_url is not empty: use blog_url
   - If blog_url is empty: use existing link (affiliate_link or "")

Keep everything else exactly the same.

Return ONLY the modified function signature and the changed payload line.
Do not return the full file — just the diff/changes.
```

---

## PROMPT 10 — agent.py UPDATE (last_posted_image_url)

```
You are a Python developer.

In my existing agent.py, after a Pinterest pin is successfully posted,
I need to save the image URL to the LangGraph state so the blog pipeline can use it.

The image URL is available as a variable (likely called image_url or imgbb_url)
at the point where mark_as_posted() is called.

Find the location in agent.py where:
  mark_as_posted(product_name) is called
  AND the pin has been confirmed as successfully posted

At that location, add this to whatever state/result dict is returned:
  "last_posted_image_url": <the_image_url_variable>

This will make the image available to node_blog_trigger and subsequent blog nodes.

IMPORTANT:
- Do not change any other logic
- If the state is returned as a dict, just add the key
- If returned differently, adapt accordingly

Return only the specific code block that needs to change (before and after).
```

---

## PROMPT 11 — requirements.txt UPDATE

```
Add this one line to my existing requirements.txt:

firebase-admin==6.5.0

Return only this one line.
```

---

## PROMPT 12 — Firebase Setup + Environment Variable

```
Give me step by step instructions to:

1. Create a Firebase project named "pinteresto-blog"
2. Enable Firestore Database in Production mode
3. Create a Service Account and download the JSON key
4. Set Firestore Security Rules so:
   - blog_posts: public read, no write (only backend writes)
   - collections: public read, no write
   - daily_counter: no public access (private)
5. How to convert the service account JSON to a single-line string
   for the FIREBASE_CREDS_JSON environment variable

Keep instructions short and clear. CLI commands where possible.
```

---

## PROMPT 13 — FULL INTEGRATION TEST

```
You are a Python developer helping me test a new feature.

I have added a 4-node blog pipeline to my existing Python system.
The pipeline runs after a Pinterest pin is posted.

Write a test script: test_blog_pipeline.py

This script should:
1. Create a mock state dict with all required fields:
   - should_create_blog: True
   - last_posted_image_url: "https://i.ibb.co/test/image.jpg" (fake)
   - a1_cmo_strategy: {pin_type: "VIRAL_PIN", style_name: "Pastel Dreamy Kitchen",
                        title: "Test Pin", description: "Test", tags: ["test"],
                        visual_prompt: "pastel kitchen"}
   - cycle_trigger: "account1"
   - blog_products: [
       {name: "Test Light", price: "$29.99",
        affiliate_url: "https://amazon.com/test", insert_after_para: 1,
        why_fits: "Perfect for kitchen"}
     ]

2. Test each node individually:
   - Call node_blog_trigger(mock_state) → print result
   - Call node_product_researcher(mock_state) → print blog_products count
   - Call node_blog_writer(mock_state) → print blog title + paragraph count
   - Call node_firebase_publisher(mock_state) → print blog_url

3. Also test Firebase connection:
   - Call get_all_posts(limit=5) → print count
   - Call get_post_by_slug("test-slug") → print exists or not

4. Use asyncio.run() to run all async functions
5. Print clear PASS/FAIL for each test

Return complete test_blog_pipeline.py file.
```

---

## CORRECT ORDER TO USE THESE PROMPTS

```
Step 1:  Prompt 11 → requirements.txt (install firebase-admin)
Step 2:  Prompt 12 → Firebase setup karo (manual, one time)
Step 3:  Prompt 8  → config.py update (env vars add)
Step 4:  Prompt 6  → state.py update (new fields)
Step 5:  Prompt 1  → tools/firebase_publisher.py (create)
Step 6:  Prompt 2  → node_blog_trigger.py (create)
Step 7:  Prompt 3  → node_product_researcher.py (create)
Step 8:  Prompt 4  → node_blog_writer.py (create)
Step 9:  Prompt 5  → node_firebase_publisher.py (create)
Step 10: Prompt 10 → agent.py (last_posted_image_url add)
Step 11: Prompt 9  → make_webhook.py (blog_url param add)
Step 12: Prompt 7  → graph.py (nodes + edges add)
Step 13: Prompt 13 → test_blog_pipeline.py (test karo)

TOTAL: 13 prompts → Complete backend ready!
```

---

## ENVIRONMENT VARIABLES TO ADD

```bash
# Firebase
FIREBASE_CREDS_JSON={"type":"service_account","project_id":"pinteresto-blog",...}
BLOG_BASE_URL=https://yourblog.vercel.app

# V3 Existing — unchanged
GROQ_API_KEY=...
GEMINI_API_KEY=...
GOOGLE_CREDS_JSON=...
IMGBB_API_KEY=...
MAKE_WEBHOOK_URL=...
MAKE_WEBHOOK_URL_2=...
RAPIDAPI_KEY=...
```

---

*PINTERESTO v4 — Finisher Tech AI*
*13 Prompts → Complete Firebase Blog Backend*
*June 3 ke baad use karo — Exam pehle! 📚*
*May 2026*
