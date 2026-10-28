"""SiteForge AI — local MVP. Run with python app.py."""
import io
import hmac
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta
import re
import uuid
import zipfile
from pathlib import Path
from flask import Flask, jsonify, request, send_file, send_from_directory
import requests

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "generated"
OUTPUT.mkdir(exist_ok=True)
app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 24 * 1024
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
DB = ROOT / "siteforge.db"
REMOTE_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
REMOTE_MODEL = os.getenv("OPENROUTER_MODEL", "").strip()
ACCESS_CODE = os.getenv("SITEFORGE_TEST_PASSWORD", "").strip()
IS_RENDER = os.getenv("RENDER", "").lower() == "true"

def test_access_ok():
    if not IS_RENDER:
        return True
    if not ACCESS_CODE:
        return False
    return hmac.compare_digest(request.headers.get("X-SiteForge-Access", ""), ACCESS_CODE)

quota_lock = threading.Lock()
PLANS = {"free": {"name": "Free", "price_usd": 0, "generations": 1},
         "starter": {"name": "Starter", "price_usd": 15, "generations": 20},
         "pro": {"name": "Pro", "price_usd": 30, "generations": None}}

def db_connect():
    con = sqlite3.connect(DB, timeout=10)
    con.execute("CREATE TABLE IF NOT EXISTS generations (id INTEGER PRIMARY KEY, created_at TEXT NOT NULL)")
    return con

def usage():
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    with db_connect() as con:
        used = con.execute("SELECT COUNT(*) FROM generations WHERE created_at >= ?", (since,)).fetchone()[0]
    return used

@app.get("/api/plans")
def plans():
    return jsonify(plans=PLANS, active_plan="free", used=usage(),
                   period="rolling 30 days", checkout_enabled=False,
                   notice="Paid plans are previews only. No payment integration is configured.")

@app.post("/api/checkout/<plan>")
def checkout(plan):
    if plan not in {"starter", "pro"}:
        return jsonify(error="Invalid paid plan."), 400
    return jsonify(error="Payments are not enabled. An eligible adult must set up an authorized payment provider before launch."), 503


@app.get("/")
def home():
    return send_from_directory(ROOT / "static", "index.html")

@app.get("/api/status")
def status():
    if REMOTE_KEY and REMOTE_MODEL:
        return jsonify(online=True, model=REMOTE_MODEL, available=True, provider="hosted", note="API configured; generation not yet tested")
    if IS_RENDER:
        return jsonify(online=False, model="Not configured", available=False, provider="hosted")
    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        response.raise_for_status()
        models = [m.get("name", "") for m in response.json().get("models", [])]
        return jsonify(online=True, model=MODEL, available=any(n == MODEL or n.startswith(MODEL + ":") for n in models))
    except requests.RequestException:
        return jsonify(online=False, model=MODEL, available=False)

def extract_files(raw):
    """Accept JSON reply, optionally fenced, with index.html, style.css, script.js."""
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, re.S)
        if not match:
            raise ValueError("Model did not return valid JSON. Try generating again.")
        parsed = json.loads(match.group())
    files = {key: parsed.get(key, "") for key in ("index.html", "style.css", "script.js")}
    if not isinstance(files["index.html"], str) or "<html" not in files["index.html"].lower():
        raise ValueError("Model did not return a valid HTML page. Try again.")
    if any(not isinstance(v, str) for v in files.values()):
        raise ValueError("Generated files had an invalid format.")
    return files

@app.post("/api/generate")
def generate():
    payload = request.get_json(silent=True) or {}
    description = str(payload.get("description", "")).strip()
    theme = str(payload.get("theme", "modern"))[:40]
    if len(description) < 12 or len(description) > 1600:
        return jsonify(error="Please describe your website (12–1600 characters)."), 400
    if theme not in {"modern", "luxury", "playful", "minimal"}:
        theme = "modern"
    if not test_access_ok():
        return jsonify(error="Private testing access required. Configure SITEFORGE_TEST_PASSWORD in Render."), 403
    if IS_RENDER and not (REMOTE_KEY and REMOTE_MODEL):
        return jsonify(error="Hosted AI is not configured in Render yet."), 503
    with quota_lock:
        if usage() >= PLANS["free"]["generations"]:
            return jsonify(error="Free plan limit reached (1 successful website per 30 days). Paid plans are not yet available."), 403
    instructions = (
        "You create polished, functional, single-page static websites. "
        "Respond ONLY with a JSON object whose EXACT keys are 'index.html', 'style.css', 'script.js'. "
        "Do not use Markdown fences or preambles. index.html must have a full <!DOCTYPE html>, "
        "<html lang='en'>, semantic sections, mobile viewport, a link to style.css and a script tag "
        "for script.js. Use original English copy, responsive accessible layouts, polished typography, "
        "CSS gradients and simple CSS geometry instead of external images. No remote CDN scripts, "
        "no external APIs, and no forms pretending to submit successfully. Buttons and navigation "
        "must work (use section links). Include clear demo labeling for fictional details. "
        "Generate all three files as strings, no more than about 10000 characters total."
    )
    try:
        messages = [
            {"role": "system", "content": instructions},
            {"role": "user", "content": f"Build a {theme} website for this brief:\n{description}"},
        ]
        if REMOTE_KEY and REMOTE_MODEL:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {REMOTE_KEY}", "Content-Type": "application/json"},
                json={"model": REMOTE_MODEL, "stream": False, "temperature": 0.65,
                      "max_tokens": 6500, "messages": messages}, timeout=180)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("The hosted model did not return text content")
        else:
            response = requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": MODEL, "stream": False, "format": "json",
                "options": {"temperature": 0.65, "num_predict": 4500},
                "messages": messages,
            }, timeout=240)
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
        files = extract_files(content)
        project_id = uuid.uuid4().hex[:12]
        directory = OUTPUT / project_id
        directory.mkdir()
        for filename, content in files.items():
            (directory / filename).write_text(content, encoding="utf-8")
        with quota_lock:
            with db_connect() as con:
                con.execute("INSERT INTO generations(created_at) VALUES (?)", (datetime.now(timezone.utc).isoformat(),))
        return jsonify(id=project_id, html=files["index.html"], css=files["style.css"], js=files["script.js"])
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        return jsonify(error=f"Generation failed: {str(exc)[:240]}"), 502

@app.get("/api/download/<project_id>")
def download(project_id):
    if not test_access_ok():
        return jsonify(error="Private test access required."), 403
    if not re.fullmatch(r"[a-f0-9]{12}", project_id):
        return jsonify(error="Invalid project ID."), 400
    directory = OUTPUT / project_id
    if not directory.is_dir():
        return jsonify(error="Project not found."), 404
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("index.html", "style.css", "script.js"):
            archive.write(directory / name, arcname=name)
        archive.writestr("README.txt", "SiteForge AI generated website\nUnzip and open index.html.\nReview all content before publishing.\n")
    memory.seek(0)
    return send_file(memory, as_attachment=True, download_name=f"siteforge-{project_id}.zip", mimetype="application/zip")

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
