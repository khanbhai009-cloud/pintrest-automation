# System.md (The Brain)

## Detailed High-level Architecture

Bhai, yeh Pinteresto ka core system hai – ek robust, agentic workflow jo mobile-first hai. Architecture ko modular banaya hai taaki scaling easy ho jaye. Main components:

- **Frontend**: Simple web app (HTML/CSS/JS) for user dashboard, running on mobile browsers.
- **Backend**: Python-based LangGraph agents on Hugging Face Spaces, handling all logic.
- **Database**: External DB (Supabase/Firebase) for user data, affiliate CSVs, and post schedules.
- **APIs**: Pinterest API for posting, Flux 1 API for image gen, affiliate parsers for CSV cleaning.
- **Queue System**: Celery/Redis for background tasks, taaki heavy loads handle ho sake.

Architecture diagram (imagine a flowchart):
```
User (Mobile) -> Web Dashboard -> Hugging Face Space (Agents) -> APIs -> Database
```

## Multi-agent Coordination (Research Agent, Content Gen Agent, Scheduler Agent)

Agents ka coordination LangGraph se hota hai – state machines jaisi flow. Har agent ka role clear:

- **Research Agent**: Tavily search se trending Pinterest topics find karta hai. User ke niche ke liye relevant content research.
- **Content Gen Agent**: Groq AI se captions generate karta hai, Flux 1 se images banata hai. Aesthetic vibes ensure karta hai.
- **Scheduler Agent**: Posts ko queue mein daalta hai, Pinterest API se post karta hai at optimal times.

Coordination: Agents serially ya parallel run karte hain based on state. E.g., Research -> Content Gen -> Scheduler.

## Tech Stack (Mobile-first Development Context)

Mobile pe develop kar rahe ho (Termux), toh stack lightweight hai:

- **Language**: Python (asyncio for non-blocking).
- **Framework**: LangGraph for agents, FastAPI for APIs.
- **Deployment**: Hugging Face Spaces (Docker containers).
- **Mobile Tools**: Termux for coding, Git for version control.
- **Libraries**: Requests for APIs, Pandas for CSV, Pillow for images.

Checklist for setup:
- [ ] Python 3.9+ install karo Termux mein.
- [ ] Virtual env banao.
- [ ] Requirements.txt se dependencies install karo.

## API Integrations (Pinterest API, Flux API, CSV Parsers)

APIs ko securely integrate kiya hai:

- **Pinterest API**: OAuth2 for auth, pins create karne ke liye. Rate limits: 1000 requests/hour.
- **Flux 1 API**: Hugging Face se image gen. Models: flux-dev for fast gen.
- **CSV Parsers**: AI (Groq) se raw affiliate CSVs clean karo – duplicates remove, categories add.

Integration steps:
1. API keys env vars mein store karo.
2. Error handling add karo for rate limits.

## Data Flow from User Login -> Image Gen -> Posting

End-to-end flow:

1. **User Login**: OAuth2 se Pinterest connect, JWT token generate.
2. **Input Upload**: Affiliate CSV upload, niche select.
. **Research**: Agent trending topics find karta hai.
4. **Content Gen**: Images generate, captions AI se banao.
5. **Schedule**: Posts queue mein daalo, optimal time pe post karo.
6. **Posting**: Pinterest API se pins create, success notify.

Data flow table:

| Step | Component | Data |
|------|-----------|------|
| 1 | Frontend | User creds |
| 2 | Backend | CSV file |
| 3 | Research Agent | Topics list |
| 4 | Content Gen Agent | Images + Captions |
| 5 | Scheduler Agent | Post queue |
| 6 | Pinterest API | Pins created |

Edge cases: If Flux down, fallback images use karo. Rate limits pe exponential backoff.