"""Railway wrapper for Horizon: a small password-protected web UI plus a daily scheduler.

Horizon itself is a run-once CLI (`horizon`) that writes Markdown briefings to
<data>/summaries. This process keeps the container alive, runs Horizon once a day
(HORIZON_RUN_AT, UTC), lets you start a run, edit data/config.json and read the
briefings in a browser, and answers /healthz for Railway's health check.
Standard library only, plus `markdown` (already a Horizon dependency).
"""
import base64
import datetime as dt
import hashlib
import hmac
import html
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import markdown

APP = Path("/app")
DATA = Path(os.environ.get("HORIZON_DATA_DIR", "/app/data"))
SUMMARIES = DATA / "summaries"
LOGS = DATA / "logs"
STATE = DATA / "railway-state.json"
CONFIG = DATA / "config.json"
PASSWORD = os.environ["HORIZON_PASSWORD"]
USERNAME = os.environ.get("HORIZON_USERNAME") or "admin"
PORT = int(os.environ.get("PORT") or 8080)
RUN_TIMEOUT = int(os.environ.get("HORIZON_RUN_TIMEOUT_SECONDS") or 7200)
COMMIT = (APP / "HORIZON_COMMIT").read_text().strip() if (APP / "HORIZON_COMMIT").exists() else "?"

# Defaults for the ${VAR} references in the template's config.json.
# An empty LLM_MODEL picks a sensible model for the chosen provider.
MODEL_DEFAULTS = {
    "openai": "gpt-4.1-mini", "anthropic": "claude-sonnet-5-5", "gemini": "gemini-2.5-flash",
    "deepseek": "deepseek-chat", "ali": "qwen-plus", "doubao": "doubao-pro-32k",
    "minimax": "MiniMax-M3.1-Flash", "ollama": "llama3.1",
}
os.environ["LLM_PROVIDER"] = (os.environ.get("LLM_PROVIDER") or "openai").strip().lower()
if not (os.environ.get("LLM_MODEL") or "").strip():
    os.environ["LLM_MODEL"] = MODEL_DEFAULTS.get(os.environ["LLM_PROVIDER"], "gpt-4.1-mini")
os.environ["LLM_BASE_URL"] = (os.environ.get("LLM_BASE_URL") or "").strip()

CSRF = hmac.new(PASSWORD.encode(), b"horizon-railway-csrf", hashlib.sha256).hexdigest()
lock = threading.Lock()
status = {"running": False, "started": None, "pid": None}


def log(msg):
    print(f"[horizon-railway] {dt.datetime.utcnow():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(s):
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.replace(STATE)


def run_at():
    raw = (os.environ.get("HORIZON_RUN_AT") or "07:00").strip()
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", raw)
    if not m:
        log(f"HORIZON_RUN_AT={raw!r} is not HH:MM; using 07:00")
        return 7, 0
    return int(m.group(1)), int(m.group(2))


def next_run(now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    h, m = run_at()
    t = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return t if t > now else t + dt.timedelta(days=1)


def run_horizon(reason):
    """Run the upstream CLI once. Returns False if a run is already going."""
    if not lock.acquire(blocking=False):
        return False
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc)
        logfile = LOGS / f"run-{stamp:%Y%m%d-%H%M%S}.log"
        status.update(running=True, started=stamp.isoformat(timespec="seconds"))
        log(f"run started ({reason}), log {logfile.name}")
        env = dict(os.environ, COLUMNS="120", TERM="dumb", NO_COLOR="1")
        with open(logfile, "w") as out:
            try:
                p = subprocess.Popen(
                    [str(APP / ".venv/bin/horizon"), "--data-dir", str(DATA), "--log-level", "INFO"],
                    cwd=str(APP), env=env, stdout=out, stderr=subprocess.STDOUT,
                )
                status["pid"] = p.pid
                rc = p.wait(timeout=RUN_TIMEOUT)
            except subprocess.TimeoutExpired:
                p.kill()
                p.wait()
                rc = "timeout"
        # Mirror the run log into Railway's log stream.
        tail = logfile.read_text(errors="replace")[-6000:]
        for line in tail.splitlines():
            print(f"[horizon] {line}", flush=True)
        st = load_state()
        st.update(last_run=stamp.isoformat(timespec="seconds"), last_exit=rc,
                  last_log=logfile.name, last_reason=reason)
        save_state(st)
        log(f"run finished ({reason}): exit {rc}")
        # Keep the 60 newest run logs.
        for old in sorted(LOGS.glob("run-*.log"))[:-60]:
            old.unlink(missing_ok=True)
        return True
    finally:
        status.update(running=False, pid=None)
        lock.release()


def scheduler():
    try:
        st = load_state()
        first = (os.environ.get("HORIZON_RUN_ON_FIRST_BOOT") or "true").lower() in ("1", "true", "yes")
        if first and not st.get("first_run_done"):
            st["first_run_done"] = True
            save_state(st)
            run_horizon("first boot")
        while True:
            target = next_run()
            log(f"next scheduled run {target:%Y-%m-%d %H:%M} UTC")
            while dt.datetime.now(dt.timezone.utc) < target:
                time.sleep(min(60, max(1, (target - dt.datetime.now(dt.timezone.utc)).total_seconds())))
            if not run_horizon("schedule"):
                log("scheduled run skipped: a run is already going")
    except Exception:
        traceback.print_exc()
        log("scheduler crashed; exiting so Railway restarts the service")
        os._exit(1)


def validate_config(text):
    """Validate a config.json candidate with Horizon's own loader. Returns an error or None."""
    try:
        json.loads(text)
    except json.JSONDecodeError as e:
        return f"Invalid JSON: {e}"
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "config.json"
        p.write_text(text)
        code = ("import sys; sys.path.insert(0, '/app');"
                "from src.storage.manager import StorageManager as S;"
                "S(data_dir=sys.argv[1]).load_config()")
        r = subprocess.run([str(APP / ".venv/bin/python"), "-c", code, d], cwd=str(APP),
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            return (r.stderr or r.stdout).strip().splitlines()[-1][:2000] if (r.stderr or r.stdout) else "invalid config"
    return None


CSS = """body{font-family:system-ui,sans-serif;max-width:920px;margin:2rem auto;padding:0 1rem;line-height:1.55;color:#1f2937}
a{color:#be185d}header{display:flex;gap:1rem;align-items:center;flex-wrap:wrap;border-bottom:2px solid #f97316;padding-bottom:.5rem;margin-bottom:1rem}
header h1{margin:0;font-size:1.4rem}nav a{margin-right:.8rem}.muted{color:#6b7280;font-size:.9rem}
textarea{width:100%;height:60vh;font-family:monospace;font-size:.85rem}pre{white-space:pre-wrap;background:#f3f4f6;padding:1rem;overflow:auto;font-size:.8rem}
button{background:#be185d;color:#fff;border:0;padding:.45rem 1rem;border-radius:4px;cursor:pointer}.err{color:#b91c1c}.ok{color:#15803d}
li{margin:.25rem 0}code{background:#f3f4f6;padding:0 .2rem}"""


def page(title, body):
    st = load_state()
    last = st.get("last_run")
    info = ("running now" if status["running"] else
            f"last run {html.escape(str(last))} UTC, exit {html.escape(str(st.get('last_exit')))}" if last else "no run yet")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} - Horizon</title><style>{CSS}</style></head><body>
<header><h1>🌅 Horizon</h1><nav><a href="/">Briefings</a><a href="/config">Config</a><a href="/logs">Run log</a></nav>
<span class="muted">{info} · next {next_run():%Y-%m-%d %H:%M} UTC</span></header>{body}
<p class="muted">Horizon <a href="https://github.com/Thysrael/Horizon/commit/{COMMIT}">{COMMIT[:7]}</a> ·
<a href="https://github.com/aalfath/horizon-railway-template">Railway template</a></p></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "horizon-railway"

    def log_message(self, fmt, *args):
        if not self.path.startswith("/healthz"):
            sys.stderr.write("[http] %s %s\n" % (self.address_string(), fmt % args))

    def send(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        # Briefings contain text from the open web: never let it run scripts.
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; style-src 'unsafe-inline'; img-src https: data:; form-action 'self'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def authed(self):
        h = self.headers.get("Authorization", "")
        if h.startswith("Basic "):
            try:
                user, _, pw = base64.b64decode(h[6:]).decode().partition(":")
                if hmac.compare_digest(user.encode(), USERNAME.encode()) and hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                    return True
            except Exception:
                pass
        self.send(401, "Login required", "text/plain", {"WWW-Authenticate": 'Basic realm="Horizon", charset="UTF-8"'})
        return False

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/healthz":
            return self.send(200, "ok", "text/plain")
        if not self.authed():
            return
        if path == "/":
            files = sorted(SUMMARIES.glob("*.md"), reverse=True)
            items = "".join(f'<li><a href="/summary/{urllib.parse.quote(f.name)}">{html.escape(f.stem)}</a></li>' for f in files[:200])
            body = f"""<form method="post" action="/run"><input type="hidden" name="csrf" value="{CSRF}">
<button>Run Horizon now</button> <span class="muted">collects the last 24 h, scores it with your LLM and writes a new briefing (a few minutes)</span></form>
<h2>Briefings</h2>{'<ul>' + items + '</ul>' if items else '<p>No briefing yet. The first run starts on first boot; check the run log.</p>'}"""
            return self.send(200, page("Briefings", body))
        if path.startswith("/summary/"):
            name = urllib.parse.unquote(path[len("/summary/"):])
            f = SUMMARIES / name
            if "/" in name or not name.endswith(".md") or not f.is_file():
                return self.send(404, page("Not found", "<p>Not found.</p>"))
            text = f.read_text(errors="replace")
            if self.headers.get("Accept", "").startswith("text/markdown") or "raw=1" in self.path:
                return self.send(200, text, "text/markdown; charset=utf-8")
            body = markdown.markdown(text, extensions=["extra", "sane_lists"])
            return self.send(200, page(f.stem, body + f'<p><a href="/summary/{urllib.parse.quote(name)}?raw=1">Markdown</a></p>'))
        if path == "/config":
            msg = ""
            q = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
            if "saved" in q:
                msg = '<p class="ok">Saved. The next run uses it.</p>'
            return self.send(200, page("Config", self.config_form(CONFIG.read_text(), msg)))
        if path == "/logs":
            st = load_state()
            logs = sorted(LOGS.glob("run-*.log"))
            text = logs[-1].read_text(errors="replace")[-30000:] if logs else "No run yet."
            name = logs[-1].name if logs else ""
            return self.send(200, page("Run log", f"<h2>{html.escape(name)}</h2><pre>{html.escape(text)}</pre>"))
        return self.send(404, page("Not found", "<p>Not found.</p>"))

    def config_form(self, text, msg):
        return f"""<h2>config.json</h2>{msg}<p class="muted">Sources, scoring thresholds and the LLM settings. See
<a href="https://github.com/Thysrael/Horizon/blob/{COMMIT}/docs/configuration.md">Horizon's configuration guide</a>.
<code>${{VAR}}</code> values come from Railway variables (<code>LLM_PROVIDER</code>, <code>LLM_MODEL</code>, <code>LLM_BASE_URL</code>, key in <code>LLM_API_KEY</code>).</p>
<form method="post" action="/config"><input type="hidden" name="csrf" value="{CSRF}">
<textarea name="config" spellcheck="false">{html.escape(text)}</textarea><p><button>Validate and save</button></p></form>"""

    def form(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            return None
        return urllib.parse.parse_qs(self.rfile.read(n).decode(errors="replace"), keep_blank_values=True)

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        if not self.authed():
            return
        f = self.form()
        if f is None or not hmac.compare_digest((f.get("csrf") or [""])[0], CSRF):
            return self.send(403, page("Forbidden", "<p>Bad form token. Reload the page and try again.</p>"))
        if path == "/run":
            if status["running"]:
                return self.send(303, "", headers={"Location": "/logs"})
            threading.Thread(target=run_horizon, args=("web",), daemon=True).start()
            time.sleep(0.5)
            return self.send(303, "", headers={"Location": "/logs"})
        if path == "/config":
            text = (f.get("config") or [""])[0].replace("\r\n", "\n")
            err = validate_config(text)
            if err:
                return self.send(400, page("Config", self.config_form(text, f'<p class="err">Not saved: {html.escape(err)}</p>')))
            if CONFIG.exists():
                CONFIG.with_suffix(".json.bak").write_text(CONFIG.read_text())
            tmp = CONFIG.with_suffix(".tmp")
            tmp.write_text(text if text.endswith("\n") else text + "\n")
            tmp.replace(CONFIG)
            return self.send(303, "", headers={"Location": "/config?saved=1"})
        return self.send(404, page("Not found", "<p>Not found.</p>"))


def main():
    SUMMARIES.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    if not os.environ.get("LLM_API_KEY") and os.environ["LLM_PROVIDER"] != "ollama":
        log("LLM_API_KEY is empty: runs will fail until you set it in Railway's Variables tab.")
    httpd = ThreadingHTTPServer(("::", PORT), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=scheduler, name="scheduler", daemon=True).start()
    log(f"Horizon {COMMIT[:7]} web UI on port {PORT}, user {USERNAME!r}")
    try:
        httpd.serve_forever()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    sys.exit(1)  # serve_forever never returns normally; a return is an unexpected stop


if __name__ == "__main__":
    main()
