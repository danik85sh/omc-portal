# Deploy OMC Portal (free, ~3 minutes)

A one-click **Deploy to Render** button does most of the work. You only need a
free GitHub account and a free Render account — no credit card.

## Step 1 — Put the code on GitHub

From inside the `omc-portal/` folder:

```bash
git init
git add .
git commit -m "OMC Portal"
# create an empty repo on github.com first, then:
git remote add origin https://github.com/YOUR_USERNAME/omc-portal.git
git branch -M main
git push -u origin main
```

(No git? On github.com click **New repository → uploading an existing file** and
drag the whole `omc-portal` folder in.)

## Step 2 — Update the deploy button URL

In `README.md` (and the link below), replace `YOUR_USERNAME/omc-portal` with your
actual repo path, commit, and push. The button then points at your repo.

## Step 3 — Click Deploy

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/YOUR_USERNAME/omc-portal)

Or paste this into your browser (with your repo path):

```
https://render.com/deploy?repo=https://github.com/YOUR_USERNAME/omc-portal
```

Render reads `render.yaml`, creates a free web service + a 1 GB persistent disk
(for the SQLite database), and generates `SECRET_KEY` automatically.

## Step 4 — Set the environment variables

When prompted (or afterwards in **Dashboard → your service → Environment**), set:

| Variable | Value |
|---|---|
| `BASE_URL` | Your Render URL, e.g. `https://omc-portal-xxxx.onrender.com` |
| `DIRECTOR_EMAILS` | Your director email(s), comma-separated |
| `GROQ_API_KEY` | Free key from https://console.groq.com/keys |

Optional, for real sign-in emails (otherwise the link appears in **Logs**):

| Variable | Value |
|---|---|
| `SMTP_HOST` | e.g. `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | your email |
| `SMTP_PASSWORD` | app password |
| `SMTP_FROM` | the "from" address |

Save → Render redeploys. Your site is live at the `BASE_URL`.

## Step 5 — Sign in as a director

Go to `https://your-url/login`, enter an email listed in `DIRECTOR_EMAILS`, and
open the magic link (from the email, or from Render **Logs** if SMTP isn't set).
You'll be an admin and can schedule meetings and create polls.

---

### Persistent data (important)
Render's **free** tier does not allow a persistent disk, so the SQLite database
resets whenever the service redeploys or restarts. Options:
- **Just trying it out:** leave as-is (data is temporary).
- **Durable, still cheap:** add a paid disk ($1–2/mo) — re-add the `disk:` block
  in `render.yaml` and point `DATABASE_PATH` at its mount path.
- **Durable & free:** create a free **PostgreSQL** instance on Render and switch
  the app's storage to it (small code change — ask and it can be added).

### Notes
- **Free-tier sleep:** Render's free web service spins down after ~15 min idle;
  the first visit after that takes ~30s to wake. Fine for an OMC site.
- **Other hosts:** the included `Procfile` (`web: gunicorn app:app`) also works on
  Railway, Fly.io, Heroku, etc. — set the same env vars there.
