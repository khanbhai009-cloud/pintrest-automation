# Pinteresto Pipeline — Integration Guide

Ye guide tumhe batata hai ki jab pipeline ko actually **live** karna ho toh kya karna hai.
Abhi sirf files bani hain — sab kuch **ready** hai, sirf main.py me endpoints add karne hain.

---

## Pipeline Ka Full Flow

```
Keyword
  └─ Step 2 → pin_content_agent   → Title + Description + Hashtags
  └─ Step 3 → prompt_selector     → Prompts_Master se best T2I prompt
  └─ Step 4 → image_creator       → Image generate → ImgBB URL
  └─ Step 5 → product_extractor   → Image me dikhne wale products extract
  └─ Step 6 → amazon_fetcher      → Amazon search + similarity check + affiliate link
  └─ Step 7 → blog_agent          → SEO Blog HTML (Gemini → Gemini2 → Groq)
  └─ Step 8 → firebase_publisher  → Firebase Firestore me push → Slug return
  └─ Step 9 → pinterest_publisher → Pin post with blog URL
```

---

## Secrets Jo Set Karne Hain (Replit Secrets tab)

| Secret | Value | Kahan use hota hai |
|--------|-------|--------------------|
| `GEMINI_API_KEY` | Google AI Studio se | Pin content, Product extractor, Blog agent |
| `GEMINI_API_KEY_2` | Backup Gemini key | Fallback on 429 |
| `GROQ_API_KEY` | groq.com se | Last resort for all AI steps |
| `RAPIDAPI_KEY` | rapidapi.com se | Amazon product search |
| `IMGBB_API_KEY` | imgbb.com se | Image hosting |
| `MAKE_WEBHOOK_URL` | Make.com scenario URL | Account 1 Pinterest posting |
| `MAKE_WEBHOOK_URL_2` | Make.com scenario URL | Account 2 Pinterest posting |
| `GOOGLE_CREDS_JSON` | GCP service account JSON | Drive + Sheets |
| `SPREADSHEET_ID` | Google Sheet ID | Prompts_Master, Vision_Tracker, etc. |
| `FIREBASE_CREDS_JSON` | Firebase service account JSON | Blog publish |
| `FIREBASE_PROJECT_ID` | e.g. `my-pinterest-blog` | Firebase init |
| `BLOG_BASE_URL` | e.g. `https://yourblog.com` | Pinterest pin ka link |

---

## Firebase Setup (Blog Publisher ke liye)

### Step 1: Firebase Project Banao
1. Jao: https://console.firebase.google.com
2. "Add project" click karo → project name do
3. Firestore Database → "Create database" → **Native mode** select karo → region choose karo

### Step 2: Service Account JSON Download Karo
1. Firebase Console → Project Settings (gear icon) → Service Accounts
2. "Generate new private key" click karo → JSON download ho jayegi
3. Us JSON ka **poora content** copy karo
4. Replit Secrets me jao → `FIREBASE_CREDS_JSON` = paste karo
5. `FIREBASE_PROJECT_ID` = apna Firebase project ID (e.g. `my-pinterest-blog-abc12`)

### Step 3: firebase-admin Install Karo
```bash
pip install firebase-admin
```

### Step 4: Firestore Security Rules (Firebase Console me)
```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Blog posts: publicly readable, only server can write
    match /blogs/{slug} {
      allow read: if true;
      allow write: if false;  // Only service account writes
    }
  }
}
```

---

## Next.js Blog Site — Firebase se Data Fetch Karo

### Install Firebase SDK
```bash
npm install firebase
```

### `lib/firebase.js`
```javascript
import { initializeApp } from 'firebase/app';
import { getFirestore } from 'firebase/firestore';

const firebaseConfig = {
  apiKey:            process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
  authDomain:        "your-project.firebaseapp.com",
  projectId:         process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
  storageBucket:     "your-project.appspot.com",
  messagingSenderId: "...",
  appId:             "...",
};

const app = getializeApp(firebaseConfig);
export const db = getFirestore(app);
```

### `pages/blog/[slug].js` (Next.js Pages Router)
```javascript
import { doc, getDoc } from 'firebase/firestore';
import { db } from '@/lib/firebase';

export async function getServerSideProps({ params }) {
  const docRef  = doc(db, 'blogs', params.slug);
  const docSnap = await getDoc(docRef);

  if (!docSnap.exists()) {
    return { notFound: true };
  }

  return {
    props: { blog: docSnap.data() }
  };
}

export default function BlogPage({ blog }) {
  return (
    <article>
      <h1>{blog.title}</h1>
      <div dangerouslySetInnerHTML={{ __html: blog.content_html }} />
    </article>
  );
}
```

### `app/blog/[slug]/page.js` (Next.js App Router)
```javascript
import { doc, getDoc } from 'firebase/firestore';
import { db } from '@/lib/firebase';

export default async function BlogPage({ params }) {
  const docRef  = doc(db, 'blogs', params.slug);
  const docSnap = await getDoc(docRef);

  if (!docSnap.exists()) notFound();

  const blog = docSnap.data();
  return (
    <article>
      <h1>{blog.title}</h1>
      <div dangerouslySetInnerHTML={{ __html: blog.content_html }} />
    </article>
  );
}
```

---

## main.py Me Integration (Jab Ready Ho)

### Option A: Single Keyword Test
```python
from pipeline import run_pipeline_for_keyword

@app.post("/api/pipeline/run-one")
async def api_run_one(keyword: str, niche: str = "home", account: str = "acc1"):
    result = await run_pipeline_for_keyword(keyword=keyword, niche=niche, account=account)
    return result
```

### Option B: Full Day Run
```python
from pipeline import run_full_pipeline

@app.post("/api/pipeline/run-today")
async def api_run_today(account: str = "acc1", max_pins: int = 15):
    results = await run_full_pipeline(account=account, max_pins=max_pins)
    return {"total": len(results), "results": results}
```

### Option C: APScheduler me Add Karo (Auto Daily)
```python
# main.py ke scheduler setup me add karo:
scheduler.add_job(
    lambda: asyncio.create_task(run_full_pipeline(account="acc1")),
    trigger  = "cron",
    hour     = 8,        # Roz subah 8 baje IST
    minute   = 0,
    timezone = "Asia/Kolkata",
    id       = "pipeline_acc1",
)
scheduler.add_job(
    lambda: asyncio.create_task(run_full_pipeline(account="acc2")),
    trigger  = "cron",
    hour     = 8,
    minute   = 30,
    timezone = "Asia/Kolkata",
    id       = "pipeline_acc2",
)
```

---

## Weekly Keywords Update Kaise Karo

### Option A: Code me Update Karo
`pipeline/keyword_agent.py` open karo → `WEEKLY_KEYWORDS` list update karo → app restart karo.

### Option B: Google Sheet se Auto-Load (Recommended)
1. Spreadsheet me `Weekly_Keywords` naam ka tab banao
2. Columns: `keyword | niche | account | priority | days`
3. `keyword_agent.py` me `_try_load_from_sheet()` already ready hai
4. Bas `get_todays_keywords()` me ek line change karo:

```python
# keyword_agent.py ke andar:
def get_weekly_plan() -> List[WeeklyKeyword]:
    from_sheet = _try_load_from_sheet()
    return from_sheet if from_sheet else [
        WeeklyKeyword(**kw) for kw in WEEKLY_KEYWORDS
    ]
```

---

## Pipeline Files Ka Map

```
pipeline/
├── __init__.py           → All public imports/exports
├── keyword_agent.py      → Weekly keywords + daily slot planning (FILL WEEKLY_KEYWORDS dict)
├── pin_content_agent.py  → Keyword → Title + Description + Hashtags (Gemini → Groq)
├── prompt_selector.py    → Keyword → Best T2I prompt from Prompts_Master
├── product_extractor.py  → Image → Physical products list (Gemini Vision → Groq Vision)
├── amazon_fetcher.py     → Products → Amazon search + verify + affiliate link
├── blog_agent.py         → Image + Products → SEO Blog HTML (Gemini → Groq)
├── firebase_publisher.py → Blog → Firebase Firestore → Slug
├── pinterest_publisher.py→ Image + Content + Slug → Pinterest Pin
└── orchestrator.py       → Full chain: all steps in order

tools/ (existing, untouched)
├── visions_ai.py         → Vision FEEDER (aesthetic DNA extractor) — DO NOT TOUCH
├── image_creator.py      → T2I image generation pipeline
├── admitad.py            → Amazon affiliate link converter
├── aliexpress.py         → Amazon RapidAPI search (base)
├── make_webhook.py       → Pinterest posting via Make.com
├── llm.py                → Groq + Cerebras LLM wrapper
└── groq_ai.py            → Pin copy generation (existing product flow)
```

---

## Rate Limiting Summary

| Step | API | Rate Limit Handling |
|------|-----|---------------------|
| Pin Content | Gemini / Groq | 429 → 30s sleep → retry (3x) → next model |
| Product Extractor | Gemini Vision / Groq Vision | 429 → 30s sleep → retry (3x) → next model |
| Amazon Search | RapidAPI | 2s delay between calls, 429 → 30s sleep |
| Blog Agent | Gemini / Groq | 429 → 30s sleep → retry (3x) → next model |
| Pinterest | Make Webhook | Timeout 30s, error logged |
| Firebase | Firestore | No rate limit (generous free tier) |

---

## Testing Individual Steps

```bash
# Orchestrator test (single keyword)
python pipeline/orchestrator.py

# Individual step tests:
python -c "from pipeline.keyword_agent import get_todays_keywords; print(get_todays_keywords())"
python -c "from pipeline.pin_content_agent import generate_pin_content; import json; print(json.dumps(generate_pin_content('aesthetic bedroom 2025', 'home'), indent=2))"
python -c "from pipeline.prompt_selector import select_best_prompt; print(select_best_prompt('aesthetic bedroom 2025', 'home'))"
```

---

## Common Issues

| Problem | Solution |
|---------|----------|
| `FIREBASE_CREDS_JSON not set` | Replit Secrets me add karo |
| `firebase-admin not installed` | `pip install firebase-admin` run karo |
| `RAPIDAPI_KEY not set` | rapidapi.com se key lo, Replit Secrets me add karo |
| `BLOG_BASE_URL not set` | Pinterest pin ka link `/blog/slug` ho jayega (relative URL) |
| Gemini 429 too often | Dono GEMINI keys set karo — pipeline automatically switch karega |
| Blog HTML me products nahi | Amazon fetch fail ho raha hai — RAPIDAPI_KEY check karo |
