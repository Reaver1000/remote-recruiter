"""
Remote Recruiter — AI-powered personalised remote job board.

Flow:
  1. User pastes LinkedIn profile text or CV
  2. Claude analyses their full career and recommends sectors + roles
  3. App searches those roles via JSearch, scores every listing against the
     user's profile, and surfaces the best remote matches worldwide.
"""

import os
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
import anthropic
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
logger = logging.getLogger(__name__)

# ── Clients ───────────────────────────────────────────────────────────────────

RAPIDAPI_KEY    = os.getenv("RAPIDAPI_KEY")
ANTHROPIC_KEY   = os.getenv("ANTHROPIC_API_KEY")
ai              = anthropic.Anthropic(api_key=ANTHROPIC_KEY)

# ── Region → search location strings ─────────────────────────────────────────

REGIONS = {
    "uk":     ["remote United Kingdom", "remote UK", "remote London"],
    "eu":     ["remote Europe", "remote Germany", "remote Netherlands"],
    "us":     ["remote United States", "remote USA"],
    "global": ["remote worldwide", "remote", "remote global"],
    "apac":   ["remote Australia", "remote Singapore", "remote Asia"],
}

# ── Prompts ───────────────────────────────────────────────────────────────────

ANALYSE_PROMPT = """You are a senior headhunter and talent strategist with 20+ years experience placing people across every industry. A candidate has pasted their LinkedIn profile or CV below.

Your job: read it thoroughly and think as broadly as possible about every role this person could realistically be competitive for — not just their obvious next step, but adjacent moves, sector switches, and roles that exploit transferable skills they might not even realise they have.

Return ONLY a valid JSON object (no markdown, no extra text) in this exact structure:

{{
  "name": "First name or 'You'",
  "headline": "One punchy sentence summarising who they are professionally",
  "years_experience": <integer>,
  "career_summary": "3-4 sentences. What have they done, what are they good at, what makes them interesting to a recruiter?",
  "core_skills": ["skill1", "skill2", ...],
  "sectors": [
    {{
      "name": "Sector name",
      "fit": "Excellent|Strong|Good",
      "why": "One sentence — why this sector suits them",
      "emoji": "relevant emoji"
    }}
  ],
  "recommended_roles": [
    {{
      "title": "Job title as it appears on job boards",
      "fit": "Excellent|Strong|Good",
      "why": "One sentence on the match",
      "is_lateral": false,
      "is_stretch": false
    }}
  ]
}}

Rules:
- sectors: return 5-8 sectors, ordered by fit
- recommended_roles: return 10-15 roles. Include their obvious next step, 3-4 lateral moves, 2-3 sector pivots, and 1-2 stretch/leadership roles if experience warrants it
- is_lateral: true if this is a sideways move using transferable skills
- is_stretch: true if this requires growth or a significant step up
- Be specific with job titles — use terms that actually appear on job boards (e.g. "Head of Growth" not "Growth Leader")

CANDIDATE PROFILE:
{profile}"""


SCORE_PROMPT = """You are a recruiter reviewing a job listing on behalf of a candidate. Be honest but look for every reason this could be a good fit — your job is to advocate for them, not gatekeep.

CANDIDATE PROFILE SUMMARY:
{profile_summary}

JOB LISTING:
Title: {title}
Company: {company}
Location / Remote: {location}
Type: {emp_type}
Description:
{description}

Score this match. Reply with ONLY valid JSON, no markdown:
{{
  "score": <integer 1-10>,
  "match_level": "Excellent|Good|Fair|Poor",
  "recruiter_note": "2-3 sentences written as if you're a recruiter briefing the candidate. What's compelling about this role for them specifically? What should they emphasise in their application?",
  "key_matches": ["matched skill or experience (max 4)"],
  "watch_outs": ["potential gap or concern (max 2)"]
}}"""


# ── Profile analysis ──────────────────────────────────────────────────────────

def analyse_profile(profile_text: str) -> dict:
    """Send profile to Claude and get structured career analysis."""
    msg = ai.messages.create(
        model="claude-sonnet-4-6",          # richer analysis deserves Sonnet
        max_tokens=2000,
        messages=[{
            "role": "user",
            "content": ANALYSE_PROMPT.format(profile=profile_text[:8000])
        }]
    )
    raw = msg.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1].lstrip("json").strip()
    return json.loads(raw)


# ── Job search ────────────────────────────────────────────────────────────────

def search_jobs_for_role(role: str, location: str, num: int = 8) -> list[dict]:
    """Fetch jobs from JSearch for one role + location string."""
    if not RAPIDAPI_KEY:
        return []
    query = f"{role} {location}"
    try:
        resp = requests.get(
            "https://jsearch.p.rapidapi.com/search",
            headers={
                "X-RapidAPI-Key": RAPIDAPI_KEY,
                "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
            },
            params={"query": query, "page": "1", "num_pages": "1", "date_posted": "all"},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json().get("data", [])[:num]
    except Exception as e:
        logger.warning("JSearch error for '%s' / '%s': %s", role, location, e)
        return []


def gather_jobs(roles: list[str], region_key: str, per_role: int = 6) -> list[dict]:
    """
    Search all selected roles across the region's location strings in parallel.
    Deduplicate by job_id and cap total results.
    """
    locations = REGIONS.get(region_key, REGIONS["global"])

    tasks = []
    for role in roles[:6]:                          # cap roles to avoid API rate limits
        for loc in locations[:2]:                   # top 2 locations per region
            tasks.append((role, loc))

    seen, results = set(), []

    def _fetch(args):
        return search_jobs_for_role(args[0], args[1], per_role)

    with ThreadPoolExecutor(max_workers=8) as pool:
        for batch in pool.map(_fetch, tasks):
            for job in batch:
                jid = job.get("job_id")
                if jid and jid not in seen:
                    seen.add(jid)
                    results.append(job)

    logger.info("Gathered %d unique jobs across %d role/location combos", len(results), len(tasks))
    return results


# ── AI scoring ────────────────────────────────────────────────────────────────

def score_job(job: dict, profile_summary: str) -> dict:
    """Ask Claude to score one job against the candidate summary."""
    loc_parts = [job.get("job_city",""), job.get("job_state",""), job.get("job_country","")]
    location  = ", ".join(p for p in loc_parts if p) or "Not specified"
    if job.get("job_is_remote"):
        location = f"Remote — {location}"

    try:
        msg = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=500,
            messages=[{"role": "user", "content": SCORE_PROMPT.format(
                profile_summary = profile_summary[:3000],
                title       = job.get("job_title", "N/A"),
                company     = job.get("employer_name", "N/A"),
                location    = location,
                emp_type    = job.get("job_employment_type", "N/A"),
                description = (job.get("job_description") or "")[:2500],
            )}]
        )
        raw = msg.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1].lstrip("json").strip()
        return json.loads(raw)
    except Exception as e:
        logger.warning("Scoring failed for '%s': %s", job.get("job_title"), e)
        return {
            "score": 0, "match_level": "Unknown",
            "recruiter_note": "Scoring unavailable for this listing.",
            "key_matches": [], "watch_outs": [],
        }


def score_jobs_parallel(jobs: list[dict], profile_summary: str) -> list[dict]:
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(score_job, job, profile_summary): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            job["ai_score"] = future.result()
    return jobs


# ── Serialisation ─────────────────────────────────────────────────────────────

def serialise_job(job: dict) -> dict:
    loc_parts = [job.get("job_city",""), job.get("job_state",""), job.get("job_country","")]
    location  = ", ".join(p for p in loc_parts if p) or "Location not specified"

    sal_min = job.get("job_min_salary")
    sal_max = job.get("job_max_salary")
    currency = job.get("job_salary_currency") or "USD"
    period   = job.get("job_salary_period") or "yr"
    if sal_min and sal_max:
        salary = f"{currency} {int(sal_min):,}–{int(sal_max):,} / {period}"
    elif sal_min or sal_max:
        salary = f"{currency} {int(sal_min or sal_max):,} / {period}"
    else:
        salary = None

    posted_raw = job.get("job_posted_at_datetime_utc", "")
    try:
        posted = datetime.fromisoformat(posted_raw.replace("Z","+00:00")).strftime("%d %b %Y")
    except Exception:
        posted = posted_raw[:10] if posted_raw else None

    return {
        "id":              job.get("job_id", ""),
        "title":           job.get("job_title", "N/A"),
        "company":         job.get("employer_name", "N/A"),
        "company_logo":    job.get("employer_logo"),
        "location":        location,
        "is_remote":       bool(job.get("job_is_remote")),
        "employment_type": job.get("job_employment_type", ""),
        "salary":          salary,
        "description":     ((job.get("job_description") or "")[:600]).rstrip() + "…",
        "apply_link":      job.get("job_apply_link", "#"),
        "posted":          posted,
        "ai_score":        job.get("ai_score"),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyse", methods=["POST"])
def analyse():
    """Step 1 → 2: analyse profile, return career summary + recommendations."""
    body = request.get_json(force=True)
    profile_text = (body.get("profile") or "").strip()

    if not profile_text:
        return jsonify({"error": "Please paste your LinkedIn profile or CV text."}), 400
    if not ANTHROPIC_KEY:
        return jsonify({"error": "ANTHROPIC_API_KEY is not set in .env"}), 500

    try:
        analysis = analyse_profile(profile_text)
        return jsonify(analysis)
    except json.JSONDecodeError:
        return jsonify({"error": "Could not parse AI response — try again."}), 500
    except Exception as e:
        logger.error("Analysis error: %s", e)
        return jsonify({"error": str(e)}), 500


@app.route("/search", methods=["POST"])
def search():
    """Step 2 → 3: search selected roles for region, score, return results."""
    body            = request.get_json(force=True)
    roles           = body.get("roles", [])          # list of job title strings
    region_key      = body.get("region", "global")
    profile_summary = (body.get("profile_summary") or "").strip()

    if not roles:
        return jsonify({"error": "No roles selected."}), 400
    if not RAPIDAPI_KEY:
        return jsonify({"error": "RAPIDAPI_KEY is not set in .env"}), 500

    try:
        jobs = gather_jobs(roles, region_key)
    except Exception as e:
        logger.error("Job gather error: %s", e)
        return jsonify({"error": f"Job search failed: {e}"}), 500

    if not jobs:
        return jsonify([])

    if profile_summary and ANTHROPIC_KEY:
        jobs = score_jobs_parallel(jobs, profile_summary)
        jobs.sort(
            key=lambda j: (j.get("ai_score") or {}).get("score", 0),
            reverse=True
        )

    return jsonify([serialise_job(j) for j in jobs])


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, port=5000)
