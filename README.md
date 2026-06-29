# OMC Portal

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/YOUR_USERNAME/omc-portal)

> **One-click deploy:** push this folder to a GitHub repo, then replace
> `YOUR_USERNAME/omc-portal` in the button URL above (and in `DEPLOY.md`) with
> your repo. Clicking the button sends Render straight to a free-tier deploy that
> reads `render.yaml`. See **[DEPLOY.md](DEPLOY.md)** for the 3-minute walkthrough.

A small, free-to-run website for **Owners' Management Company** directors and
property owners. Owners post items for the next meeting (with their email or
anonymously), directors schedule meetings and run votes, and a local AI agent
turns every submission into a suggested agenda discussion point.

## What it does

- **Post agenda items** — any owner can submit a report/issue/proposal. They can
  include their email *or* tick "anonymous" to hide it.
- **AI agenda analysis** — each submission is analysed by a free cloud AI API
  (Groq by default), which produces a one-line summary, a category, a priority,
  and a neutral *discussion point* that is added to the agenda list. You can
  switch to Google Gemini or a local Ollama model instead. If the provider is
  unavailable or no key is set, a built-in keyword analyser is used so nothing
  breaks.
- **Meetings** — directors schedule meetings (date, location, notes) and attach
  agenda items to them.
- **Voting** — directors create polls (e.g. proposed AGM dates, motions, budget
  approval). Signed-in owners vote once per poll; results show live with bars.
- **Email magic-link login** — owners sign in with a one-time email link, no
  passwords. Directors are auto-promoted by email (see `DIRECTOR_EMAILS`).

## Quick start (local / lab)

```bash
cd omc-portal
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # then edit .env
python app.py                 # http://127.0.0.1:5000
```

Sign in: go to `/login`, enter your email. If SMTP isn't configured, the
**sign-in link is printed in the server log** — copy it into your browser.
Any email listed in `DIRECTOR_EMAILS` becomes a director on first login.

## The AI agent (free cloud API)

The AI agent uses a free cloud API. Pick a provider with `AI_PROVIDER`.

### Groq (default — free, no credit card)
1. Create a free key at https://console.groq.com/keys
2. In `.env`:
   ```
   AI_ENABLED=1
   AI_PROVIDER=groq
   GROQ_API_KEY=gsk_your_key_here
   GROQ_MODEL=llama-3.3-70b-versatile
   ```
Groq is OpenAI-compatible and very fast. The free tier needs no card; typical
limits are ~30 requests/min and ~1,000 requests/day for the 70B model — far more
than an OMC site needs.

### Google Gemini (alternative free tier)
1. Create a key at https://aistudio.google.com/apikey
2. In `.env`:
   ```
   AI_ENABLED=1
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your_key_here
   GEMINI_MODEL=gemini-2.5-flash
   ```

### Local Ollama (fully offline, optional)
Set `AI_PROVIDER=ollama`, run `ollama pull llama3.2 && ollama serve`, and point
`OLLAMA_BASE_URL` at it.

If the chosen provider is unreachable or no key is set, the app automatically
falls back to a built-in keyword analyser, so submissions always get a category
and agenda point.

## Deploying to a free cloud tier

`render.yaml` is included for **Render.com** (free web service + 1 GB free disk):

1. Push this folder to a GitHub repo.
2. In Render: New → **Blueprint** → pick the repo. It reads `render.yaml`.
3. Set `BASE_URL` to your Render URL (e.g. `https://omc-portal.onrender.com`)
   and `DIRECTOR_EMAILS` to your director addresses.
4. Set `GROQ_API_KEY` in the Render dashboard (the AI works fully in the cloud
   this way — no lab machine needed).
5. Configure SMTP env vars so magic-link emails actually send (a free Gmail
   app-password or a free SendGrid/Mailgun tier works).

The `Procfile` (`web: gunicorn app:app`) also works on Railway, Fly.io, and most
PaaS free tiers. Because the AI is a cloud API call, analysis runs the same
locally and when hosted — just set the relevant API key as an env var.

## Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session secret (use a long random string). |
| `DATABASE_PATH` | SQLite file path. Use a persistent disk path in the cloud. |
| `BASE_URL` | Public URL, used to build magic-link emails. |
| `DIRECTOR_EMAILS` | Comma-separated emails auto-granted director role. |
| `SMTP_*` | Email server for sending sign-in links (optional locally). |
| `AI_ENABLED` | `1` to use AI analysis, `0` for keyword-only. |
| `AI_PROVIDER` | `groq` (default) / `gemini` / `ollama`. |
| `GROQ_API_KEY` / `GROQ_MODEL` | Groq cloud API settings. |
| `GEMINI_API_KEY` / `GEMINI_MODEL` | Gemini cloud API settings. |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | Local Ollama settings. |

## Project layout

```
omc-portal/
  app.py            # Flask app: auth, agenda, meetings, voting
  ai.py             # AI analysis (Ollama + keyword fallback)
  requirements.txt
  Procfile          # gunicorn entrypoint for PaaS
  render.yaml       # Render.com free-tier blueprint
  .env.example
  templates/        # Jinja2 HTML
  static/style.css
```

## Notes & next steps

- Data lives in one SQLite file — easy to back up (just copy the `.db`).
- Anonymous items store no email; the AI still analyses the text.
- Possible extensions: email digest of new agenda items to directors, exporting
  a meeting's agenda to PDF, vote eligibility tied to verified unit ownership.
