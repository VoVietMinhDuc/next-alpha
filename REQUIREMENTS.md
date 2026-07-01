# OptiSigns – OptiBot Mini-Clone Take-Home Test

### (Clarified breakdown — updated version)

> Goal: build a customer-support chatbot that clones OptiBot, using data from OptiSigns' support site, in roughly **10 focused hours**.

---

## 0. Warm-up (15 min)

- [x] Create a free trial account on **optisigns.com** and chat with OptiBot to understand how it answers.
- [ ] Create an account on **one** of these AI platforms:
  - OpenAI → platform.openai.com
  - Google Gemini → aistudio.google.com

**Decision to make now:** OpenAI or Gemini? (Recommended: OpenAI, since it has a built-in Vector Store, saving you a lot of effort.)

---

## Part 1 — Scrape ⇒ Markdown (~3 hours)

**Goal:** prove you can ingest messy web content and normalize it.

| Requirement    | Detail                                                                   |
| -------------- | ------------------------------------------------------------------------ |
| Quantity       | At least **30 articles** from `support.optisigns.com`                    |
| Format         | Convert each article → **clean Markdown**                                |
| File naming    | `<slug>.md` (or any consistent scheme)                                   |
| Must preserve  | Relative links, code blocks, headings                                    |
| Must remove    | Navigation menus, ads                                                    |
| Technical hint | Use the **Zendesk API** to fetch articles (instead of raw HTML scraping) |

**Output of this part:** a folder containing 30+ `.md` files.

---

## Part 2 — Build AI Assistant & Load Vector Store via API (~2 hours)

**Hard rule:** upload must go through the **API** — **no UI drag-and-drop**.

### Step 1 — Create the Assistant

Use OpenAI Playground UI **or** Google AI Studio to create the assistant, with this **verbatim system prompt** (do not modify):

```
You are OptiBot, the customer-support bot for OptiSigns.com.
• Tone: helpful, factual, concise.
• Only answer using the uploaded docs.
• Max 5 bullet points; else link to the doc.
• Cite up to 3 "Article URL:" lines per reply.
```

### Step 2 — Upload data via script

- Write a **Python script** to upload the `.md` files to the vector store / knowledge base of your chosen platform:
  - OpenAI → **Vector Store**
  - Gemini → equivalent feature (File API / build your own embeddings)
- **Chunking strategy**: your choice — but **must be explained in the README**
- **Log:** how many files and how many chunks were embedded

**Reference docs (from the original brief):**

- Upload files to the API → OpenAI Files API / Gemini File API docs
- Attach files to Vector Stores → OpenAI Vector Stores docs
- Overall agent approach → OpenAI Assistants/Agents docs or Google Gemini API docs

### Step 3 — Sanity check

- In Playground (OpenAI) or AI Studio (Gemini), ask:
  > "How do I add a YouTube video?"
- **Take a screenshot** of the correct answer, including citations (source links).
- The answer in the screenshot should also respect the system prompt constraints: only uses the uploaded docs, **max 5 bullet points**, and **cites at most 3 "Article URL:" lines**.

---

## Part 3 — Deploy Scraper as a Daily Job (~2 hours)

**Idea:** wrap the scraper + uploader (Part 1 + Part 2) into one entry point, package it, and run it automatically once a day.

| Requirement | Detail                                                                          |
| ----------- | ------------------------------------------------------------------------------- |
| Entry point | Combine scraper + uploader into `main.py` (or equivalent)                       |
| Packaging   | Write a `Dockerfile`                                                            |
| Schedule    | Run once per day on DigitalOcean **or** Railway, Render, Fly.io, AWS, GCP, etc. |

**Required job logic:**

1. Re-scrape the articles
2. **Detect new/updated articles** (compare content hash, or `Last-Modified` header)
3. **Upload only the delta** (changed content) — **do not re-upload everything each time**
   - ⚠️ **Reuse the existing Vector Store**; do **not** create a brand-new store and dump all files on every run.
   - Only push files that were `added` or `updated`; existing unchanged files stay as-is.
4. **Log counts:** how many articles were `added`, `updated`, `skipped`
5. Provide a **link to the logs** or save the artefact of the latest run

> **Important:** the container should **run the job once and then exit** (exit code 0). It is **not** a long-running daemon — the daily repetition is handled by an **external scheduler** (cron job, platform scheduler, etc.), not by an internal loop inside the container.

---

## Deliverables — What you must submit

| Item            | Specific requirement                                                                                                                                                           |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **GitHub repo** | Name must be **cryptic, must NOT contain "optisigns"** (so it can't easily be found via search). Clear, understandable commits. **No hard-coded API keys** — use `.env.sample` |
| **Dockerfile**  | `docker run -e API_KEY=... main.py` must **run once, complete, and exit with code 0** (one-shot, not a daemon)                                                                 |
| **README**      | Max 1 page, including: setup steps, how to run locally, link to daily job logs, screenshot of the assistant's answer                                                           |
| **Screenshot**  | Assistant correctly answers the sample question, with cited source links (Article URL)                                                                                         |

---

## Grading (pass bar: ≥ 70/100)

| Area                                | Points |
| ----------------------------------- | ------ |
| Scrape & clean quality              | 25     |
| API-based vector-store upload works | 20     |
| Daily job deployment & logs         | 15     |
| Code clarity + README               | 10     |
| Bonus tests                         | +5     |

---

## After submission — 1-hour Project Review

They will interview you about:

1. **Overall concept understanding** — do you grasp the full pipeline
2. **Approach & solution** — why you chose this approach, what trade-offs you made
3. **How you learn something new** — when facing unfamiliar tech (e.g. Vector Store), how do you go about learning it
4. **Suggestions to improve OptiBot** — what could be improved, and what potential challenges you foresee when running a chatbot like this in production (e.g. stale data, hallucination, API cost, latency...)

---

## What's DIFFERENT from the older version of the brief

- ✅ You can now choose **OpenAI or Gemini** (previously OpenAI was mandatory)
- ✅ You can deploy on **multiple cloud platforms** (previously DigitalOcean was mandatory)
- ⚠️ The brief still says **"Via Python script"** in Part 2 — so it's **safer to use Python**, unless you've explicitly confirmed another language is acceptable
- 🔁 Environment variable name changed from `OPENAI_API_KEY` → `API_KEY` (more generic, works for either platform)

---

## Master checklist, in order

```
[ ] 1. Create an OptiSigns trial account + chat with OptiBot
[ ] 2. Create an OpenAI (or Gemini) account
[ ] 3. Write scraper.py → fetch 30+ articles via Zendesk API → save as .md
[ ] 4. Write uploader.py → create a Vector Store, upload .md files via API
[ ] 5. Create the Assistant in Playground with the verbatim system prompt
[ ] 6. Test asking "How do I add a YouTube video?" → take a screenshot
[ ] 7. Write main.py → combine scraper + uploader + delta detection (hashing)
[ ] 8. Write Dockerfile → test docker run -e API_KEY=... main.py
[ ] 9. Deploy to a cloud platform, schedule it to run daily
[ ] 10. Write README (setup, run locally, log link, screenshot)
[ ] 11. Pick a cryptic repo name, push to GitHub, double-check .env.sample
```
