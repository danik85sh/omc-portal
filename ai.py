"""
AI agenda analysis.

Each submitted report/message is analysed to produce:
  - a short one-line summary,
  - a category,
  - a suggested agenda discussion point, and
  - a priority.

Backends (set AI_PROVIDER):
  * "groq"   - free cloud API, OpenAI-compatible, no credit card (default).
  * "gemini" - Google Gemini free tier (Flash models).
  * "ollama" - local model on your own machine (free, private).
If the chosen provider is disabled or unreachable, a lightweight keyword-based
fallback is used so submissions always get an agenda point.
"""
import json
import os
import re
import requests

AI_ENABLED = os.environ.get("AI_ENABLED", "1") == "1"
AI_PROVIDER = os.environ.get("AI_PROVIDER", "groq").lower()

# Groq (https://console.groq.com) — OpenAI-compatible.
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

# Google Gemini (https://ai.google.dev).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Local Ollama.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")

CATEGORIES = [
    "Maintenance & Repairs",
    "Finance & Budget",
    "Health & Safety",
    "Common Areas",
    "Rules & Compliance",
    "Neighbour / Noise",
    "Other",
]

SYSTEM_PROMPT = (
    "You are an assistant for an Owners' Management Company (OMC). "
    "You receive a message from a property owner or director. "
    "Return ONLY a compact JSON object with these keys: "
    '"summary" (one sentence, max 20 words), '
    '"category" (one of: ' + ", ".join(CATEGORIES) + "), "
    '"agenda_point" (a clear, neutral discussion item for the next meeting, max 25 words), '
    '"priority" (one of: low, medium, high). '
    "Do not include any text outside the JSON."
)


def analyze(title: str, body: str) -> dict:
    """Return {summary, category, agenda_point, priority} for a message."""
    text = f"Subject: {title}\n\nMessage:\n{body}".strip()
    if AI_ENABLED:
        try:
            if AI_PROVIDER == "groq":
                data = _analyze_groq(text)
            elif AI_PROVIDER == "gemini":
                data = _analyze_gemini(text)
            elif AI_PROVIDER == "ollama":
                data = _analyze_ollama(text)
            else:
                data = None
            if data:
                return _normalize(data)
        except Exception as exc:  # noqa: BLE001 - any failure -> fallback
            print(f"[ai] {AI_PROVIDER} analysis failed ({exc}); using fallback.")
    return _analyze_fallback(title, body)


# ---- Groq (OpenAI-compatible chat completions) ----
def _analyze_groq(text: str) -> dict | None:
    if not GROQ_API_KEY:
        print("[ai] GROQ_API_KEY not set; using fallback.")
        return None
    resp = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    return json.loads(content)


# ---- Google Gemini ----
def _analyze_gemini(text: str) -> dict | None:
    if not GEMINI_API_KEY:
        print("[ai] GEMINI_API_KEY not set; using fallback.")
        return None
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    resp = requests.post(
        url,
        headers={"x-goog-api-key": GEMINI_API_KEY},
        json={
            "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
            },
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(content)


# ---- Local Ollama ----
def _analyze_ollama(text: str) -> dict | None:
    resp = requests.post(
        f"{OLLAMA_BASE_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "system": SYSTEM_PROMPT,
            "prompt": text,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.2},
        },
        timeout=60,
    )
    resp.raise_for_status()
    return json.loads(resp.json().get("response", ""))


def _normalize(data: dict) -> dict:
    category = data.get("category", "Other")
    if category not in CATEGORIES:
        category = "Other"
    priority = str(data.get("priority", "medium")).lower()
    if priority not in {"low", "medium", "high"}:
        priority = "medium"
    return {
        "summary": (data.get("summary") or "").strip()[:300] or "(no summary)",
        "category": category,
        "agenda_point": (data.get("agenda_point") or "").strip()[:300]
        or "Discuss owner submission.",
        "priority": priority,
    }


# ---- Keyword fallback (no LLM, fully offline) ----
_KEYWORDS = {
    "Maintenance & Repairs": ["repair", "broken", "leak", "lift", "elevator",
                               "fix", "damage", "maintenance", "boiler", "roof"],
    "Finance & Budget": ["budget", "fee", "fees", "service charge", "cost",
                          "invoice", "payment", "arrears", "money", "levy"],
    "Health & Safety": ["fire", "safety", "hazard", "alarm", "emergency",
                         "danger", "smoke", "security"],
    "Common Areas": ["garden", "hallway", "parking", "car park", "bin",
                     "lighting", "lobby", "stairwell", "communal"],
    "Rules & Compliance": ["rule", "policy", "compliance", "lease", "legal",
                           "regulation", "insurance"],
    "Neighbour / Noise": ["noise", "neighbour", "neighbor", "complaint",
                          "disturbance", "pet", "dog"],
}


def _analyze_fallback(title: str, body: str) -> dict:
    text = f"{title} {body}".lower()
    category = "Other"
    best = 0
    for cat, words in _KEYWORDS.items():
        hits = sum(1 for w in words if w in text)
        if hits > best:
            best, category = hits, cat
    first = re.split(r"(?<=[.!?])\s+", body.strip())[0] if body.strip() else title
    summary = (first or title).strip()
    if len(summary) > 140:
        summary = summary[:137] + "..."
    priority = "high" if any(w in text for w in
                             ["urgent", "fire", "danger", "emergency", "leak"]) else "medium"
    return {
        "summary": summary or "(no summary)",
        "category": category,
        "agenda_point": f"Discuss: {title}".strip()[:300],
        "priority": priority,
    }
