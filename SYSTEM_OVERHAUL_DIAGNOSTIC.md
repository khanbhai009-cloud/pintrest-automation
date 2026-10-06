# SYSTEM OVERHAUL DIAGNOSTIC

Static repository audit. No application code was changed and no provider was called as part of this audit. Token counts below are estimates from prompt text and configured output limits, not provider-reported usage.

## 1. Active Runtime and End-to-End Execution Path

### Runtime verdict

There is no working, always-on application entry point in the checked-in project state.

- The configured Replit workflow runs `python -m uvicorn main:app --host 0.0.0.0 --port 5000 --reload` (`.replit:29-32`). The latest observed workflow log stops with `No module named uvicorn`.
- Installing the listed `uvicorn` dependency would expose the next blocker: `main.py` does not define a FastAPI `app`, route handlers, or ASGI lifespan. It defines `run_engine()` and calls it only under `__main__` (`main.py:14-51`). `uvicorn main:app` therefore has no application object to import.
- The Replit deployment command has the same structural problem: it asks Gunicorn/Uvicorn to serve `main:app` (`.replit:38-40`).
- The `Dockerfile` runs `python main.py`, exposes port 7860, and does not start an HTTP server (`Dockerfile:14-20`). That command runs a single engine cycle and exits; it is not a persistent service.
- `static/index.html` is a large dashboard that calls endpoints such as `/api/stats`, `/api/next-pins`, `/api/chat`, `/api/vision/start`, and `/api/boards/save`. There is no corresponding FastAPI application or route implementation in the Python source. The dashboard is therefore not backed by the configured runtime.

The immediate observed startup failure is missing `uvicorn`; the deeper deterministic defect is that the configured ASGI target does not exist. The source audit did not launch the application or make API requests.

### Intended one-shot Pinterest path

The code's intended current production path is `run_once.py`, not `main.py`:

```text
.github/workflows/pin_scheduler.yml
  └─ python run_once.py
       └─ run_mastermind(trigger="scheduled")
            └─ LangGraph: firebase_loader
                 → data_intelligence
                 → cmo_mastermind
                 → board_selector
                 → agent_executor
                      └─ run_agent(trigger="account1" or "account2")
                           └─ ChatGroq tool loop
                                └─ publish_next_pin
                                     ├─ generate image
                                     ├─ optionally run inline blog/product pipeline
                                     └─ post Pinterest pin through Make.com
```

Evidence: `run_once.py:12-21`, `mastermind/graph.py:99-116,121-168`, `agent.py:249-362,485-559`.

Each `run_once.py` invocation supplies the generic trigger `"scheduled"`. `node_cmo_mastermind` interprets a generic trigger by reading and flipping `next_turn` in `Style_Tracker`, then creates a strategy for only the selected account (`mastermind/node_cmo.py:1297-1306,1312-1419`). It does not normally run both accounts in one cycle. The CMO and board-selector nodes still load/read data for both accounts before the executor skips the unselected one.

The CMO uses a rotating style from `Prompts_Master` (hardcoded style order is a fallback), chooses one account, and calls Gemini once, then Cerebras if Gemini fails. Its output includes a generated visual prompt, title, description, tags, and related fields. The board-selector node then calls the independent board selector for the selected account. The agent's system prompt injects the CMO's entire `visual_prompt` as text (`agent.py:387-418`), and `publish_next_pin` also passes that prompt to image generation (`agent.py:274-299`). The prompt is therefore **not** confined to Python/image-generation code; it is sent back to the execution LLM as part of its system message.

The actual image-provider chain is Cloudflare → Hugging Face → Pollinations in `tools/image_creator.py`. Older comments in `agent.py` describe OpenRouter → Pollinations and are stale. The CMO's visual prompt flows through Python, into the agent LLM context, and into the image generator; it is not itself a separate LLM response passed back to the CMO.

### Automation that is and is not scheduled

- `.github/workflows/pin_scheduler.yml` has its `on:` key, hourly `schedule`, and `workflow_dispatch` all commented out. Its job body would call `python run_once.py`, but no trigger is currently declared. As written, it does not schedule pins.
- `.github/workflows/manual_full_flow.yml` has a `workflow_dispatch` trigger, but its job invokes `python run_full_flow.py <account>`. No `run_full_flow.py` exists in the repository. That manual job cannot reach the described pipeline.
- `.github/workflows/vision_feeder.yml` has its `on:` key commented out and `workflow_dispatch` sitting outside any `on:` mapping. It does not declare a valid GitHub Actions trigger. Its body would call `vision_run_once.py`.
- `vision_run_once.py` calls `run_feeder_agent()` once. `tools/visions_ai.py` contains a `while True` loop only in its own `if __name__ == "__main__"` block; that loop repeatedly scans Drive and sleeps five minutes when idle. The one-shot entry point does not enter that loop.
- There is no APScheduler instance, scheduler registration, `mastermind_scheduled_job`, background task, or FastAPI lifespan in the Python source. `APScheduler` appears in dependencies and old documentation, not in the active runtime.
- `main.py` defaults `ACCOUNT_CHOICE` to `"both"` and maps it to `"manual-both"`, but the CMO treats that as a generic trigger and selects one account via `next_turn`; the log message saying both accounts will run is not accurate for the current graph.

## 2. LangGraph, Tool Registry, and Conditional Blog/Product Paths

### Two graphs, only one in the current entry path

The active top-level graph is the five-node LangGraph in `mastermind/graph.py`: local board loader → analytics loader → CMO → board selector → agent executor. Its module header calls it a three-node graph and `build_mastermind_graph()` calls it a four-node pipeline, both inconsistent with the five nodes actually registered.

The second graph is in `agent.py`: an LLM node routes tool calls to a `ToolNode`, then loops back to the LLM until the model stops requesting tools (`agent.py:467-492`). It is used by the active executor, but it is unnecessary as an orchestration layer for a deterministic “generate one image, then post one pin” operation. The explicit system protocol says to call `publish_next_pin` and stop (`agent.py:446-460`).

The tool registry is exactly:

```python
ALL_TOOLS = [fill_missing_niches, publish_next_pin]
```

(`agent.py:360-362`)

`analyze_niche_stock` and `fetch_aliexpress_products` are defined but unregistered. They cannot be called by this graph. `tools/groq_ai.filter_product`, `tools/groq_ai.generate_pin_copy`, and the product-fetch path those functions support are consequently not part of the active pin cycle. The same applies to the imported `tools.tavily_search.get_trending_keyword`: it is not registered or called from the current graph.

`fill_missing_niches` **is** registered. Its tool description says to run it at the beginning of every cycle, while the higher-level system prompt says the only required action is `publish_next_pin` and then end. This is contradictory, so whether the model calls it is nondeterministic. If called, it scans every sheet product with a blank niche and makes one Groq chat request per such product, sequentially, with a 2.5-second sleep after each (`agent.py:84-118`, `tools/llm.py:16-54`). There is no batch-size limit.

The active agent's global variables (`CURRENT_TRIGGER`, `CURRENT_CMO_STRATEGY`, and `LAST_POSTED_IMAGE_URL`) are set before graph execution (`agent.py:59-66,514-517`). They are acceptable only while calls are strictly serialized within a process. Concurrent requests in a future web server could overwrite each other's account/strategy context.

### CMO analytics and duplicate board decision

`node_data_intelligence` reads both accounts' last-seven-day analytics from Google Sheets (`mastermind/node_data.py:24-79`). Those rows are passed as the `metrics` parameter to `_call_cmo_for_account`, but that parameter is never read in the function body. The CMO prompt is built from the selected style row, account profile, board text, and trends—not the analytics rows. The product has analytics reads and state fields but no analytics-driven CMO decision.

`node_firebase_loader` does not load Firebase boards or trends; it loads `data/boards_config.json` and returns empty trend maps (`mastermind/node_firebase.py:13-62`). The active CMO still includes the resulting local board list in its prompt and asks the model to select a board (`mastermind/node_cmo.py:910-939,1203-1215`). The following `node_board_selector` makes a second, independent selection (`mastermind/node_board_selector.py:73-105`). It writes `board_id` and `board_name`, which `publish_next_pin` reads. The CMO's separate `selected_board_id` field is logged but not used as the routed board. This is duplicate prompt/call work and duplicate decision logic.

`tools.firebase_boards.get_boards()` and `get_all_active_trends()` exist but are not called by the active Firebase loader. Only its prompt formatters are used by the CMO.

### Blog/product branch: conditional, real, and before Pinterest posting

The blog branch is not a standalone graph node in the active `mastermind/graph.py`. It is called inline by `publish_next_pin` after image upload and **before** Pinterest posting:

```text
publish_next_pin
  └─ if BLOG_ENABLED is not "false" (default true)
       └─ _run_inline_blog
            └─ requires FIREBASE_CREDS_JSON
                 └─ node_blog_trigger
                 └─ node_product_researcher
                 └─ node_blog_writer
                 └─ node_firebase_publisher
  └─ post Pinterest pin (with blog URL if available)
```

Evidence: `agent.py:192-246,297-353`. The inline branch returns immediately when `FIREBASE_CREDS_JSON` is absent. If it is present, `BLOG_ENABLED` defaults to true; set it to `"false"` to skip the branch. The blog trigger enforces a per-account daily counter, but the inline state does not pass `force_blog`, so `run_mastermind(force_blog=True)` does not bypass that counter.

Several important consequences:

- The blog trigger's `last_posted_image_url` check receives the generated ImgBB URL before the Pinterest call has happened. Its variable name and log imply that the pin is already posted when it is not (`agent.py:213-230`, `mastermind/node_blog_trigger.py:43-61`).
- The daily blog counter is incremented before product research, blog writing, Firebase publication, and Pinterest posting. A later failure can consume the daily slot without publishing a blog.
- Blog publication is attempted before the Pinterest post because the pin needs the blog URL. The code catches blog exceptions and continues to pin without a URL, but can leave a published blog with no successful Pinterest post.
- The CMO brief says “no products/no affiliate links,” yet the default-enabled blog branch researches products and inserts affiliate links. These are separate policy paths with contradictory descriptions.
- `MAX_BLOG_PRODUCTS = 4` caps only the entries eventually returned to the blog. It does **not** cap the number of products normalized, image galleries examined, or vision-model calls before that point.

`node_product_researcher` is therefore conditional but live. When blog publishing is enabled and Firebase credentials are configured, it can call Gemini vision, Groq vision, a Groq quality filter, RapidAPI, and Groq image selection. It is not accurate to classify all product and blog modules as dead.

## 3. LLM Invocation Ledger and Token/TPM Estimates

### Method and interpretation

Character-based estimates use approximately four English characters per token. This is a sizing heuristic, not a tokenizer result. Dynamic Google Sheets rows, exact provider tokenization, image dimensions/patching, tool-schema serialization, actual model completions, and retries can change the results. Output `max_tokens` values below are ceilings, not predictions of actual usage.

The repository does not record or aggregate provider-reported `usage.prompt_tokens` / `usage.completion_tokens`, does not enforce a shared per-minute Groq budget, and does not preserve provider quota headers. There is no evidence here to identify an exact request or minute that crossed 8,000 TPM. In the checked environment, the Replit workflow currently fails before the app starts, and the GitHub scheduler workflow has no trigger. Any claim that one particular CMO prompt is the proven cause would be unsupported.

### Calls reachable from the intended pin path

| Call/site | Provider and trigger | Estimated input / output | Frequency and TPM significance |
|---|---|---|---|
| CMO strategy, `mastermind/node_cmo.py:_call_gemini_sync` | Gemini 2.5 Flash primary; one selected account per generic run | The fixed prompt body is 2,473 chars (~620 tokens), plus a 1,064-char Gemini system instruction (~266 tokens). Account profile, one style row, tags, boards, and trends add roughly 600–1,500 tokens. Budget about **1,500–2,400 input tokens**; output ceiling **6,000**, with a typical short JSON result likely hundreds of tokens. | One primary call. This is **not Groq TPM**. |
| CMO fallback, `_call_cerebras_sync` | Cerebras after Gemini exception or invalid response | Same user prompt plus a 1,483-char system prompt (~371 tokens): roughly **1,800–2,800 input tokens**; output ceiling **6,000**. | At most one fallback call per selected account. Not Groq TPM. |
| Board selection, `tools/board_selector.py:_call_llm` | Groq primary; Cerebras fallback; one active account has 5 local boards, the other 3 | Prompt template is 542 chars (~136 tokens). Current formatted board text is 1,583 chars (~396 tokens) for account 1 and 328 chars (~82 tokens) for account 2, plus keywords and description. About **350–800 input tokens**, output cap **50**. | Normally one Groq request per cycle because each account has multiple boards. It duplicates the board choice already requested from the CMO. |
| Agent LLM, `agent.py:agent_node` | `ChatGroq` primary, `ChatOpenAI` against Cerebras fallback | Static system prompt is 1,789 chars (~447 tokens); CMO brief includes title/copy and the full generated `visual_prompt`. Allow roughly **900–1,600 input tokens per turn**, including a modest allowance for two bound-tool schemas; exact schema overhead is SDK-dependent. | Usually one request to produce the `publish_next_pin` tool call and another after the tool result to produce the final report: roughly **1,800–3,200 Groq input tokens** for two turns, before any extra tool loop or fallback. Each turn resends the system prompt and prior messages. |
| Niche fill, `agent.py:fill_missing_niches` → `tools/llm.py:chat` | Groq, Cerebras on error | Approximately **35–70 input tokens per product** and a 1–3 token niche answer. | One separate request per blank-niche product, with no count cap. Model invocation is optional/nondeterministic because tool instructions conflict. |
| Product identification, `mastermind/node_product_researcher.py:_identify_products_with_fallback` | Gemini key 1 → Gemini key 2 → Groq Llama 4 Scout → Cerebras text, sequential | Text prompt is 956 chars (~239 tokens); image is also supplied to the first three model attempts. Text fallback is a few hundred tokens. Image token use is provider/model/image-resolution dependent and cannot be determined from source. Configured output ceilings: 4,096 / 1,200 / 1,000 tokens respectively. | Conditional on inline blog. It stops at the first non-empty parsed result; fallback attempts have 10-second waits. Groq sees the image only if both Gemini attempts fail. |
| Product quality filter, `_llm_quality_filter` | Groq `llama-3.3-70b-versatile` | Static prompt is 1,148 chars (~287 tokens). Up to 20 slim product records (titles capped at 80 chars) make a likely total of **about 1,100–1,500 input tokens**. Output cap **1,500** per request. | One call per identified keyword; max 5 by code, although the vision prompt asks for exactly 3. Several calls can occur in one cycle. |
| Product image picker, `tools/aliexpress.py:get_best_lifestyle_image` | Groq vision, then GitHub inference fallback | Text instruction is tiny, but each request contains **2–5 image URLs as vision inputs**. Source does not resize or normalize these images, so token use is unknown and may dominate the text estimate. | One call for every normalized approved product whose RapidAPI gallery has more than one image. Up to 20 raw results per keyword and 5 keywords are allowed by constants; the four-blog-product cap happens after normalization. This is the highest-volume conditional Groq path. |
| Blog writer, `mastermind/node_blog_writer.py:_write_blog_with_fallback` | Gemini key 1 → Gemini key 2 → Groq → Cerebras, sequential | Fixed prompt/schema is 1,994 chars (~498 tokens), plus visual prompt and up to 4 product summaries. Roughly **700–1,200 input tokens**. Required output is 9 paragraphs of 120–150 words plus 3 FAQs, likely **about 1,600–2,400 output tokens**; cap is 3,000. | Groq is reached only after both Gemini calls fail or return invalid content. No retry on the same provider. |

The CMO prompt does **not** contain the entire `VISUAL_STYLES` dictionary. That dictionary contains 25,865 characters of string values (~6,466 tokens if naïvely concatenated), but it is only an emergency/local lookup. The active CMO path sends one selected style row (`label`, `description`, `t2i_base`, tags/niche) and the board text. The selected style row comes from Google Sheets, so its exact size is external and unknown.

The visual prompt is nevertheless sent to the execution LLM. It is inserted into the CMO brief at `agent.py:406-418`, included in every execution message history, and separately supplied to `generate_pin_image` at `agent.py:274-299`. A prompt around 1,000 tokens adds approximately that amount to **each** agent request that resends the system message; it does not remain pure Python.

### Other codebase LLM callers: condition and status

| Caller | Status relative to `run_once.py` | Approximate usage if invoked |
|---|---|---|
| `tools/visions_ai.py` Gemini image analysis | Separate Vision Feeder. `vision_run_once.py` calls one feeder scan; GitHub workflow has no valid trigger. Direct `python tools/visions_ai.py` enters a `while True` scan/sleep loop. | One Gemini multimodal request per processed Drive image. Image tokens are unknown; text prompt is a few hundred tokens. Not Groq TPM. |
| `mastermind/node_copy.py` Groq → Cerebras copywriter | Dormant: not imported or called by `mastermind/graph.py`; `a1_final_seo_copy` / `a2_final_seo_copy` remain empty. | One prompt per account, about 400–700 input tokens plus short JSON output; fallback only after failure. |
| `tools/groq_ai.py:filter_product` through `fetch_aliexpress_products` | Dormant: that fetch function is not registered in `ALL_TOOLS`. | `filter_product` can call `tools.llm.chat` once per fetched candidate (up to 20), with a product JSON prompt; it can create many Groq requests if the old path is re-enabled. |
| `tools/groq_ai.py:generate_pin_copy` | No call site found. | Roughly 700–1,000 input tokens per invocation, but currently zero calls from the graph. |
| `tools/tavily_search.py:get_trending_keyword` | Not registered or called by the current graph. | One `tools.llm.chat` call after Tavily; prompt size depends on search result text. |
| `pipeline/pin_content_agent.py` | Dormant pipeline; not imported by `run_once.py` or `mastermind/graph.py`. | 995-char template (~249 tokens), Gemini primary/fallback then up to 3 Groq attempts. Small request unless repeated retries. |
| `pipeline/product_extractor.py` | Dormant pipeline. | Gemini primary/fallback then Groq vision; 1,080-char text prompt (~270 tokens) plus one image. Up to 3 retries per model. |
| `pipeline/amazon_fetcher.py:_verify_similarity` | Dormant pipeline. | One Groq request per candidate passing rating/review/ASIN checks, max 5 results per extracted product and 8 products per image (up to 40 calls). Prompt is roughly 60–100 tokens; output cap 5. |
| `pipeline/blog_agent.py` | Dormant pipeline. | 2,303-char prompt body (~576 tokens), dynamic product data, and a 4,096 output ceiling; likely around 800–1,300 input plus 1,500–2,500 output tokens when Groq fallback is reached. |
| `pipeline/prompt_selector.py` | Dormant pipeline; its documentation says LLM fallback, but implementation uses deterministic string scoring/random choice and makes no LLM request. | Zero. |

### 8,000 TPM assessment

The likely cause is **aggregate request volume**, not a single 8,000-token CMO prompt:

1. The CMO is Gemini/Cerebras, not Groq.
2. The board selector contributes one relatively small Groq request.
3. The execution agent resends its CMO system brief—including the long visual prompt—on multiple Groq turns.
4. If `fill_missing_niches` is selected, it adds one Groq request for each blank sheet product.
5. If inline blog is enabled and configured, the product quality filter makes multiple Groq requests, and the image picker can add one multimodal Groq call per approved product/gallery. Those images' token cost is not measurable from source.
6. If both Gemini blog-writer attempts fail, Groq receives the long blog prompt and generates a long article. The separate image-identification fallback can also send the pin image to Groq if both Gemini attempts fail.

The product/image branch is the strongest source-level risk because its work is scaled by product count before the four-item blog cap. It can plausibly push a shared Groq key over 8,000 tokens in a minute when image selection and other Groq fallbacks cluster together. The repository does not prove that it did so: actual throughput depends on runtime secrets, Firebase configuration, provider success/failure timing, provider image-token accounting, the number of approved products, and any concurrent process sharing the key. No provider usage telemetry was present to confirm the event.

## 4. Dead Paths, Background Loops, and Operational Overhead

### Dormant or conflicting execution systems

- `pipeline/orchestrator.py` is a complete second publishing pipeline (keyword list → pin copy → prompt → image → product extraction → Amazon lookup → blog → Firebase → Pinterest). No current root entry point imports or invokes it. `pipeline/__init__.py` eagerly imports its modules only if the `pipeline` package is imported.
- `mastermind/node_copy.py` and `mastermind/node_execute.py` are legacy graph nodes. Neither is registered in the active graph. `node_execute.py` bypasses the active agent and calls image generation/posting directly.
- `mastermind/node_blog_trigger.py`, `node_product_researcher.py`, `node_blog_writer.py`, and `node_firebase_publisher.py` are not nodes in the top-level graph, but are reached through the conditional inline blog branch described above.
- `tools/aliexpress.search_products()` can use RapidAPI/Apify, but the active inline product-research route calls `fetch_rapidapi()` directly. Its Apify fallback and the registered-agent `fetch_aliexpress_products` route are not used. The module name says AliExpress, while its RapidAPI endpoint and product normalization are Amazon-oriented.
- `tools/firebase_boards.get_boards()` / `get_all_active_trends()` are not called by the active loader; local JSON is the actual board source.
- `utils/image_processor.py` has no Python call site in the repository.
- `tools/digistore.py` imports `ALLOWED_CATEGORIES` and `BLOCKED_CATEGORIES` from `config.py`, but those names are not defined there. It is currently unreferenced and would fail at import.
- The static dashboard is not simply missing a process manager; its expected HTTP API is absent.

There are contradictory descriptions in source and documentation: the active image chain, style names, scheduler, “both accounts” behavior, product policy, graph node count, and blog order are described differently in comments, migration documents, and actual code. Use executable source and workflow configuration as the runtime truth.

### Background work and blocking overhead

There is no background loop in the configured Pinterest workflow. The only explicit infinite loop is in `tools/visions_ai.py` when that module itself is run as a script. `run_once.py` does one graph invocation and exits.

Per intended pin cycle, non-LLM overhead includes:

- Both analytics tabs are fetched even though only one account is selected and the resulting metrics do not affect the CMO prompt.
- `Prompts_Master`, `Style_Tracker`, and `Prompt_Tracker` calls are made to choose/rotate styles. Their TTL caches are in-process; GitHub Actions starts a fresh runner for each run, so these caches do not persist between scheduled runs.
- Style rotation uses read-modify-write on a sheet with no cross-process lock or atomic compare-and-swap. Concurrent workflow dispatches can read the same `next_turn` and select the same account.
- `sheets/base.py` enforces synchronous sleep-based read/write gaps. Some Sheets writes also call `get_all_records()` within the write closure. This is quota protection but adds serial latency.
- Product research can perform RapidAPI calls, product-gallery fetches, one-second sleeps per normalized product, half-second sleeps between normalized products, and two-second sleeps between search keywords.
- Vision and blog fallback chains wait 10 seconds between models. Some older pipeline callers wait 30 seconds after 429 and retry up to three times.
- `fill_missing_niches` uses synchronous `time.sleep(2.5)` inside a tool path and calls its LLM serially for every missing product.

These waits reduce burstiness in some code paths but do not constitute a Groq-wide TPM limiter. They are scattered by feature, do not count provider-reported input plus output tokens, and do not coordinate simultaneous workers.

### Reliability and observability gaps

- `node_agent_executor` marks a publish successful whenever `run_agent()` returns status `"ok"`. `run_agent()` returns `"ok"` if the LangGraph finishes, even if `publish_next_pin` returned `{"success": False}` or the model never called the tool. The outer graph can report a false-positive publish result (`mastermind/graph.py:59-94`, `agent.py:547-559`).
- The top-level result hardcodes `"blog_published": False` and an empty blog URL even though inline blog publishing occurs inside the agent (`mastermind/graph.py:193-203`). The summary can therefore disagree with side effects.
- The test suite contains only the two account-turn rotation tests (`tests/test_turn_logic.py`). There are no tests for startup/importability, workflow triggers, tool-call execution, pin result propagation, blog gating, product call caps, or token accounting.
- A source-wide Python AST parse found no syntax errors. This is not evidence that imports, provider APIs, workflows, or external integrations work.

## 5. Minimal Refactor Blueprint

Do this in small, observable stages. The first goal is one real execution contract; do not combine the old pipeline and Mastermind graph.

1. **Choose the runtime contract.** If the dashboard is still required, implement and test the actual FastAPI app/routes and lifespan, and make `.replit`/deployment target that app. If this project is meant to be a headless scheduled worker, stop trying to serve `main:app`; configure the Replit run/deployment command to execute the one-shot entry point and remove or separately host the dashboard. Do not keep an ASGI command pointed at a CLI file.
2. **Make automation executable.** Restore a declared `on.schedule` and/or `workflow_dispatch` for the pin workflow; repair the Vision Feeder trigger; replace the nonexistent `run_full_flow.py` invocation with the intended entry point or remove that stale workflow. Add a smoke test that validates the workflow entry path and exact account-selection behavior.
3. **Collapse orchestration to one graph.** Keep `mastermind.graph` as the single owner of the pin cycle. Either explicitly integrate the separate `pipeline/` stages behind a deliberate feature boundary or remove/retire that second pipeline after confirming nothing external invokes it. Do not run two independent pin publishers.
4. **Remove the LLM tool loop for deterministic publishing.** Have the graph call the image/publish operation directly with the already-built CMO strategy, or retain an LLM only where its decision is required. Do not spend two or more agent turns asking a model to call one predetermined tool and summarize the result. Propagate the tool's actual `success` field to the top-level status.
5. **Make board selection happen once.** Either use a validated board selected by the CMO or use the standalone board selector; remove the unused duplicate choice from the other stage. Load actual analytics into a compact structured prompt if analytics should influence the strategy, otherwise remove the misleading analytics/CMO dependency.
6. **Bound the conditional product branch before fan-out.** Apply a small explicit candidate cap immediately after RapidAPI results and before gallery downloads/image selection. Prefer deterministic image scoring or one batched image-selection request over a Groq vision call for each approved product. Batch or rule-score product quality where possible. Keep a hard per-cycle request and token budget independent of the blog display cap.
7. **Instrument and enforce provider budgets centrally.** Record provider, model, feature/cycle ID, request count, `usage.prompt_tokens`, `usage.completion_tokens`, latency, retry/fallback, and provider rate-limit headers when available. Add a shared per-key limiter with a safety margin beneath the configured TPM, including concurrent executions. Do not log credentials or full sensitive payloads. Revisit the 8,000 TPM diagnosis only after these measurements exist.
8. **Make side effects explicit and testable.** Model a cycle with separate image-ready, blog-draft/published, pin-posted, and failed states. Make blog-counter consumption and retry/idempotency rules explicit; do not report a successful pin merely because the agent graph returned normally.
9. **Add narrow regression tests before broader cleanup.** Cover CLI/server startup contract, scheduled account rotation under concurrent runs, one board-selection call, actual pin failure propagation, blog disabled/missing-Firebase/daily-limit cases, candidate/image-call caps, and token-budget behavior. Preserve the existing turn-rotation tests.

No code changes were made for these recommendations. The current highest-priority blockers are the nonexistent ASGI app target, the disabled/broken automation triggers, and the unbounded conditional Groq vision fan-out. The exact historical 8,000 TPM breach remains unverified until provider usage data is available.
