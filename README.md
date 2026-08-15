# Automatic Job Search Agent

Daily automated job search that fetches Data Engineering / Data Science
listings from multiple public sources, scores them against your skill
profile, and emails you a digest of new matches — no manual searching needed.

## Why not scrape LinkedIn/Indeed directly?

Both platforms actively block scrapers (login walls, anti-bot detection,
Terms of Service restrictions), so a direct scraper would break constantly
and risk account/IP bans. Instead this agent uses stable, legitimate public
data sources that together cover overlapping listings:

| Source | What it covers | Auth needed? |
|---|---|---|
| **Adzuna API** | Aggregates Indeed, Monster, and thousands of company career pages | Free API key |
| **Greenhouse API** | Public job boards for companies using Greenhouse ATS | None |
| **Lever API** | Public job boards for companies using Lever ATS | None |
| **RemoteOK API** | Remote-friendly tech roles | None |

## 1. Get an Adzuna API key (free)

1. Sign up at https://developer.adzuna.com/
2. Create an app to get an `app_id` and `app_key`

## 2. Set up email sending (Gmail example)

1. Enable 2-Step Verification on your Google account
2. Create an **App Password**: Google Account → Security → App passwords
3. Use your Gmail address + the generated app password (not your normal password)

## 3. Add GitHub repo secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Secret name | Value |
|---|---|
| `ADZUNA_APP_ID` | from step 1 |
| `ADZUNA_APP_KEY` | from step 1 |
| `EMAIL_ADDRESS` | your Gmail address |
| `EMAIL_APP_PASSWORD` | app password from step 2 |
| `EMAIL_TO` | where you want the digest sent (can be same as EMAIL_ADDRESS) |

## 4. Customize your search

Edit `config.yaml`:
- `search_keywords` — job titles to look for
- `skill_keywords` — your skills, used to score/rank matches
- `min_score` — how many skill keywords must match to include a job
- `greenhouse_companies` / `lever_companies` — add specific companies you want tracked directly (find the slug from the company's careers URL)

## 5. Push to GitHub

```bash
git init
git add .
git commit -m "Initial job search agent"
git remote add origin https://github.com/uroojfatimah11/job-search-agent.git
git push -u origin main
```

The workflow runs automatically every day at 08:00 PKT. You can also trigger
it manually from the **Actions** tab → "Daily Job Search Agent" → "Run workflow".

## 6. Test locally first (recommended)

```bash
pip install -r requirements.txt
export ADZUNA_APP_ID="your_id"
export ADZUNA_APP_KEY="your_key"
export EMAIL_ADDRESS="you@gmail.com"
export EMAIL_APP_PASSWORD="your_app_password"
python main.py
```

If email credentials aren't set, the agent prints the digest to the console
instead — useful for testing your keyword/scoring setup before wiring up email.

## How matching works

A job is included in the digest only if:
1. Its title/description contains at least one of your `search_keywords`, **and**
2. It matches at least `min_score` of your `skill_keywords`

Jobs are ranked by score (most skill overlap first) so the best fits are at
the top of your inbox. Already-seen jobs are tracked in `seen_jobs.json`
(auto-committed by the workflow) so you never get duplicate notifications.

## Extending this

- Add more Greenhouse/Lever company slugs as you find companies you like
- Add a Slack/Telegram webhook instead of (or alongside) email
- Push matches into a Google Sheet or Notion database for tracking
