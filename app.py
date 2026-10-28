"""SiteForge AI — local MVP. Run with python app.py."""
import io
import logging
import time
from html.parser import HTMLParser
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
from flask import Flask, jsonify, request, send_file, send_from_directory, session
import requests
from requests.exceptions import Timeout, RequestException
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import func
from functools import wraps
import secrets

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("siteforge")

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "generated"
OUTPUT.mkdir(exist_ok=True)
app = Flask(__name__, static_folder="static")
app.config["MAX_CONTENT_LENGTH"] = 24 * 1024
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "")
app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv("DATABASE_URL", "sqlite:///siteforge-beta.db").replace("postgres://", "postgresql://", 1)
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("RENDER", "").lower() == "true"
db = SQLAlchemy(app)
migrate = Migrate(app, db)

class User(db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(254), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(300), nullable=False)
    plan = db.Column(db.String(20), nullable=False, default="free")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

class UserGeneration(db.Model):
    __tablename__ = "user_generations"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=func.now())

def current_user():
    uid = session.get("user_id")
    return db.session.get(User, uid) if isinstance(uid, int) else None

def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]

@app.before_request
def protect_requests():
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        if request.path == "/api/checkout/starter" or request.path == "/api/checkout/pro":
            return None
        if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), session.get("csrf", "not-set")):
            return jsonify(error="Your session expired. Refresh the page and try again."), 403

@app.after_request
def secure_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return response

@app.get("/api/auth/csrf")
def auth_csrf():
    return jsonify(csrf_token=csrf_token())

@app.get("/api/auth/me")
def auth_me():
    u = current_user()
    if not u:
        return jsonify(authenticated=False, csrf_token=csrf_token())
    return jsonify(authenticated=True, email=u.email, plan=u.plan, csrf_token=csrf_token())

def valid_credentials(body):
    email = str(body.get("email", "")).strip().lower()
    password = body.get("password", "")
    return email, password if isinstance(password, str) else ""

@app.post("/api/auth/register")
def auth_register():
    body = request.get_json(silent=True) or {}
    if not test_access_ok():
        return jsonify(error="Private beta invitation required."), 403
    email, password = valid_credentials(body)
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) or not 12 <= len(password) <= 128:
        return jsonify(error="Enter a valid email and password of at least 12 characters."), 400
    if User.query.filter_by(email=email).first():
        return jsonify(error="This email is already registered."), 409
    user = User(email=email, password_hash=generate_password_hash(password, method="scrypt"))
    db.session.add(user)
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify(error="Could not create account. Try again."), 409
    session.clear()
    session["user_id"] = user.id
    return jsonify(ok=True, email=user.email, csrf_token=csrf_token()), 201

@app.post("/api/auth/login")
def auth_login():
    body = request.get_json(silent=True) or {}
    email, password = valid_credentials(body)
    user = User.query.filter_by(email=email).first() if email else None
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify(error="Incorrect email or password."), 401
    session.clear()
    session["user_id"] = user.id
    return jsonify(ok=True, email=user.email, csrf_token=csrf_token())

@app.post("/api/auth/logout")
def auth_logout():
    session.clear()
    return jsonify(ok=True)

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not current_user():
            return jsonify(error="Sign in to create or download websites."), 401
        return fn(*args, **kwargs)
    return wrapped

def user_usage(uid):
    since = datetime.now(timezone.utc) - timedelta(days=30)
    return UserGeneration.query.filter(UserGeneration.user_id == uid, UserGeneration.created_at >= since).count()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
MODEL = os.getenv("OLLAMA_MODEL", "qwen3:8b")
DB = ROOT / "siteforge.db"
REMOTE_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
REMOTE_MODEL = os.getenv("OPENROUTER_MODEL", "").strip()
FALLBACK_MODEL = os.getenv("OPENROUTER_FALLBACK_MODEL", "").strip()
REMOTE_TIMEOUT = min(95, max(10, int(os.getenv("OPENROUTER_TIMEOUT", "80"))))
REMOTE_MAX_TOKENS = min(16000, max(1000, int(os.getenv("OPENROUTER_MAX_TOKENS", "10000"))))
ACCESS_CODE = os.getenv("SITEFORGE_TEST_PASSWORD", "").strip()
IS_RENDER = os.getenv("RENDER", "").lower() == "true"

def test_access_ok():
    if not IS_RENDER:
        return True
    if not ACCESS_CODE:
        return False
    return hmac.compare_digest(request.headers.get("X-SiteForge-Access", ""), ACCESS_CODE)

quota_lock = threading.Lock()
project_owners = {}
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
    u = current_user()
    return jsonify(plans=PLANS, active_plan=u.plan if u else "free", used=user_usage(u.id) if u else 0,
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
    if not isinstance(raw, str):
        raise ValueError("Model returned an invalid format.")
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

class GenerationError(Exception):
    """Safe public failure; details remain in logs."""
    def __init__(self, message, status=502, retryable=False):
        super().__init__(message)
        self.status = status
        self.retryable = retryable


class HTMLCleaner(HTMLParser):
    """Conservative filter: remove dangerous HTML elements and event handlers.

    This is defense-in-depth, NOT a guarantee that arbitrary generated JavaScript
    is safe. Preview runs in an opaque-origin sandbox; never publish unreviewed code.
    """
    forbidden = {"iframe", "object", "embed", "base", "meta", "form", "input", "button", "textarea", "select", "link"}
    void = {"area", "br", "hr", "img", "source", "wbr", "col", "link", "meta", "input", "embed", "base"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.output = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if self.skip:
            if tag in self.forbidden or tag == "script": self.skip += 1
            return
        if tag in self.forbidden or tag == "script":
            if tag not in self.void: self.skip = 1
            return
        safe = []
        for name, value in attrs:
            if not name or name.lower().startswith("on") or name.lower() in {"srcdoc", "formaction"}: continue
            if name.lower() in {"href", "src", "action", "poster", "xlink:href"}:
                value = (value or "").strip()
                if value.lower().startswith(("javascript:", "data:", "vbscript:", "//")) or (value and not value.startswith(("#", "./", "/"))): continue
            if name.lower() == "style" and ("url(" in (value or "").lower() or "expression(" in (value or "").lower()): continue
            from html import escape
            safe.append(f' {name}="{escape(value or "", quote=True)}"')
        self.output.append(f'<{tag}{"".join(safe)}>')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if self.skip:
            if tag in self.forbidden or tag == "script": self.skip -= 1
            return
        if tag not in self.forbidden and tag != "script" and tag not in self.void:
            self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip: self.output.append(data)

    def handle_entityref(self, name):
        if not self.skip: self.output.append(f"&{name};")

    def handle_charref(self, name):
        if not self.skip: self.output.append(f"&#{name};")

    def handle_decl(self, decl):
        if not self.skip: self.output.append(f"<!{decl}>")


def sanitize_files(files):
    clean = HTMLCleaner()
    clean.feed(files["index.html"])
    clean.close()
    files["index.html"] = "".join(clean.output)
    if "<html" not in files["index.html"].lower():
        raise GenerationError("The AI produced invalid HTML. Please try again.")
    # CSS should not load external assets; remove imports and CSS URLs.
    files["style.css"] = re.sub(r"@import\s+[^;]+;", "", files["style.css"], flags=re.I)
    files["style.css"] = re.sub(r"url\s*\([^)]*\)", "none", files["style.css"], flags=re.I)
    return files


def parse_remote_reply(response):
    if "json" not in response.headers.get("Content-Type", "").lower():
        raise GenerationError("The AI provider returned an unexpected response. Try again.", retryable=response.status_code >= 500)
    try:
        body = response.json()
    except ValueError:
        raise GenerationError("The AI provider returned invalid JSON.", retryable=True)
    if not isinstance(body, dict):
        raise GenerationError("Unexpected AI provider response.", retryable=True)
    if response.status_code >= 400 or body.get("error"):
        err = body.get("error") or {}
        code = response.status_code
        logger.warning("OpenRouter error status=%s code=%s", code, err.get("code") if isinstance(err, dict) else "unknown")
        if code in (401, 403): raise GenerationError("AI provider access failed. Check the API credentials.", 503)
        if code == 402: raise GenerationError("AI provider credits are unavailable.", 503)
        if code == 429: raise GenerationError("The AI provider is busy or rate-limited. Try again later.", 503, True)
        raise GenerationError("The AI provider could not complete this request.", 502, code >= 500)
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise GenerationError("The AI provider did not return a valid generation.", retryable=True)
    choice = choices[0]
    reason = choice.get("finish_reason")
    if reason == "length":
        logger.warning("OpenRouter truncated output finish_reason=length completion_tokens=%s",
                       (body.get("usage") or {}).get("completion_tokens"))
        raise GenerationError("The AI stopped before finishing the website. Try another model or a smaller design.", retryable=True)
    if reason in {"content_filter", "error"}:
        raise GenerationError("The AI provider could not finish the request.")
    message = choice.get("message") or {}
    if not isinstance(message, dict):
        raise GenerationError("The AI provider returned an invalid message.", retryable=True)
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text")
    if not isinstance(content, str) or not content.strip():
        # Reasoning is NOT valid website code; never substitute it for content.
        logger.warning("OpenRouter empty content finish_reason=%s reasoning_present=%s", reason, bool(message.get("reasoning")))
        raise GenerationError("The AI returned no website code. Try another model.", retryable=True)
    return content


def hosted_generation(messages):
    models = list(dict.fromkeys([m for m in (REMOTE_MODEL, FALLBACK_MODEL) if m]))
    last_error = GenerationError("No AI model configured.", 503)
    for i, model in enumerate(models):
        try:
            response = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={"Authorization": f"Bearer {REMOTE_KEY}", "Content-Type": "application/json"},
                json={"model": model, "stream": False, "temperature": 0.5,
                      "max_tokens": REMOTE_MAX_TOKENS, "messages": messages},
                timeout=(8, REMOTE_TIMEOUT),
            )
            return parse_remote_reply(response)
        except Timeout:
            last_error = GenerationError("The AI took too long to respond. Please retry.", 504, True)
            logger.warning("OpenRouter timed out model=%s", model)
        except RequestException as exc:
            last_error = GenerationError("The AI provider is temporarily unreachable.", 502, True)
            logger.warning("OpenRouter connection error: %s", type(exc).__name__)
        except GenerationError as exc:
            last_error = exc
            logger.warning("Generation failure model=%s status=%s", model, exc.status)
        if not last_error.retryable: break
        if i < len(models) - 1: time.sleep(1)
    raise last_error


@app.post("/api/generate")
@login_required
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
    user = current_user()
    # Private beta: no paid entitlements until payment validation exists.
    if user_usage(user.id) >= 1:
        return jsonify(error="Your Free beta quota is used (1 website per rolling 30 days)."), 403
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
            content = hosted_generation(messages)
        else:
            response = requests.post(f"{OLLAMA_URL}/api/chat", json={
                "model": MODEL, "stream": False, "format": "json",
                "options": {"temperature": 0.65, "num_predict": 4500},
                "messages": messages,
            }, timeout=(8, 120))
            response.raise_for_status()
            content = response.json().get("message", {}).get("content", "")
        files = sanitize_files(extract_files(content))
        project_id = uuid.uuid4().hex[:12]
        directory = OUTPUT / project_id
        directory.mkdir()
        project_owners[project_id] = user.id
        for filename, content in files.items():
            (directory / filename).write_text(content, encoding="utf-8")
        db.session.add(UserGeneration(user_id=user.id))
        db.session.commit()
        return jsonify(id=project_id, html=files["index.html"], css=files["style.css"], js=files["script.js"])
    except GenerationError as exc:
        return jsonify(error=str(exc)), exc.status
    except (requests.RequestException, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Generation failed type=%s", type(exc).__name__)
        return jsonify(error="Generation failed. Try a shorter prompt or another model."), 502
    except Exception:
        logger.exception("Unexpected generation failure")
        return jsonify(error="The generation service encountered an error. Please try again."), 500

@app.get("/api/download/<project_id>")
@login_required
def download(project_id):
    if not test_access_ok():
        return jsonify(error="Private test access required."), 403
    if not re.fullmatch(r"[a-f0-9]{12}", project_id):
        return jsonify(error="Invalid project ID."), 400
    if project_owners.get(project_id) != current_user().id:
        return jsonify(error="Project not found."), 404
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