# Pinteresto GitHub Actions Migration Guide (Hinglish)

Is project ab old setup se move ho kar GitHub Actions based cron system me ja rahi hai. Old code server-based tha, jisme FastAPI + APScheduler 24/7 chal raha tha. Ab hum usko short-lived runner model me convert kar rahe hain.

Ab har run ek hi pin ka cycle hoga. GitHub Actions ek fresh Ubuntu runner kholta hai, code chalta hai, kaam complete hota hai, aur process khatam ho jata hai.

---

## 1) Problem kya tha old setup me?

Old code me:
- FastAPI server khulta tha
- APScheduler background job 24/7 chalta tha
- dono accounts ek hi cycle me run ho sakte the
- server persistent rehta tha, isliye hosting/DNS issue hota tha
- GitHub Actions me direct run karne ke liye script ko one-shot mode me banana padta hai

Ab yeh architecture change ho gaya hai:
- no persistent server
- no dashboard dependency
- each cron trigger = one execution
- each execution = one pin post cycle

---

## 2) Naya flow kya hai?

### A) `run_once.py`

Ye root file hai. Iska kaam simple hai:

```python
async def main():
    result = await run_mastermind(trigger="scheduled")
    print(result.get("summary", result))
```

Matlab har GitHub Action run ke sath `run_mastermind()` call hota hai. `run_mastermind()` graph ka main flow chalta hai.

### B) `mastermind/node_cmo.py`

Yahan decision liya jata hai ki is run me account_1 post karega ya account_2.

Old logic me generic trigger (jaise manual/scheduled) ke sath dono accounts run ho jaate the.

Ab logic hai:
- agar trigger me explicit "account1" ya "account2" hai, to us account ko run karna
- nahi to `next_turn` column se auto-pick karo

### C) `next_turn` column

`Style_Tracker` sheet me ab 3rd column add hoti hai:

- account_1
- account_2
- next_turn

Example:

```text
account_1 | account_2 | next_turn
0         | 0         | account_1
```

Har run ke sath:

```python
def _decide_turn():
    tracker = load_style_tracker()
    turn = tracker.get("next_turn", "account_1")
    tracker["next_turn"] = "account_2" if turn == "account_1" else "account_1"
    save_style_tracker(tracker)
    return turn
```

Isliye:
- pehle run => account_1
- next run => account_2
- next run => account_1

Ye get current turn ko read karta hai, phir flip karke save karta hai. Isse concurrent runs me confusion nahi hota.

---

## 3) Why this is important for GitHub Actions?

GitHub cron fixed schedule par chalta hai, jaise har ghante. Isliye humko server ke andar persistent state rely nahi karna chahiye.

Aaj ke environment me:
- runner fresh hota hai
- previous run ka memory exist nahi karta
- isliye `next_turn` ko Google Sheets ke through maintain karna zaroori hai

Yeh source of truth hai, local JSON backup sirf fallback ke liye hai.

---

## 4) `sheets/style_tracker.py` me kya change hua?

Is file me tracker ko support kiya gaya hai:
- read karna
- local JSON me save karna
- Google Sheets me save karna
- `next_turn` field ko include karna

Important part ye hai:

```python
if not records:
    sheet.append_row(["account_1", "account_2", "next_turn"])
    sheet.append_row([a1_val, a2_val, turn_val])
else:
    headers = sheet.row_values(1)
    if "next_turn" not in headers:
        sheet.update_cell(1, 3, "next_turn")
    sheet.update("A2", [[a1_val, a2_val, turn_val]])
```

Isse sheet ko auto-update hota hai agar column missing ho.

---

## 5) `mastermind/graph.py` me kya fix hua?

Graph node `node_agent_executor` ab `target_account` ko prefer karta hai.

Old logic:
- generic trigger => dono accounts run

New logic:
- `target_account` available hai => only that account run hota hai
- agar nahi mila => explicit `account1`/`account2` trigger check

Yeh critical hai, kyunki GitHub cron trigger generic hi hota hai. Isliye single-run single-post pattern maintain hota hai.

---

## 6) Workflow files ka kaam

### `.github/workflows/pin_scheduler.yml`

Yeh file cron har ghante chalati hai:

```yaml
on:
  schedule:
    - cron: '0 * * * *'
```

Har run:
```bash
python run_once.py
```

Ye ek execution me ek hi pin cycle run karta hai.

### `.github/workflows/vision_feeder.yml`

Ye vision feeder ko 2-hourly run karta hai.

---

## 7) Why not random 60-72 min gap?

GitHub cron fixed schedule support karta hai. Random gap APScheduler ke andar Python code se generate hota tha, but GitHub Actions cron me aisa native nahi hota. Isliye simple fixed hourly cadence choose kiya gaya hai.

Ye honest caveat hai:
- reliability high
- randomness lower
- load pe GitHub runner 5-15 min delay ho sakta hai

---

## 8) GitHub Secrets kya chahiye?

Repository ke GitHub Settings > Secrets and variables > Actions me yeh secrets honi chahiye:

- `GROQ_API_KEY`
- `CEREBRAS_API_KEY`
- `OPENROUTER_API_KEY`
- `IMGBB_API_KEY`
- `GOOGLE_CREDS_JSON`
- `SPREADSHEET_ID`
- `RAPIDAPI_KEY`
- `RAPIDAPI_KEY2`
- `TAVILY_API_KEY`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `GEMINI_API_KEY`
- `GEMINI_API_KEY_2`
- `FIREBASE_CREDS_JSON`
- `MAKE_WEBHOOK_URL`
- `MAKE_WEBHOOK_URL_2`

---

## 9) Actual execution flow

Ek complete cycle ka flow is tarah hota hai:

1. GitHub Actions cron trigger hota hai
2. `run_once.py` call hota hai
3. `run_mastermind()` start hota hai
4. `node_cmo_mastermind()` `next_turn` read karta hai
5. target account decide hota hai
6. board + strategy build hota hai
7. agent executor only selected account ko run karta hai
8. pin publish hota hai
9. runner exit ho jata hai

Yeh hi reason hai ki server chahiye hi nahi, because fresh runner per cron run handle karta hai.

---

## 10) Important note

`main.py` ko delete nahi kiya gaya. Sirf GitHub Actions use nahi kar raha. Agar future me manual dashboard chahiye to that file still usable hai.

---

## 11) Quick check list

Agar deploy karna ho to check karo:

- [ ] GitHub Secrets add kiye gaye hain
- [ ] `Style_Tracker` sheet me `next_turn` column hai
- [ ] `.github/workflows/pin_scheduler.yml` file commit hui hai
- [ ] `run_once.py` run kar ke output check hua hai
- [ ] Actions tab me workflow manually trigger karke verify kiya hai

---

## 12) Summary in one line

Old system: server + scheduler + multi-account same run.
New system: cron-triggered short script + single account per run + `next_turn` state in Sheets.

Isse GitHub Actions reliable aur stateless execution milta hai.
