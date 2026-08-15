"""
Automatic Job Search Agent
---------------------------
Fetches job listings from multiple legitimate public sources, scores them
against your skill profile, filters out jobs you've already seen, and
emails you a digest of new, relevant matches.

Sources used:
  - Adzuna API        (aggregates Indeed, Monster, and many company sites)
  - Greenhouse API     (public job-board JSON for companies using Greenhouse ATS)
  - Lever API           (public job-board JSON for companies using Lever ATS)
  - RemoteOK API      (public JSON, remote-friendly roles)

Note: LinkedIn and Indeed direct scraping is intentionally NOT used here,
since both actively block scrapers and it violates their Terms of Service.
Adzuna's aggregation covers a large overlapping set of listings instead.

Run manually with:  python main.py
Run automatically via the included GitHub Actions workflow.
"""

import os
import json
import smtplib
import yaml
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.yaml"
SEEN_JOBS_PATH = Path(__file__).parent / "seen_jobs.json"


# ------------------------------------------------------------------
# Config & state helpers
# ------------------------------------------------------------------

def load_config():
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f)


def load_seen_jobs():
    if SEEN_JOBS_PATH.exists():
        with open(SEEN_JOBS_PATH, "r") as f:
            return set(json.load(f))
    return set()


def save_seen_jobs(seen_ids):
    with open(SEEN_JOBS_PATH, "w") as f:
        json.dump(sorted(seen_ids), f, indent=2)


# ------------------------------------------------------------------
# Source fetchers — each returns a list of dicts:
# {id, title, company, location, url, description}
# ------------------------------------------------------------------

def fetch_adzuna_jobs(config):
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("Skipping Adzuna: ADZUNA_APP_ID / ADZUNA_APP_KEY not set.")
        return []

    jobs = []
    countries = config.get("adzuna_countries", ["gb"])
    for country in countries:
        for keyword in config["search_keywords"]:
            url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/1"
            params = {
                "app_id": app_id,
                "app_key": app_key,
                "results_per_page": config.get("max_results_per_source", 30),
                "what": keyword,
                "content-type": "application/json",
            }
            try:
                resp = requests.get(url, params=params, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("results", []):
                    jobs.append({
                        "id": f"adzuna-{country}-{item.get('id')}",
                        "title": item.get("title", ""),
                        "company": item.get("company", {}).get("display_name", "Unknown"),
                        "location": item.get("location", {}).get("display_name", ""),
                        "url": item.get("redirect_url", ""),
                        "description": item.get("description", ""),
                    })
            except requests.RequestException as e:
                print(f"Adzuna fetch failed for '{keyword}' in '{country}': {e}")
    return jobs


def fetch_greenhouse_jobs(config):
    jobs = []
    for company in config.get("greenhouse_companies", []):
        url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("jobs", [])[: config.get("max_results_per_source", 30)]:
                jobs.append({
                    "id": f"greenhouse-{item.get('id')}",
                    "title": item.get("title", ""),
                    "company": company,
                    "location": (item.get("location") or {}).get("name", ""),
                    "url": item.get("absolute_url", ""),
                    "description": item.get("content", ""),
                })
        except requests.RequestException as e:
            print(f"Greenhouse fetch failed for '{company}': {e}")
    return jobs


def fetch_lever_jobs(config):
    jobs = []
    for company in config.get("lever_companies", []):
        url = f"https://api.lever.co/v0/postings/{company}?mode=json"
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            data = resp.json()
            for item in data[: config.get("max_results_per_source", 30)]:
                jobs.append({
                    "id": f"lever-{item.get('id')}",
                    "title": item.get("text", ""),
                    "company": company,
                    "location": (item.get("categories") or {}).get("location", ""),
                    "url": item.get("hostedUrl", ""),
                    "description": item.get("descriptionPlain", ""),
                })
        except requests.RequestException as e:
            print(f"Lever fetch failed for '{company}': {e}")
    return jobs


def fetch_remoteok_jobs(config):
    if not config.get("use_remoteok", True):
        return []
    jobs = []
    try:
        resp = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": "job-search-agent"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        # First item is metadata, skip it
        for item in data[1:]:
            title = item.get("position", "")
            if not title:
                continue
            jobs.append({
                "id": f"remoteok-{item.get('id')}",
                "title": title,
                "company": item.get("company", "Unknown"),
                "location": item.get("location", "Remote"),
                "url": item.get("url", ""),
                "description": " ".join(item.get("tags", [])) + " " + item.get("description", ""),
            })
    except requests.RequestException as e:
        print(f"RemoteOK fetch failed: {e}")
    return jobs[: config.get("max_results_per_source", 30)]


# ------------------------------------------------------------------
# Matching & scoring
# ------------------------------------------------------------------

def score_job(job, config):
    text = f"{job['title']} {job['description']}".lower()

    # Must match at least one target job title keyword
    title_match = any(kw.lower() in text for kw in config["search_keywords"])
    if not title_match:
        return 0

    score = sum(1 for skill in config["skill_keywords"] if skill.lower() in text)
    return score


def filter_and_rank_jobs(all_jobs, seen_ids, config):
    new_matches = []
    for job in all_jobs:
        if job["id"] in seen_ids:
            continue
        score = score_job(job, config)
        if score >= config.get("min_score", 2):
            job["score"] = score
            new_matches.append(job)

    new_matches.sort(key=lambda j: j["score"], reverse=True)
    return new_matches


# ------------------------------------------------------------------
# Email digest
# ------------------------------------------------------------------

def build_email_body(matches):
    lines = [f"Found {len(matches)} new matching job(s) today:\n"]
    for job in matches:
        lines.append(f"• {job['title']} — {job['company']} ({job['location']})")
        lines.append(f"  Match score: {job['score']}  |  {job['url']}\n")
    return "\n".join(lines)


def send_email_digest(matches):
    email_from = os.environ.get("EMAIL_ADDRESS")
    email_password = os.environ.get("EMAIL_APP_PASSWORD")
    email_to = os.environ.get("EMAIL_TO", email_from)

    if not email_from or not email_password:
        print("Email credentials not set (EMAIL_ADDRESS / EMAIL_APP_PASSWORD). "
              "Printing digest instead:\n")
        print(build_email_body(matches))
        return

    msg = MIMEMultipart()
    msg["From"] = email_from
    msg["To"] = email_to
    msg["Subject"] = f"Job Search Agent: {len(matches)} new match(es)"
    msg.attach(MIMEText(build_email_body(matches), "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(email_from, email_password)
            server.sendmail(email_from, email_to, msg.as_string())
        print(f"Email sent to {email_to} with {len(matches)} matches.")
    except smtplib.SMTPException as e:
        print(f"Failed to send email: {e}")


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

def main():
    config = load_config()
    seen_ids = load_seen_jobs()

    all_jobs = []
    all_jobs += fetch_adzuna_jobs(config)
    all_jobs += fetch_greenhouse_jobs(config)
    all_jobs += fetch_lever_jobs(config)
    all_jobs += fetch_remoteok_jobs(config)

    print(f"Fetched {len(all_jobs)} total listings across all sources.")

    new_matches = filter_and_rank_jobs(all_jobs, seen_ids, config)
    print(f"Found {len(new_matches)} new matching job(s) after filtering.")

    if new_matches:
        send_email_digest(new_matches)
    else:
        print("No new matches today — no email sent.")

    # Mark everything we fetched as seen (whether matched or not),
    # so we don't re-score them every run.
    seen_ids.update(job["id"] for job in all_jobs)
    save_seen_jobs(seen_ids)


if __name__ == "__main__":
    main()