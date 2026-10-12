#!/usr/bin/env python3
"""Offline tests for the sign-in path (no AWS, no model): python3 -I tests/test_signin.py

- GuardApi: POST /guard/check as API Gateway delivers it (payload v2, JWT already verified by the authorizer).
- SignIn: browser sign-in (authorization code + PKCE, loopback redirect) and the "api" hook backend, against a fake
  OIDC provider and a fake API Gateway that runs the real guard Lambda handler. The model is unreachable on purpose,
  so verdicts come from the regex fallback.
"""
import base64
import hashlib
import http.server
import importlib
import io
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "guard"), os.path.join(ROOT, "client")]
os.environ.setdefault("DECIDER_URL", "http://127.0.0.1:9")   # nothing listens: regex-only verdicts
import guard_core as g  # noqa: E402
import lambda_handler as lh  # noqa: E402

RRN = "-".join(["900101", "1234567"])                      # synthetic resident number
MAIL = lambda user: "@".join([user, "example.com"])         # synthetic address


def b64(d):
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def claims_of(jwt):
    part = jwt.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))


def quiet_handler(event):
    with redirect_stdout(io.StringIO()) as buf:
        resp = lh.handler(event, None)
    return resp, [json.loads(l) for l in buf.getvalue().splitlines() if l.startswith("{")]


class GuardApi(unittest.TestCase):
    def call(self, body, raw=None):
        ev = {"requestContext": {"http": {"method": "POST"}, "authorizer": {"jwt": {"claims": {"email": MAIL("dev")}}}},
              "body": raw if raw is not None else json.dumps(body)}
        resp, logs = quiet_handler(ev)
        return resp["statusCode"], json.loads(resp["body"]), logs

    def test_check_logs_the_signed_in_user(self):
        status, out, logs = self.call({"items": [{"source": "prompt", "text": "id " + RRN}], "client": "claude", "user": "forged"})
        self.assertEqual((status, out["decision"]), (200, "block"))
        self.assertEqual((logs[-1]["user"], logs[-1]["client"]), (MAIL("dev"), "claude"))   # from the token, not the body

    def test_draft_policies_are_refused_and_bad_input_rejected(self):
        draft = {"categories": {"resident_id": "allow"}}
        status, out, logs = self.call({"items": [{"source": "prompt", "text": "id " + RRN}], "policy": draft, "dry_run": True})
        self.assertEqual((status, out["decision"], len(logs)), (200, "block", 1))   # saved policy, logged like any check
        self.assertEqual(self.call({"items": "nope"})[0], 400)
        self.assertEqual(self.call(None, raw="{not json")[0], 400)
        self.assertEqual(self.call(None, raw="x" * 2_000_001)[0], 413)

    def test_user_source_tells_verified_from_reported(self):
        _, logs = quiet_handler({"items": [{"source": "prompt", "text": "hello"}], "user": "litellm-key-user"})
        self.assertEqual((logs[-1]["user"], logs[-1]["user_source"]), ("litellm-key-user", "caller"))   # IAM caller's word
        _, logs = quiet_handler({"items": [{"source": "prompt", "text": "hello"}]})
        self.assertEqual((logs[-1]["user"], logs[-1]["user_source"]), ("", ""))
        logs = self.call({"items": [{"source": "prompt", "text": "hello"}]})[2]
        self.assertEqual(logs[-1]["user_source"], "token")

    def test_litellm_sends_the_key_user(self):
        sys.path.insert(0, os.path.join(ROOT, "litellm"))
        stub = type(sys)("stub")
        stub.CustomGuardrail, stub.HTTPException = object, Exception
        with mock.patch.dict(sys.modules, {"litellm": stub, "litellm.integrations": stub, "litellm.integrations.custom_guardrail": stub,
                                           "fastapi": stub}):
            import decider_guardrail as dg
        auth = type("Auth", (), {"user_email": None, "user_id": "u-42", "key_alias": "ci-key"})()
        self.assertEqual(dg.key_user(auth), "u-42")
        self.assertEqual(dg.key_user(object()), "")


class FakeIdp(http.server.BaseHTTPRequestHandler):
    """Discovery, /authorize (redirects back with a code), /token (code + PKCE, refresh) and /guard/check."""
    state = None   # set per test

    def log_message(self, *a):
        pass

    def reply(self, status, body, location=None):
        self.send_response(status)
        if location:
            self.send_header("Location", location)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(body).encode())

    def issue(self, renewable=True):
        st = self.state
        jwt = ".".join([b64({"alg": "none"}), b64({"email": MAIL("dev"), "sub": "u1", "n": len(st["issued"])}), "sig"])
        st["issued"].add(jwt)
        out = {"id_token": jwt, "expires_in": 3600}
        if renewable:
            out["refresh_token"] = "R"
        return out

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        if u.path == "/.well-known/openid-configuration":
            base = f"http://127.0.0.1:{self.server.server_port}"
            return self.reply(200, {"authorization_endpoint": base + "/authorize", "token_endpoint": base + "/token"})
        assert u.path == "/authorize" and q["code_challenge_method"] == "S256" and q["client_id"] == "hooks"
        self.state["codes"]["c1"] = (q["code_challenge"], q["redirect_uri"])
        self.reply(302, {}, f"{q['redirect_uri']}?code=c1&state={q['state']}")

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        st = self.state
        if self.path == "/token":
            f = {k: v[0] for k, v in urllib.parse.parse_qs(body).items()}
            if f["grant_type"] == "authorization_code":
                challenge, redirect = st["codes"].pop(f["code"])
                digest = base64.urlsafe_b64encode(hashlib.sha256(f["code_verifier"].encode()).digest()).rstrip(b"=").decode()
                if digest != challenge or redirect != f["redirect_uri"]:
                    return self.reply(400, {"error": "invalid_grant"})
                return self.reply(200, self.issue())
            if not st["renew_ok"]:
                return self.reply(400, {"error": "invalid_grant"})
            return self.reply(200, self.issue(renewable=False))   # like Cognito: renewal keeps the old refresh value
        # /guard/check: API Gateway's JWT authorizer, then the Lambda integration
        jwt = self.headers.get("Authorization", "").removeprefix("Bearer ")
        if jwt not in st["issued"]:
            return self.reply(401, {"message": "Unauthorized"})
        st["calls"] += 1
        resp, _ = quiet_handler({"requestContext": {"http": {}, "authorizer": {"jwt": {"claims": claims_of(jwt)}}}, "body": body})
        self.reply(resp["statusCode"], json.loads(resp["body"]))


def fetch_later(url):
    threading.Thread(target=lambda: urllib.request.urlopen(url, timeout=5).read(), daemon=True).start()
    return True


class SignIn(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DECIDER_GUARD_HOME"] = self.tmp.name
        import decider_guard
        self.h = importlib.reload(decider_guard)
        self.st = FakeIdp.state = {"codes": {}, "issued": set(), "renew_ok": True, "calls": 0}
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeIdp)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{self.srv.server_port}"
        self.cfg = dict(self.h.DEFAULTS, backend="api", api_url=base + "/guard/check", language="en",
                        auth={"client_id": "hooks", "issuer": base})
        with open(os.path.join(self.tmp.name, "config.json"), "w") as f:
            json.dump(self.cfg, f)

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        os.environ.pop("DECIDER_GUARD_HOME", None)
        self.tmp.cleanup()

    def login(self, browser=fetch_later):
        with mock.patch("webbrowser.open", browser), redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()):
            self.h.login(self.cfg)
        return out.getvalue()

    def hook(self, text):
        ev = {"hook_event_name": "UserPromptSubmit", "prompt": text}
        with mock.patch("sys.stdin", io.StringIO(json.dumps(ev))), redirect_stdout(io.StringIO()) as buf, redirect_stderr(io.StringIO()):
            self.h.run_hook("claude")
        return json.loads(buf.getvalue()) if buf.getvalue() else None

    def saved(self):
        with open(self.h.TOKEN_FILE) as f:
            return json.load(f)

    def expire(self):
        stale = dict(self.saved(), expires_at=0)
        with open(self.h.TOKEN_FILE, "w") as f:
            json.dump(stale, f)

    def test_signed_out_blocks_with_a_login_hint(self):
        out = self.hook("hello")
        self.assertEqual(out["decision"], "block")
        self.assertIn("decider-guard login", out["reason"])

    def test_login_check_renew_and_revoke(self):
        self.assertIn(MAIL("dev"), self.login())
        self.assertEqual(os.stat(self.h.TOKEN_FILE).st_mode & 0o777, 0o600)
        self.assertIsNone(self.hook("Show me an S3 bucket policy example"))           # allowed
        self.assertEqual(self.hook("look up resident number " + RRN)["decision"], "block")
        self.assertEqual(self.st["calls"], 2)

        first = self.saved()
        self.expire()
        self.assertIsNone(self.hook("hello"))                                         # renewed silently
        self.assertNotEqual(self.saved()["id_token"], first["id_token"])
        self.assertEqual(self.saved()["refresh_token"], first["refresh_token"])

        self.st["renew_ok"] = False                                                   # user disabled / session revoked
        self.expire()
        self.assertIn("decider-guard login", self.hook("hello")["reason"])

    def test_forged_redirect_is_rejected(self):
        def forged(url):
            redirect = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["redirect_uri"][0]
            return fetch_later(redirect + "?code=c1&state=other")
        with self.assertRaisesRegex(RuntimeError, "state mismatch"):
            self.login(forged)
        self.assertFalse(os.path.exists(self.h.TOKEN_FILE))


if __name__ == "__main__":
    unittest.main(verbosity=1)
