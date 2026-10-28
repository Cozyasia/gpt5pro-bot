#!/usr/bin/env python3
"""NEYRONIX isolated staging readiness probe.

No webhook, polling, message sends, local Bot API logOut, production DB access,
or payment calls. Checks token identity using Telegram getMe and exposes /healthz.
Run with: python -u ops/neyronix_staging_probe.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

EXPECTED = os.getenv("BOT_USERNAME", "neyronixbot").lstrip("@").lower()
TOKEN = os.getenv("BOT_TOKEN", "")
PORT = int(os.getenv("PORT", "10000"))

def check_identity():
    if not TOKEN:
        return False, "BOT_TOKEN missing"
    req = urllib.request.Request(
        "https://api.telegram.org/bot" + TOKEN + "/getMe",
        headers={"User-Agent": "NEYRONIX-staging-probe/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.load(response)
        actual = str(data.get("result", {}).get("username", "")).lower()
        if data.get("ok") and actual == EXPECTED:
            return True, "Verified @" + actual
        return False, "Bot identity mismatch (expected @" + EXPECTED + ")"
    except Exception as exc:
        # Never include exception text: some errors contain the token URL.
        return False, "Telegram API check failed: " + type(exc).__name__

ready, message = check_identity()
print("NEYRONIX staging probe: " + message, flush=True)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/healthz", "/"):
            self.send_error(404)
            return
        body = json.dumps({"ready": ready, "bot": EXPECTED if ready else None}).encode()
        self.send_response(200 if ready else 503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, fmt, *args):
        pass

ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
