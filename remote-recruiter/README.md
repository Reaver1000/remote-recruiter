# 🌍 Remote Recruiter — Your AI Headhunter

> Paste your LinkedIn profile. Get every role you could be competitive for. Find remote jobs that actually hire where you live.

![Python](https://img.shields.io/badge/Python-3.11+-blue?logo=python)
![Flask](https://img.shields.io/badge/Flask-3.0-black?logo=flask)
![Claude](https://img.shields.io/badge/Claude-Sonnet%20%2B%20Haiku-purple?logo=anthropic)
![License](https://img.shields.io/badge/License-MIT-green)

---

## The Problem

Most job tools either show you roles you already know about, or surface "remote" jobs that are quietly US-only. If you're in the UK, Europe, or APAC looking for genuinely remote work — you know the struggle.

**Remote Recruiter** takes a different approach: it reads your entire career history and acts as a senior headhunter on your side — identifying roles you might never have considered, then hunting down live listings that will actually hire in your region.

---

## ✨ Features

### 🧠 AI Career Analysis (Claude Sonnet)
- Paste your LinkedIn profile (`Ctrl+A` → `Ctrl+C` on your profile page) or your CV
- Claude reads your full career history and returns:
  - A sharp career summary
  - Your core transferable skills
  - 5–8 best-fit sectors with explanations
  - 10–15 recommended roles: obvious next steps, lateral moves, sector pivots, and stretch roles

### 🌍 Remote-First, Region-Aware Job Search
- Search across all recommended roles simultaneously
- Choose your target region: UK, Europe, North America, APAC, or Global
- Filters search terms to surface roles that genuinely hire in your region (not just "remote = US")

### 🎯 AI Match Scoring (Claude Haiku)
- Every listing is scored 1–10 against your profile in parallel
- Each card includes:
  - A **recruiter's take** — written as if a headhunter is briefing you before an application
  - Matched skills and watch-outs highlighted
  - Sort by best match or most recent

### 💅 Clean 3-Step UI
- Step 1: Paste profile
- Step 2: Review AI analysis, toggle which roles to search, pick region
- Step 3: Browse personalised job board

---

## 🚀 Quick Start

### 1. Clone & install

```bash
git clone https://github.com/Reaver1000/remote-recruiter.git
cd remote-recruiter
pip install -r requirements.txt
```

### 2. Set up API keys

```bash
cp .env.example .env
# Edit .env with your keys
```

Two free-tier keys needed:

| Key | Where to get it | Free tier |
|---|---|---|
| `RAPIDAPI_KEY` | [JSearch on RapidAPI](https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch) | 200 req/month |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) | Pay-per-use (~$0.01 per full search) |

### 3. Run

```bash
python app.py
```

Visit [http://localhost:5000](http://localhost:5000)

---

## 🏗️ Architecture

```
remote-recruiter/
├── app.py                  # Flask backend
│   ├── /analyse            # Profile → career analysis (Claude Sonnet)
│   └── /search             # Multi-role job search + parallel AI scoring
├── templates/
│   └── index.html          # 3-step SPA dashboard
├── requirements.txt
├── .env.example
└── README.md
```

### How the search works

1. The user selects roles from the AI recommendations (up to 6 searched)
2. For each role, the app searches across 2 location strings for the chosen region
3. All searches run in parallel via `ThreadPoolExecutor`
4. Results are deduplicated by `job_id`
5. Every job is scored against the user's profile summary — also in parallel
6. Results are sorted by AI match score

---

## 🔧 Customisation

**Add more regions** — edit the `REGIONS` dict in `app.py`:
```python
REGIONS = {
    "uk":     ["remote United Kingdom", "remote UK", "remote London"],
    "eu":     ["remote Europe", "remote Germany", ...],
    ...
}
```

**Tune the AI prompts** — `ANALYSE_PROMPT` and `SCORE_PROMPT` in `app.py` are easy to edit. The recruiter framing in `SCORE_PROMPT` is what makes the "recruiter's take" feel personal.

**Increase results** — change `per_role=6` in `gather_jobs()` to fetch more per role (watch your API rate limits).

---

## 💰 API Cost Estimate

A typical session (paste profile → analyse → search 5 roles → score 30 jobs):
- Profile analysis: ~$0.003 (Sonnet)
- Job scoring (30 × Haiku): ~$0.009
- **Total: ~$0.01–0.02 per session**

---

## 📄 License

MIT — use it, fork it, build on it.
