"""Test-only stand-in for an OpenAI-compatible LLM (and a tiny RSS feed), so the
template can be tested end to end without a paid API key. Not part of the template."""
import json, os, re, time
from email.utils import formatdate
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CALLS = {"n": 0}


def answer(system, user):
    text = system + "\n" + user
    if '"tool_requests"' in text and "Return {\"tool_requests\": []}" in text:
        return {"tool_requests": []}
    m = re.search(r"Generate only block `([^`]+)`", text)
    if m:
        return {"title": "Stub briefing item", "block": {"id": m.group(1), "title": "Stub " + m.group(1),
                "content": "Stub content for " + m.group(1) + ".", "source_refs": []}}
    if "Generate only these blocks:" in text:
        ids = re.findall(r"^- `([^`]+)` required", text, re.M)
        return {"title": "Stub briefing item", "blocks": [
            {"id": i, "title": "Stub " + i, "content": "Stub content for " + i + ".", "source_refs": []} for i in ids]}
    if '"duplicates"' in text:
        return {"duplicates": []}
    if "Profile catalog" in text:
        return {"profile": "tech-news", "confidence": 0.9, "reason": "stub"}
    if '"score"' in text:
        return {"score": 8, "reason": "stub reason", "summary": "Stub one-sentence summary.", "tags": ["stub"]}
    return {}


def feed():
    now = time.time()
    items = "".join(
        f"<item><title>Stub story {i}</title><link>https://example.org/story-{i}</link>"
        f"<guid>https://example.org/story-{i}</guid><pubDate>{formatdate(now - i * 3600, usegmt=True)}</pubDate>"
        f"<description>Body of stub story {i} about open-source software.</description></item>" for i in range(1, 4))
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>Stub</title><link>https://example.org</link><description>stub</description>{items}</channel></rss>'


class H(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        b = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    def do_GET(self):
        if self.path.startswith("/feed.xml"):
            return self._send(200, feed(), "application/rss+xml")
        if self.path.startswith("/stats"):
            return self._send(200, json.dumps(CALLS), "application/json")
        return self._send(200, "stub ok", "text/plain")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n) or b"{}")
        msgs = req.get("messages", [])
        system = "\n".join(m.get("content", "") for m in msgs if m.get("role") == "system")
        user = "\n".join(m.get("content", "") for m in msgs if m.get("role") == "user")
        CALLS["n"] += 1
        content = json.dumps(answer(system, user))
        resp = {"id": "stub", "object": "chat.completion", "created": int(time.time()), "model": req.get("model"),
                "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}}
        self._send(200, json.dumps(resp), "application/json")


ThreadingHTTPServer(("::", int(os.environ.get("PORT", 9000))), H).serve_forever()
