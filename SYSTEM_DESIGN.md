# SYSTEM DESIGN — Finisher Tech AI
### Pinterest Automation System — Architecture Document
**Language: Hinglish (Hindi + English mix) | Audience: Builder studying their own system**

---

## SECTION 1 — THE BIRD'S EYE VIEW (Ek Nazar Mein Poora System)

### Yeh system kya karta hai?

"Finisher Tech AI" ek fully automated Pinterest marketing machine hai.  
Iska ek hi kaam hai: **bina kisi human input ke, din mein 6 Pinterest pins post karna** — 2 accounts par, 3 pins each — aur yeh sab AI ke through hona chahiye.

Pipeline ke 5 main phases hain:

```
[Scheduler Triggers] 
       ↓
[Mastermind CMO — Gemini analyzes analytics & decides strategy]
       ↓
[Fast Copywriters — Groq/Cerebras writes SEO title + description]
       ↓
[Execution Engine — Image generate karo, ImgBB pe upload karo]
       ↓
[Make.com Webhook — Pinterest pe post ho jaata hai]
```

---

### Do "Brains" hain system mein — Yeh samajhna ZAROORI hai

```
┌─────────────────────────────────────────────────────────────────────┐
│  BRAIN 1: CMO Mastermind (mastermind/graph.py)                      │
│                                                                     │
│  Yeh ek 4-node LangGraph pipeline hai.                              │
│  Iska kaam hai: DATA padhna → STRATEGY banana → COPY likhna →       │
│  IMAGE banana → Pinterest pe POST karna.                             │
│                                                                     │
│  Yeh apne andar sab kuch karta hai:                                 │
│  node_data → node_cmo → node_copy → node_execute                    │
│                                                                     │
│  Yeh MAIN production pipeline hai jo scheduler call karta hai.      │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│  BRAIN 2: LangGraph Execution Agent (agent.py)                      │
│                                                                     │
│  Yeh ek reactive "tool-calling" agent hai.                          │
│  Iska kaam hai: LLM (Groq/Cerebras) ko tools dena aur usse khud    │
│  decide karne dena ki kya karna hai.                                │
│                                                                     │
│  Tools: fill_missing_niches, analyze_niche_stock,                  │
│         fetch_aliexpress_products, publish_next_pin                  │
│                                                                     │
│  Yeh CMO Mastermind ka ek "toolkit" hai — aur standalone bhi        │
│  run ho sakta hai debugging/single-account cycles ke liye.          │
└─────────────────────────────────────────────────────────────────────┘
```

**Simple Rule:** CMO Mastermind = Strategic Director. LangGraph Agent = Field Operator with tools.

---

## SECTION 2 — VISUAL FLOWCHART (Mermaid.js)

```mermaid
flowchart TD
    A([🕐 APScheduler Trigger\nHar roz random time pe\nAccount1: 10AM-4PM\nAccount2: 7PM-1AM]) --> B

    B[main.py\nmastermind_scheduled_job] --> C

    subgraph MASTERMIND_GRAPH["🧠 MASTERMIND CEO GRAPH (mastermind/graph.py)"]
        C[NODE 1: node_data_intelligence\nGoogle Sheets se 7-day analytics padhta hai\nAccount1 → Analytics_Log sheet\nAccount2 → Analytics_logs2 sheet] --> D

        D[NODE 2: node_cmo_mastermind\nGemini 1.5 Flash ko analytics data bhejta hai\nGemini CMO persona mein sochta hai:\nHigh Impressions + Low Clicks → Visual Pivot\nHigh Engagement → Aggressive Affiliate Strike\nStagnant Growth → Viral-Bait] --> E

        E{Gemini API\nSuccessful?}
        E -- Haan ✅ --> F[CMO JSON Strategy Output\n{\n  account_1: { strategy, vibe, image_prompts },\n  account_2: { strategy, vibe, image_prompts }\n}]
        E -- Nahi ❌ --> G[Hardcoded Fallback:\nVisual Pivot strategy inject hoti hai\nPipeline kabhi nahi rukti]
        F --> H
        G --> H

        H[NODE 3: node_fast_copywriters\nGroq LLM — Llama 3.3 70B\nSEO Title 100 chars\nDescription 500 chars\n5 Niche hashtags\nFallback: Cerebras Llama 3.3] --> I

        I[NODE 4: node_execution_engine\nStrategy read karo\nProduct fetch karo Google Sheet se\nImage pipeline route karo\nImgBB pe upload karo\nMake.com webhook call karo] --> J
    end

    J([📌 Pinterest pe Pin Post Ho Gaya!])

    subgraph IMAGE_PIPELINE["🎨 IMAGE PIPELINE (node_execute.py + agent.py)"]
        I --> K{Strategy kya hai?}

        K -- Visual Pivot\nYA Viral-Bait --> L[PATH A: Text-to-Image\nAffiliate Link STRIP karo\nPure aesthetic pin]
        K -- Aggressive\nAffiliate Strike --> M[PATH B: Image-to-Image\nAffiliate Link RAKHO\nProduct composite karo]

        L --> N[PRIMARY: Pollinations.ai\nGET /p/encoded_prompt\n?width=1024&height=1792\n&model=flux]
        N -- Success ✅ --> P
        N -- Fail ❌ --> O[FALLBACK: Puter.js REST API\nPOST /drivers/call\ninterface: puter-image-generation]

        M --> O2[Puter.js I2I API\nPOST /drivers/call\nmethod: edit\nimage_url + aesthetic prompt]
        O2 -- Fail ❌ --> N2[Last Resort:\nPollinations T2I]

        O --> P
        O2 --> P
        N2 --> P

        P[Image Bytes Download\nhttpx.AsyncClient se\nbytes memory mein]
        P --> Q[⬆️ ImgBB Upload\nPOST api.imgbb.com/1/upload\nbase64 encoded bytes\nexpiration=1800 seconds\n30 min temporary URL]
        Q --> R[ImgBB Direct URL\nhttps://i.ibb.co/xxxxx/img.jpg]
    end

    R --> S[Make.com Webhook\nPOST to MAKE_WEBHOOK_URL\nPayload:\n- image_url: ImgBB URL\n- title, caption, link\n- board_id]

    subgraph AGENT_BRAIN["🤖 AGENT.PY — LangGraph Tool Agent"]
        T([Standalone Trigger\nrun_agent called]) --> U
        U[SystemPrompt inject:\nCMO strategy instructions\n5-step protocol] --> V
        V[Groq LLM\nTool Calling Mode] --> W

        W -- Step 1 --> X[fill_missing_niches\nEmpty niche columns classify karo]
        W -- Step 2 --> Y[analyze_niche_stock\nStock count check karo]
        Y -- needs_fetching: True --> Z[fetch_aliexpress_products\nAmazon RapidAPI se products laao\nAdmitad affiliate link add karo\nGoogle Sheet mein save karo]
        Y -- needs_fetching: False --> AA[Skip refill]
        Z --> AA
        AA --> AB[publish_next_pin\nniche + strategy + vibe + image_prompt]
        AB --> IMAGE_PIPELINE
    end

    subgraph GOOGLE_SHEET["📊 Google Sheet — Central Database"]
        GS1[Approved Deals Sheet\nColumns: product_name, product_id,\nsale_price, rating, orders,\naffiliate_link, image_url,\nkeyword, niche, Status]
        GS2[Analytics_Log - Account1]
        GS3[Analytics_logs2 - Account2]
    end

    C --> GS2
    C --> GS3
    I --> GS1
    Z --> GS1
```

---

## SECTION 3 — TOOL CONNECTIONS DEEP DIVE

### 3.1 — agent.py apne tools se kaise connect hota hai?

`agent.py` mein LangGraph ka **ToolNode pattern** use hota hai. Yeh kaam karta hai aisa:

```
LLM (Groq) ko saare tools bind karte hain:
llm = ChatGroq(...).bind_tools([
    fill_missing_niches,
    analyze_niche_stock,
    fetch_aliexpress_products,
    publish_next_pin
])

Phir StateGraph banate hain:
  "agent" node  → LLM call karo
  "tools" node  → LangGraph ka ToolNode (automatically tools execute karta hai)
  
Edge logic:
  agent → tools  (agar LLM ne tool_calls return kiye)
  tools → agent  (tool result wapas LLM ko bhejo)
  agent → END    (agar koi tool call nahi)
```

**Simple analogy:** LLM ek manager hai. Jab usse koi kaam karna ho, woh "tool call request" bhejta hai. ToolNode ek junior employee hai jo woh kaam actually karta hai aur result wapas manager ko de deta hai. Yeh loop tab tak chalta hai jab tak kaam complete na ho.

---

### 3.2 — `publish_next_pin` ka complete breakdown

Yeh sabse complex tool hai. Step by step samajhte hain:

```
publish_next_pin(
    niche = "home",                          ← Konsa board target karein
    strategy = "Visual Pivot",               ← CMO ka decision
    vibe = "Satisfying ASMR/Luxury...",      ← Gemini ka exact aesthetic command
    image_prompt = "flat-lay marble..."      ← Image generation direction
)
```

**Internal flow:**

```
STEP 1: Product fetch
  get_pending_products(limit=1, allowed_niches=[niche])
  → Google Sheet se pehla PENDING product laata hai
  → product = { product_name, image_url, affiliate_link, ... }

STEP 2: Affiliate link routing
  IF strategy in ("Visual Pivot", "Viral-Bait"):
      affiliate_link = ""   ← STRIP! Algorithm warm up karna hai
  ELSE (Aggressive Affiliate Strike):
      affiliate_link = product["affiliate_link"]  ← KEEP! Revenue time

STEP 3: SEO copy generate karo
  generate_pin_copy(product) via Groq LLM
  → Returns: title (100 chars), description (500 chars), tags (5)

STEP 4: Image pipeline route karo
  _orchestrate_image(strategy, vibe, image_prompt, raw_product_image_url)
  
  PATH A (Visual Pivot / Viral-Bait):
    _t2i_pollinations(prompt) → tries first
    If fails → _t2i_puter(prompt) → fallback
    
  PATH B (Aggressive Affiliate Strike):
    _i2i_puter(product_image_url, prompt) → product ko vibe mein composite karo
    If fails → _t2i_pollinations(prompt) → last resort

STEP 5: ImgBB mandatory gateway
  image_bytes download karo (httpx.AsyncClient)
  _upload_to_imgbb(image_bytes)
  → POST https://api.imgbb.com/1/upload
  → base64(image_bytes) + expiration=1800
  → Returns: "https://i.ibb.co/xxxxx/image.jpg"

STEP 6: Webhook call
  post_to_pinterest(image_url=imgbb_url, title, description, link, tags)
  → POST to Make.com webhook URL
  → Make.com Pinterest pe pin create karta hai

STEP 7: Mark as posted
  mark_as_posted(product_name)
  → Google Sheet mein Status = "POSTED"
```

---

### 3.3 — Strategy Routing Logic — Visual Summary

```
┌────────────────────────────────────────────────────────────────┐
│  CMO Strategy = "Visual Pivot" ya "Viral-Bait"                 │
├────────────────────────────────────────────────────────────────┤
│  Goal: Algorithm ko warm up karo, trust banao                  │
│  Image: Fresh AI-generated aesthetic (T2I)                     │
│  Link:  EMPTY — koi affiliate link nahi                        │
│  Flow:  Pollinations → (fail) → Puter T2I → ImgBB → Webhook   │
└────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────┐
│  CMO Strategy = "Aggressive Affiliate Strike"                  │
├────────────────────────────────────────────────────────────────┤
│  Goal: Paise kamao — product sell karo                         │
│  Image: Product image ko aesthetic vibe mein composite karo    │
│         (I2I — product + background merge)                     │
│  Link:  RAKHO — affiliate link full active                     │
│  Flow:  Puter I2I → (fail) → Pollinations T2I → ImgBB →       │
│         Webhook                                                │
└────────────────────────────────────────────────────────────────┘
```

---

## SECTION 4 — THE DATA LIFECYCLE

### 4A — Product Pin ka Safar (Aggressive Affiliate Strike)

Ek Amazon product ka poora journey — Google Sheet se Pinterest tak:

```
[DAY 0 — STOCKING PHASE]

1. fetch_aliexpress_products(niche="kitchen") call hota hai
   
2. Amazon RapidAPI se query:
   GET real-time-amazon-data.p.rapidapi.com/search
   params: { query: "smart kitchen gadgets", country: "US" }
   
3. Response: 20 raw products
   [{ asin: "B09XYZ", product_title: "Automatic Pot Stirrer",
      product_price: "$24.99", product_star_rating: 4.3,
      product_photo: "https://m.media-amazon.com/images/I/xyz.jpg" }]

4. filter_product() via Groq LLM:
   → Rating check, visual appeal check, viral potential check
   → Approve/Reject decision
   → "Automatic Pot Stirrer" → APPROVED ✅

5. enrich_with_affiliate_link():
   product_url = "https://www.amazon.com/dp/B09XYZ"
   affiliate_link = "https://www.amazon.com/dp/B09XYZ?tag=swiftmart0008-20"

6. save_products() → Google Sheet mein save:
   | product_name          | sale_price | rating | affiliate_link          | image_url      | niche   | Status  |
   | Automatic Pot Stirrer | $24.99     | 4.3    | amazon.com/dp/...tag=.. | m.media-amaz.. | kitchen | PENDING |

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

[PUBLISHING DAY — Jab scheduler trigger karta hai]

7. node_data_intelligence:
   Analytics sheet padhta hai → clicks=450, saves=320 (HIGH!)
   
8. node_cmo_mastermind (Gemini):
   Gemini dekhta hai: "High Clicks + High Saves = Conversion Ready"
   Output JSON:
   {
     "account_1": {
       "strategy": "Aggressive Affiliate Strike",
       "vibe": "Satisfying ASMR/Luxury kitchen aesthetic, warm marble textures",
       "image_prompts": ["Premium kitchen gadget on marble countertop, golden hour lighting"]
     }
   }

9. node_fast_copywriters (Groq):
   Product data + CMO vibe → SEO copy generate:
   title: "This $25 Pot Stirrer Changed My Cooking Forever ✨"
   description: "Hands-free cooking ka naya level! Automatic pot stirrer..."
   tags: ["KitchenHacks", "CookingGadgets", "HomeChef", "AmazonFinds", "KitchenOrganization"]

10. node_execution_engine:
    Strategy = "Aggressive Affiliate Strike" → PATH B (I2I)
    
    Puter I2I API call:
    POST api.puter.com/drivers/call
    {
      method: "edit",
      args: {
        image_url: "https://m.media-amazon.com/images/I/xyz.jpg",  ← Raw Amazon product
        prompt: "Premium kitchen gadget on marble countertop, golden hour, ASMR luxury"
      }
    }
    → Puter returns: "https://puter-cdn.com/generated/abc123.jpg"
    
11. Image bytes download:
    httpx.AsyncClient GET → 847,293 bytes in memory

12. ImgBB Upload:
    POST api.imgbb.com/1/upload
    { key: IMGBB_API_KEY, image: base64(...bytes...), expiration: 1800 }
    → ImgBB returns: "https://i.ibb.co/mBxK2p/abc123.jpg"

13. Make.com Webhook:
    POST https://hook.eu1.make.com/xxxxxxxxxxxxx
    {
      "image_url": "https://i.ibb.co/mBxK2p/abc123.jpg",
      "title": "This $25 Pot Stirrer Changed My Cooking Forever ✨",
      "caption": "Hands-free cooking... #KitchenHacks #CookingGadgets...",
      "link": "https://www.amazon.com/dp/B09XYZ?tag=swiftmart0008-20",
      "board_id": "909445787192891736"  ← Kitchen board
    }

14. Pinterest pe pin live! 🎉
    mark_as_posted("Automatic Pot Stirrer")
    → Google Sheet: Status = "POSTED"
```

---

### 4B — Viral Pin ka Safar (Viral-Bait Strategy)

Koi product nahi — sirf ek beautiful AI image jisse algorithm warm up ho:

```
[Gemini CMO Decision]
Analytics mein stagnation detect hota hai:
  impressions_avg: 0 (naya account / inactive period)
  Gemini output: strategy = "Viral-Bait"
  vibe = "Apple-style Liquid Glassmorphism — frosted glass, cinematic"
  image_prompt = "Minimalist WFH desk setup, iPhone floating on gradient"

[Execution]
Strategy = "Viral-Bait" → PATH A (T2I)

Pollinations.ai call:
GET pollinations.ai/p/Minimalist%20WFH%20desk%20setup%2C%20iPhone...
   &width=1024&height=1792&nologo=true&model=flux&seed=47832

→ Image bytes download (pure AI generated, koi product nahi)

ImgBB upload → Make.com webhook:
{
  "image_url": "https://i.ibb.co/xxxxx/viral.jpg",
  "title": "Your Dream WFH Setup ✨",
  "caption": "Aesthetic desk goals... #WFHSetup #DeskGoals...",
  "link": "",          ← EMPTY — affiliate link STRIP ho gayi
  "board_id": "1093952634426985796"  ← WFH board
}

→ Pinterest pe beautiful aesthetic pin post
→ Algorithm engagement badhta hai
→ Agli baar Gemini "Aggressive Affiliate Strike" trigger karega
→ Tab real affiliate products post honge → Revenue 💰
```

---

## SECTION 5 — KEY FILES AT A GLANCE

| File | Role | Key Dependency |
|---|---|---|
| `main.py` | FastAPI server + APScheduler | `mastermind/graph.py` |
| `mastermind/graph.py` | 4-node pipeline orchestrator | All 4 nodes |
| `mastermind/node_data.py` | Analytics reader | `tools/google_drive.py` |
| `mastermind/node_cmo.py` | Gemini CMO strategist | `google-genai` SDK |
| `mastermind/node_copy.py` | SEO copy writer | `tools/llm.py` (Groq) |
| `mastermind/node_execute.py` | Image gen + webhook | `tools/make_webhook.py` |
| `agent.py` | Standalone LangGraph agent | All tools + LLM |
| `tools/aliexpress.py` | Amazon product fetcher | RapidAPI |
| `tools/admitad.py` | Affiliate link builder | `AMAZON_STORE_ID` |
| `tools/google_drive.py` | Google Sheet CRUD | `gspread` |
| `tools/groq_ai.py` | Product filter + copy gen | `tools/llm.py` |
| `tools/llm.py` | LLM wrapper (Groq+Cerebras) | API keys |
| `tools/make_webhook.py` | Pinterest poster | `MAKE_WEBHOOK_URL` |
| `config.py` | All env vars centralized | `.env` / Replit secrets |

---

## SECTION 6 — ENVIRONMENT VARIABLES (Kya Set Karna Hai)

```
# LLM APIs
GROQ_API_KEY          → Groq (primary LLM — Llama 3.3 70B)
CEREBRAS_API_KEY      → Cerebras (fallback LLM)
GEMINI_API_KEY        → Google Gemini 1.5 (CMO brain)

# Product Sourcing
RAPIDAPI_KEY          → Amazon product search

# Google Sheets (Analytics + Product DB)
GOOGLE_CREDS_JSON     → Service account JSON (stringify karke dalo)
SPREADSHEET_ID        → Google Sheet ka ID (URL mein hota hai)

# Image Pipeline
IMGBB_API_KEY         → ImgBB upload (MANDATORY gateway)
PUTER_API_KEY         → Puter.js I2I / T2I fallback

# Pinterest Webhooks
MAKE_WEBHOOK_URL      → Account 1 (HomeDecor) Make.com webhook
MAKE_WEBHOOK_URL_2    → Account 2 (Tech) Make.com webhook
```

---

## SECTION 7 — QUICK REFERENCE: Kab Kya Hota Hai

```
Scheduler trigger aata hai
        ↓
mastermind_scheduled_job() called
        ↓
run_mastermind(trigger="scheduled-account1")
        ↓
        ├── DATA node: Sheets se analytics
        ├── CMO node: Gemini strategy decide karta hai
        ├── COPY node: Groq SEO copy likhta hai
        └── EXECUTE node:
                ├── Stock check implicit (niche ke products fetch)
                ├── Strategy route: Viral-Bait/Visual Pivot → T2I
                │                  Affiliate Strike → I2I
                ├── Pollinations → fail → Puter fallback
                ├── Bytes → ImgBB (30 min temp URL)
                └── ImgBB URL → Make.com → Pinterest ✅
```

---

*Document generated by Lead Systems Architect AI — Finisher Tech AI v2.0*  
*Last updated: April 2026*
