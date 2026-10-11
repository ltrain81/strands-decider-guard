#!/usr/bin/env python3
"""Run the policy console locally, without AWS or login (binds to 127.0.0.1 only).

  admin/dev_server.py [--port 8770] [--decider-url http://127.0.0.1:8000] [--home ~/.decider-guard]

The policy is saved to <home>/policy.json, which the hook's local mode (client/install.sh --local)
reads, so changes made here apply to the local agents immediately. Stats come from <home>/audit.log.
"""
import argparse
import http.server
import json
import os
import sys
import urllib.parse
import webbrowser

ROOT = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8770)
ap.add_argument("--decider-url", default="http://127.0.0.1:8000")
ap.add_argument("--home", default=os.environ.get("DECIDER_GUARD_HOME", os.path.expanduser("~/.decider-guard")))
ap.add_argument("--no-open", action="store_true")
args = ap.parse_args()

os.environ.update(POLICY_FILE=os.path.join(args.home, "policy.json"), LOCAL_DECIDER_URL=args.decider_url,
                  AUDIT_LOG=os.path.join(args.home, "audit.log"))
sys.path[:0] = [os.path.join(ROOT, "api"), os.path.join(ROOT, "..", "guard")]
import handler  # noqa: E402  (reads the env above at import)

WEB = os.path.join(ROOT, "web")
CONFIG = json.dumps({"mode": "local", "apiBase": ""}).encode()
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml"}


class H(http.server.BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _api(self, method):
        url = urllib.parse.urlsplit(self.path)
        body = self.rfile.read(int(self.headers.get("content-length") or 0)).decode() if method in ("PUT", "POST") else ""
        event = {"requestContext": {"http": {"method": method}}, "rawPath": url.path, "body": body,
                 "headers": {k.lower(): v for k, v in self.headers.items()},
                 "queryStringParameters": dict(urllib.parse.parse_qsl(url.query))}
        r = handler.handler(event)
        self._send(r["statusCode"], r["body"].encode())

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path.startswith("/api/"):
            return self._api("GET")
        if path == "/config.json":
            return self._send(200, CONFIG)
        name = "index.html" if path == "/" else path.lstrip("/")
        file = os.path.realpath(os.path.join(WEB, name))
        if file.startswith(os.path.realpath(WEB) + os.sep) and os.path.isfile(file):
            with open(file, "rb") as f:
                return self._send(200, f.read(), TYPES.get(os.path.splitext(file)[1], "application/octet-stream"))
        self._send(404, b"{}")

    def do_PUT(self):
        self._api("PUT")

    def do_POST(self):
        self._api("POST")

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    url = f"http://127.0.0.1:{args.port}"
    print(f"policy console: {url}   (policy file: {os.environ['POLICY_FILE']})")
    if not args.no_open:
        webbrowser.open(url)
    http.server.ThreadingHTTPServer(("127.0.0.1", args.port), H).serve_forever()
