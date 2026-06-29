"""
OMC Portal — a small site for Owners' Management Company directors and owners.

Features
  * Email magic-link login (owner / director roles).
  * Owners post reports / agenda items, with their email shown OR anonymously.
  * Each submission is analysed by a local AI agent (Ollama) which adds a
    suggested discussion point + category + priority to the agenda list.
  * Directors schedule meetings and create polls (e.g. proposed dates, motions).
  * Owners vote once per poll; results are shown live.

Single-file Flask app backed by SQLite. Run with `python app.py` (dev) or
`gunicorn app:app` (production / free cloud tier).
"""
import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from functools import wraps

import requests
from flask import (Flask, g, redirect, render_template, request, session,
                   url_for, flash, abort)

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

import ai
import database

# ---------------------------------------------------------------- config
app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:5000").rstrip("/")
DIRECTOR_EMAILS = {e.strip().lower() for e in
                   os.environ.get("DIRECTOR_EMAILS", "").split(",") if e.strip()}
TOKEN_TTL_MIN = 30

# ---------------------------------------------------------------- database
SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL DEFAULT 'owner',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS login_tokens (
    token TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS meetings (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    scheduled_for TEXT,
    location TEXT,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agenda_items (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    author_email TEXT,          -- NULL when submitted anonymously
    is_anonymous INTEGER NOT NULL DEFAULT 0,
    ai_summary TEXT,
    ai_category TEXT,
    ai_priority TEXT,
    ai_point TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);
CREATE TABLE IF NOT EXISTS polls (
    id INTEGER PRIMARY KEY,
    meeting_id INTEGER,
    question TEXT NOT NULL,
    closes_at TEXT,
    is_closed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    FOREIGN KEY (meeting_id) REFERENCES meetings(id)
);
CREATE TABLE IF NOT EXISTS poll_options (
    id INTEGER PRIMARY KEY,
    poll_id INTEGER NOT NULL,
    label TEXT NOT NULL,
    FOREIGN KEY (poll_id) REFERENCES polls(id)
);
CREATE TABLE IF NOT EXISTS votes (
    id INTEGER PRIMARY KEY,
    poll_id INTEGER NOT NULL,
    option_id INTEGER NOT NULL,
    voter_email TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (poll_id, voter_email)
);
"""


def get_db():
    if "db" not in g:
        g.db = database.connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    database.init(SCHEMA)


# ---------------------------------------------------------------- helpers
def now():
    return datetime.utcnow().isoformat(timespec="seconds")


def current_user():
    email = session.get("email")
    if not email:
        return None
    return get_db().execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()


@app.context_processor
def inject_user():
    return {"user": current_user()}


def login_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        if not session.get("email"):
            flash("Please sign in to continue.", "warn")
            return redirect(url_for("login", next=request.path))
        return view(*a, **kw)
    return wrapped


def director_required(view):
    @wraps(view)
    def wrapped(*a, **kw):
        u = current_user()
        if not u or u["role"] != "director":
            abort(403)
        return view(*a, **kw)
    return wrapped


def send_login_email(email, link):
    """Send the magic-link email. Prefers the Brevo HTTP API (port 443), which
    works on hosts that block SMTP ports such as Render. Falls back to SMTP,
    then to logging. Never raises — sign-in must not 500 if mail fails."""
    subject = "Your OMC Portal sign-in link"
    text = f"Click to sign in (valid {TOKEN_TTL_MIN} minutes):\n\n{link}\n"
    sender = os.environ.get("SMTP_FROM", "omc-portal@example.com")
    try:
        brevo_key = os.environ.get("BREVO_API_KEY")
        if brevo_key:
            r = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": brevo_key,
                         "accept": "application/json",
                         "content-type": "application/json"},
                json={"sender": {"email": sender, "name": "OMC Portal"},
                      "to": [{"email": email}],
                      "subject": subject,
                      "textContent": text},
                timeout=15)
            r.raise_for_status()
            print(f"[mail] Brevo API: sent to {email}")
            return True
        host = os.environ.get("SMTP_HOST")
        if host:
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = email
            msg.set_content(text)
            with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", 587)),
                              timeout=15) as s:
                s.starttls()
                user = os.environ.get("SMTP_USER")
                if user:
                    s.login(user, os.environ.get("SMTP_PASSWORD", ""))
                s.send_message(msg)
            print(f"[mail] SMTP: sent to {email}")
            return True
    except Exception as exc:  # noqa: BLE001
        print(f"[mail] send failed ({exc}); link logged below.")
    # Fallback: log the link so sign-in still works.
    print(f"\n[magic-link] for {email}:\n  {link}\n")
    return False


# ---------------------------------------------------------------- auth
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if "@" not in email:
            flash("Please enter a valid email address.", "error")
            return redirect(url_for("login"))
        token = secrets.token_urlsafe(32)
        expires = (datetime.utcnow() + timedelta(minutes=TOKEN_TTL_MIN)).isoformat()
        db = get_db()
        db.execute("INSERT INTO login_tokens (token, email, expires_at) VALUES (?,?,?)",
                   (token, email, expires))
        db.commit()
        link = f"{BASE_URL}{url_for('magic', token=token)}"
        send_login_email(email, link)
        flash("Check your email for a sign-in link. "
              "(If email isn't configured, the link is in the server log.)", "ok")
        return redirect(url_for("login"))
    return render_template("login.html")


@app.route("/magic/<token>")
def magic(token):
    db = get_db()
    row = db.execute("SELECT * FROM login_tokens WHERE token = ?", (token,)).fetchone()
    if (not row or row["used"]
            or datetime.fromisoformat(row["expires_at"]) < datetime.utcnow()):
        flash("That sign-in link is invalid or has expired.", "error")
        return redirect(url_for("login"))
    db.execute("UPDATE login_tokens SET used = 1 WHERE token = ?", (token,))
    email = row["email"]
    user = db.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if not user:
        role = "director" if email in DIRECTOR_EMAILS else "owner"
        db.execute("INSERT INTO users (email, role, created_at) VALUES (?,?,?)",
                   (email, role, now()))
    elif email in DIRECTOR_EMAILS and user["role"] != "director":
        db.execute("UPDATE users SET role = 'director' WHERE email = ?", (email,))
    db.commit()
    session["email"] = email
    flash("You're signed in.", "ok")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Signed out.", "ok")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- home / agenda
@app.route("/")
def index():
    db = get_db()
    meetings = db.execute(
        "SELECT * FROM meetings WHERE status != 'archived' "
        "ORDER BY COALESCE(scheduled_for, created_at) DESC LIMIT 5").fetchall()
    open_items = db.execute(
        "SELECT * FROM agenda_items WHERE status = 'open' "
        "ORDER BY created_at DESC LIMIT 10").fetchall()
    open_polls = db.execute(
        "SELECT * FROM polls WHERE is_closed = 0 ORDER BY created_at DESC").fetchall()
    return render_template("index.html", meetings=meetings,
                           items=open_items, polls=open_polls)


@app.route("/agenda")
def agenda():
    db = get_db()
    items = db.execute(
        "SELECT * FROM agenda_items ORDER BY "
        "CASE ai_priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        "created_at DESC").fetchall()
    return render_template("agenda.html", items=items)


@app.route("/agenda/new", methods=["GET", "POST"])
def new_item():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        body = request.form.get("body", "").strip()
        anonymous = request.form.get("anonymous") == "on"
        # Email: prefer the signed-in user; otherwise take the provided field.
        signed_in = session.get("email")
        email = (signed_in or request.form.get("email", "").strip().lower()) or None
        if not title or not body:
            flash("Please provide both a subject and a message.", "error")
            return redirect(url_for("new_item"))
        author = None if anonymous else email
        analysis = ai.analyze(title, body)
        db = get_db()
        db.execute(
            "INSERT INTO agenda_items "
            "(title, body, author_email, is_anonymous, ai_summary, ai_category, "
            " ai_priority, ai_point, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (title, body, author, 1 if anonymous else 0,
             analysis["summary"], analysis["category"], analysis["priority"],
             analysis["agenda_point"], now()))
        db.commit()
        flash("Thanks — your item was added to the agenda and analysed.", "ok")
        return redirect(url_for("agenda"))
    return render_template("new_item.html")


@app.route("/agenda/<int:item_id>")
def item(item_id):
    row = get_db().execute("SELECT * FROM agenda_items WHERE id = ?",
                           (item_id,)).fetchone()
    if not row:
        abort(404)
    return render_template("item.html", item=row)


@app.route("/agenda/<int:item_id>/status", methods=["POST"])
@director_required
def item_status(item_id):
    new_status = request.form.get("status", "open")
    meeting_id = request.form.get("meeting_id") or None
    db = get_db()
    db.execute("UPDATE agenda_items SET status = ?, meeting_id = ? WHERE id = ?",
               (new_status, meeting_id, item_id))
    db.commit()
    flash("Agenda item updated.", "ok")
    return redirect(url_for("item", item_id=item_id))


# ---------------------------------------------------------------- meetings
@app.route("/meetings")
def meetings():
    rows = get_db().execute(
        "SELECT * FROM meetings ORDER BY COALESCE(scheduled_for, created_at) DESC"
    ).fetchall()
    return render_template("meetings.html", meetings=rows)


@app.route("/meetings/new", methods=["GET", "POST"])
@director_required
def new_meeting():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        scheduled_for = request.form.get("scheduled_for", "").strip() or None
        location = request.form.get("location", "").strip()
        notes = request.form.get("notes", "").strip()
        if not title:
            flash("Please give the meeting a title.", "error")
            return redirect(url_for("new_meeting"))
        db = get_db()
        cur = db.execute(
            "INSERT INTO meetings (title, scheduled_for, location, notes, created_at) "
            "VALUES (?,?,?,?,?) RETURNING id", (title, scheduled_for, location, notes, now()))
        db.commit()
        return redirect(url_for("meeting", meeting_id=cur.lastrowid))
    return render_template("new_meeting.html")


@app.route("/meetings/<int:meeting_id>")
def meeting(meeting_id):
    db = get_db()
    m = db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
    if not m:
        abort(404)
    items = db.execute(
        "SELECT * FROM agenda_items WHERE meeting_id = ? ORDER BY "
        "CASE ai_priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END",
        (meeting_id,)).fetchall()
    polls = _polls_with_results(db, meeting_id=meeting_id)
    unassigned = db.execute(
        "SELECT * FROM agenda_items WHERE meeting_id IS NULL AND status='open' "
        "ORDER BY created_at DESC").fetchall()
    return render_template("meeting.html", meeting=m, items=items,
                           polls=polls, unassigned=unassigned)


# ---------------------------------------------------------------- voting
def _polls_with_results(db, meeting_id=None, poll_id=None):
    if poll_id is not None:
        polls = db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchall()
    elif meeting_id is not None:
        polls = db.execute("SELECT * FROM polls WHERE meeting_id = ? "
                           "ORDER BY created_at", (meeting_id,)).fetchall()
    else:
        polls = db.execute("SELECT * FROM polls ORDER BY created_at DESC").fetchall()
    result = []
    voter = session.get("email")
    for p in polls:
        options = db.execute("SELECT * FROM poll_options WHERE poll_id = ?",
                             (p["id"],)).fetchall()
        counts, total = [], 0
        for o in options:
            n = db.execute("SELECT COUNT(*) c FROM votes WHERE option_id = ?",
                           (o["id"],)).fetchone()["c"]
            total += n
            counts.append({"id": o["id"], "label": o["label"], "count": n})
        for c in counts:
            c["pct"] = round(100 * c["count"] / total) if total else 0
        my_vote = None
        if voter:
            mv = db.execute("SELECT option_id FROM votes WHERE poll_id=? AND voter_email=?",
                            (p["id"], voter)).fetchone()
            my_vote = mv["option_id"] if mv else None
        result.append({"poll": p, "options": counts, "total": total,
                       "my_vote": my_vote})
    return result


@app.route("/polls")
def polls():
    return render_template("polls.html",
                           polls=_polls_with_results(get_db()))


@app.route("/polls/new", methods=["GET", "POST"])
@director_required
def new_poll():
    if request.method == "POST":
        question = request.form.get("question", "").strip()
        meeting_id = request.form.get("meeting_id") or None
        closes_at = request.form.get("closes_at", "").strip() or None
        options = [o.strip() for o in request.form.getlist("options") if o.strip()]
        if not question or len(options) < 2:
            flash("A poll needs a question and at least two options.", "error")
            return redirect(url_for("new_poll"))
        db = get_db()
        cur = db.execute(
            "INSERT INTO polls (meeting_id, question, closes_at, created_at) "
            "VALUES (?,?,?,?) RETURNING id", (meeting_id, question, closes_at, now()))
        pid = cur.lastrowid
        for label in options:
            db.execute("INSERT INTO poll_options (poll_id, label) VALUES (?,?)",
                       (pid, label))
        db.commit()
        flash("Poll created.", "ok")
        return redirect(url_for("polls"))
    meetings_list = get_db().execute(
        "SELECT id, title FROM meetings ORDER BY created_at DESC").fetchall()
    return render_template("new_poll.html", meetings=meetings_list)


@app.route("/polls/<int:poll_id>/vote", methods=["POST"])
@login_required
def vote(poll_id):
    db = get_db()
    poll = db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)).fetchone()
    if not poll:
        abort(404)
    if poll["is_closed"]:
        flash("This poll is closed.", "error")
        return redirect(request.referrer or url_for("polls"))
    option_id = request.form.get("option_id")
    opt = db.execute("SELECT * FROM poll_options WHERE id=? AND poll_id=?",
                     (option_id, poll_id)).fetchone()
    if not opt:
        flash("Please choose an option.", "error")
        return redirect(request.referrer or url_for("polls"))
    voter = session["email"]
    existing = db.execute("SELECT id FROM votes WHERE poll_id=? AND voter_email=?",
                          (poll_id, voter)).fetchone()
    if existing:
        db.execute("UPDATE votes SET option_id=?, created_at=? WHERE id=?",
                   (option_id, now(), existing["id"]))
    else:
        db.execute("INSERT INTO votes (poll_id, option_id, voter_email, created_at) "
                   "VALUES (?,?,?,?)", (poll_id, option_id, voter, now()))
    db.commit()
    flash("Your vote has been recorded.", "ok")
    return redirect(request.referrer or url_for("polls"))


@app.route("/polls/<int:poll_id>/close", methods=["POST"])
@director_required
def close_poll(poll_id):
    db = get_db()
    db.execute("UPDATE polls SET is_closed = 1 WHERE id = ?", (poll_id,))
    db.commit()
    flash("Poll closed.", "ok")
    return redirect(request.referrer or url_for("polls"))


# ---------------------------------------------------------------- boot
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
