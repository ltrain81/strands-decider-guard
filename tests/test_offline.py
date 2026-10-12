#!/usr/bin/env python3
"""Fast tests that need no model server and no AWS (run in CI): python3 -m unittest tests/test_offline.py

The decider is replaced by a fake that returns fixed probabilities, so these tests pin the policy
logic, regexes, hook output formats and config merging rather than model quality
(that is tests/eval_accuracy.py and tests/test_with_model.py, which need a running decider).
"""
import importlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "guard"), os.path.join(ROOT, "client"), os.path.join(ROOT, "admin", "api")]
import guard_core as g  # noqa: E402


RRN = "-".join(["900101", "1234567"])                      # synthetic resident number
MAIL = lambda user: "@".join([user, "example.com"])         # synthetic addresses


def fake_answers(kind="none", p_kind=0.95, about=0.1, real=0.1, named=0.1, rules=None):
    """Decider answers shaped like the real API: kind probabilities spread over the other categories."""
    cats = ["none", "contact", "government_id", "financial", "health", "private_life", "credential"]
    rest = (1 - p_kind) / (len(cats) - 1)
    probs = {c: (p_kind if c == kind else rest) for c in cats}
    out = {"kind": {"type": "choice", "choice": kind, "probabilities": probs, "confidence": p_kind},
           "about_person": {"noul": about}, "real_values": {"noul": real}, "named_person": {"noul": named}}
    for key, p in (rules or {}).items():
        out[key] = {"noul": p}
    return out


class FakeDecider:
    def __init__(self, **kw):
        self.kw, self.calls = kw, []

    def __call__(self, state, url=None, timeout=20, questions=None):
        self.calls.append((state, sorted(questions or {})))
        return fake_answers(**self.kw)


def check(text, policy=None, lang="en", **answers):
    fake = FakeDecider(**answers)
    with mock.patch.object(g, "ask_decider", fake):
        return g.check(text, None, policy, lang), fake


class Patterns(unittest.TestCase):
    def hits(self, text):
        return {h["type"] for h in g.scan_patterns(text, g.normalize_policy(None))}

    def test_resident_id(self):
        self.assertIn("kr_resident_id", self.hits("주민번호 900101-1234567"))
        self.assertNotIn("kr_resident_id", self.hits("order 901301-1234567"))  # month 13

    def test_card_needs_luhn_and_skips_published_test_cards(self):
        def luhn_complete(prefix):   # append the check digit
            digits = [int(c) for c in prefix + "0"]
            for i in range(len(digits) - 2, -1, -2):
                digits[i] = digits[i] * 2 - 9 if digits[i] > 4 else digits[i] * 2
            return prefix + str((10 - sum(digits) % 10) % 10)
        real = luhn_complete("45320151" + "1283036")
        self.assertIn("card_number", self.hits("card " + real))
        self.assertNotIn("card_number", self.hits("card " + real[:-1] + str((int(real[-1]) + 1) % 10)))
        self.assertNotIn("card_number", self.hits("stripe test card " + "4242" * 4))

    def test_secrets(self):
        fake_key = "AKIA" + "Z" * 16  # built at runtime so secret scanners do not flag a test fixture
        self.assertIn("aws_access_key_id", self.hits(f"key {fake_key}"))
        self.assertIn("private_key", self.hits("-----BEGIN RSA PRIVATE KEY-----"))

    def test_contact_patterns(self):
        h = self.hits("mail jane@acme.com or call 010-2345-6789 / +1 415 555 0199")
        self.assertTrue({"email", "kr_mobile", "phone_intl"} <= h)

    def test_dates_and_schemas_are_not_ids(self):
        self.assertEqual(self.hits("git log --since=2024-01-01; CREATE TABLE t (phone VARCHAR(20))"), set())

    def test_mask_never_returns_the_value(self):
        self.assertNotIn("1234567", g.mask("900101-1234567"))


class Policy(unittest.TestCase):
    def test_defaults(self):
        p = g.normalize_policy(None)
        self.assertEqual(p["sensitivity"], "balanced")
        self.assertTrue(all(v == "block" for v in p["categories"].values()))

    def test_validation_messages_are_localized(self):
        with self.assertRaisesRegex(ValueError, "Unknown sensitivity"):
            g.normalize_policy({"sensitivity": "max"}, "en")
        with self.assertRaisesRegex(ValueError, "알 수 없는 민감도"):
            g.normalize_policy({"sensitivity": "max"}, "ko")
        for bad in ({"categories": {"nope": "block"}}, {"categories": {"health": "deny"}}, {"custom_rules": [{"question": " "}]},
                    {"custom_rules": [{"question": "x?"}] * 21}):
            with self.assertRaises(ValueError):
                g.normalize_policy(bad)

    def test_rules_and_allowlist_are_cleaned(self):
        p = g.normalize_policy({"custom_rules": [{"id": "a b!", "question": "q?"}, {"id": "ab", "question": "q2?"}],
                                "allow": {"email_domains": ["@Acme.COM", " "], "terms": ["Jane Doe"]}})
        self.assertEqual([r["id"] for r in p["custom_rules"]], ["ab", "abx"])
        self.assertEqual(p["allow"]["email_domains"], ["acme.com"])

    def test_allowlist_removes_values_before_checking(self):
        p = g.normalize_policy({"allow": {"email_domains": ["acme.com"], "terms": ["Jane Doe"]}})
        out = g.apply_allowlist("Jane Doe <jane@acme.com>, bob@other.org", p)
        self.assertNotIn("Jane Doe", out)
        self.assertNotIn("jane@acme.com", out)
        self.assertIn("bob@other.org", out)


class Judgement(unittest.TestCase):
    def test_strong_pattern_blocks_without_calling_the_model(self):
        r, fake = check("resident number 900101-1234567")
        self.assertEqual(r["decision"], "block")
        self.assertEqual(fake.calls, [])

    def test_category_action_caps_a_strong_pattern(self):
        r, _ = check("900101-1234567", {"categories": {"resident_id": "ask", "gov_id": "ask"}})
        self.assertEqual(r["decision"], "ask")
        r, _ = check("900101-1234567", {"categories": {"resident_id": "allow", "gov_id": "allow"}})
        self.assertEqual(r["decision"], "allow")

    def test_sensitive_about_a_named_person_blocks(self):
        r, _ = check("Mark is treated for depression", kind="health", named=0.7, about=0.4, real=0.2)
        self.assertEqual(r["decision"], "block")
        self.assertIn("Health / medical data", r["reasons"][0])

    def test_unnamed_sensitive_text_in_the_ask_band_asks(self):
        r, _ = check("SELECT name, email FROM users", kind="contact", named=0.07, real=0.55)
        self.assertEqual(r["decision"], "ask")

    def test_non_sensitive_text_is_allowed(self):
        r, _ = check("Tim Cook is the CEO of Apple", kind="none", named=0.93)
        self.assertEqual(r["decision"], "allow")
        self.assertEqual(r["reasons"], [])

    def test_disabled_category_is_ignored(self):
        r, _ = check("Mark is treated for depression", {"categories": {"health": "allow"}}, kind="health", named=0.9)
        self.assertEqual(r["decision"], "allow")

    def test_sensitivity_changes_the_threshold(self):
        named = dict(kind="contact", named=0.4, real=0.3)       # a named person, little else
        self.assertEqual(check("x" * 20, {"sensitivity": "lenient"}, **named)[0]["decision"], "allow")
        self.assertEqual(check("x" * 20, {"sensitivity": "balanced"}, **named)[0]["decision"], "block")
        values = dict(kind="contact", named=0.2, real=0.7)      # real values, nobody named
        self.assertEqual(check("x" * 20, {"sensitivity": "balanced"}, **values)[0]["decision"], "ask")
        self.assertEqual(check("x" * 20, {"sensitivity": "strict"}, **values)[0]["decision"], "block")

    def test_private_life_category(self):
        r, _ = check("x" * 20, kind="private_life", named=0.8, real=0.3)
        self.assertEqual((r["decision"], r["findings"][0]["category"]), ("block", "private_life"))
        r, _ = check("x" * 20, {"categories": {"private_life": "allow"}}, kind="private_life", named=0.8, real=0.3)
        self.assertEqual(r["decision"], "allow")

    def test_placeholder_credentials_pass_when_lenient(self):
        r, _ = check("DB_PASSWORD=${DB_PASSWORD}", {"sensitivity": "lenient"}, kind="credential", p_kind=0.95, real=0.1, about=0.1)
        self.assertEqual(r["decision"], "allow")

    def test_custom_rule(self):
        policy = {"custom_rules": [{"id": "phx", "name": "Phoenix", "question": "Unreleased Phoenix plans?", "action": "block"}]}
        r, fake = check("Phoenix launches in March", policy, rules={"rule_phx": 0.9})
        self.assertEqual(r["decision"], "block")
        self.assertIn("rule_phx", fake.calls[0][1])
        self.assertEqual(check("phoenix web framework", policy, rules={"rule_phx": 0.1})[0]["decision"], "allow")

    def test_only_rules_means_only_rule_questions(self):
        policy = {"categories": {c["id"]: "allow" for c in g.CATEGORIES},
                  "custom_rules": [{"id": "s", "question": "Salary?", "action": "ask"}]}
        r, fake = check("salary 6200", policy, rules={"rule_s": 0.9})
        self.assertEqual(r["decision"], "ask")
        self.assertEqual(fake.calls[0][1], ["rule_s"])

    def test_long_text_is_sampled(self):
        r, fake = check("a" * (g.CHUNK_CHARS * 40))
        self.assertTrue(r["truncated"])
        self.assertEqual(len(fake.calls), g.MAX_CHUNKS)

    def test_korean_reasons(self):
        r, _ = check("900101-1234567", None, "ko")
        self.assertIn("주민등록번호", r["reasons"][0])


class PatternModeAndBasis(unittest.TestCase):
    def test_pattern_modes(self):
        text = "id " + RRN + " mail " + MAIL("ops")
        self.assertEqual(check(text)[0]["basis"], "pattern")                             # assist: certain format blocks
        r, fake = check(text, {"patterns": "off"})
        self.assertEqual((r["decision"], r["findings"]), ("allow", []))                  # off: no regex at all, model says none
        self.assertTrue(fake.calls)
        r, _ = check("mail " + MAIL("ops"), {"patterns": "strong"}, kind="contact", named=0.1, real=0.1)
        self.assertEqual(r["findings"], [])                                              # strong: weak hints are not used
        with self.assertRaises(ValueError):
            g.normalize_policy({"patterns": "maybe"})

    def test_basis(self):
        self.assertEqual(check("x" * 20, kind="health", named=0.9)[0]["basis"], "model")
        r, _ = check("write to " + MAIL("ops"), kind="contact", named=0.1, real=0.1, p_kind=0.5)
        self.assertEqual((r["decision"], r["basis"]), ("block", "model_pattern"))
        self.assertTrue(r["basis_label"])
        rule = {"custom_rules": [{"id": "x", "question": "q?", "action": "block"}]}
        self.assertEqual(check("plan for project x", rule, rules={"rule_x": 0.9})[0]["basis"], "rule")


class LambdaEvidence(unittest.TestCase):
    def test_evidence_capture_respects_the_policy(self):
        import lambda_handler as lh
        items = [{"source": "prompt", "text": "id " + RRN}]
        out = g.check_many(items)
        s3 = mock.MagicMock()
        with mock.patch.object(lh, "EVIDENCE_BUCKET", "bucket"), mock.patch.dict(sys.modules, {"boto3": mock.MagicMock(client=lambda n: s3)}):
            self.assertIsNone(lh.save_evidence(items, out, {"evidence": "off"}, "claude", "rid"))
            key = lh.save_evidence(items, out, {"evidence": "blocked"}, "claude", "rid")
            self.assertTrue(key.startswith("evidence/") and key.endswith("/rid.json"))
            body = json.loads(s3.put_object.call_args.kwargs["Body"])
            self.assertEqual((body["items"][0]["source"], body["items"][0]["decision"]), ("prompt", "block"))
            allowed = g.check_many([{"source": "prompt", "text": "hi"}])
            self.assertIsNone(lh.save_evidence([{"source": "prompt", "text": "hi"}], allowed, {"evidence": "blocked"}, "c", "r2"))


class Hook(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DECIDER_GUARD_HOME"] = self.tmp.name
        import decider_guard
        self.h = importlib.reload(decider_guard)
        self.cfg = dict(self.h.DEFAULTS, language="en")

    def tearDown(self):
        os.environ.pop("DECIDER_GUARD_HOME", None)
        self.tmp.cleanup()

    def test_tool_extraction(self):
        path = os.path.join(self.tmp.name, "c.csv")
        with open(path, "w") as f:
            f.write("name,phone\nJane,010-2345-6789\n")
        items = self.h.tool_items("claude", "Read", {"file_path": path}, None, self.cfg)
        self.assertEqual(items[0]["source"], "file:c.csv")
        items = self.h.tool_items("codex", "Bash", {"command": "head -n 2 c.csv | cut -d, -f1"}, self.tmp.name, self.cfg)
        self.assertEqual([i["source"] for i in items], ["bash", "file:c.csv"])
        items = self.h.tool_items("codex", "apply_patch", {"command": "*** Begin Patch\n+added line\n-removed\n*** End Patch"}, None, self.cfg)
        self.assertEqual(items[0]["text"], "added line")
        self.assertEqual(self.h.tool_items("kiro", "str_replace", {"newStr": "new"}, None, self.cfg)[0]["text"], "new")
        self.assertEqual(self.h.tool_items("claude", "Glob", {"pattern": "**"}, None, self.cfg), [])

    def emit(self, agent, event, decision):
        buf = io.StringIO()
        with redirect_stdout(buf), redirect_stderr(io.StringIO()):
            code = self.h.emit(self.cfg, agent, event, decision, "MSG", ["Email pattern found (j***@x.com)"])
        return code, buf.getvalue()

    def test_output_formats(self):
        code, out = self.emit("claude", "UserPromptSubmit", "block")
        self.assertEqual((code, json.loads(out)["decision"]), (0, "block"))
        code, out = self.emit("claude", "PreToolUse", "ask")
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "ask")
        code, out = self.emit("kiro", "PreToolUse", "block")
        self.assertEqual(code, 2)
        code, out = self.emit("kiro", "UserPromptSubmit", "block")   # Kiro cannot block prompts: warn the model
        self.assertEqual(code, 0)
        self.assertIn("Email pattern found", out)
        self.assertNotIn("j***@x.com", out)
        code, out = self.emit("codex", "PreToolUse", "block")
        self.assertEqual(json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(self.emit("claude", "PreToolUse", "allow"), (0, ""))

    def test_language_from_locale(self):
        cfg = dict(self.h.DEFAULTS)
        with mock.patch.dict(os.environ, {"LANG": "ko_KR.UTF-8", "LC_ALL": ""}):
            self.assertEqual(self.h.language(cfg), "ko")
        with mock.patch.dict(os.environ, {"LANG": "en_US.UTF-8", "LC_ALL": ""}):
            self.assertEqual(self.h.language(cfg), "en")

    def test_end_to_end_local_mode_with_fake_decider(self):
        with open(os.path.join(self.tmp.name, "config.json"), "w") as f:
            json.dump({"backend": "local", "language": "en"}, f)
        ev = json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "look up 900101-1234567"})
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(ev)), redirect_stdout(buf), mock.patch.object(g, "ask_decider", FakeDecider()):
            sys.modules["guard_core"] = g
            code = self.h.run_hook("claude")
        self.assertEqual(code, 0)
        self.assertIn("Resident registration number", json.loads(buf.getvalue())["reason"])


    def _hook(self, ev, cfg):
        with open(os.path.join(self.tmp.name, "config.json"), "w") as f:
            json.dump(cfg, f)
        buf = io.StringIO()
        with mock.patch("sys.stdin", io.StringIO(json.dumps(ev))), redirect_stdout(buf), redirect_stderr(io.StringIO()):
            sys.modules["guard_core"] = g
            self.h.run_hook("claude")
        return buf.getvalue()

    def test_model_down_falls_back_to_patterns(self):
        g._down_until = 0
        cfg = {"backend": "local", "decider_url": "http://127.0.0.1:9", "language": "en"}
        clean = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git log --oneline -20"}}
        self.assertEqual(self._hook(clean, cfg), "")                       # allowed, model skipped
        g._down_until = 0
        mail = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "send the report to " + MAIL("ops")}}
        out = json.loads(self._hook(mail, cfg))["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "ask")                  # weak pattern without the model -> ask
        self.assertIn("patterns only", out["permissionDecisionReason"])
        g._down_until = 0

    def test_unreachable_guard_says_so(self):
        ev = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "git log --oneline -20"}}
        with mock.patch.object(self.h, "call_guard", side_effect=RuntimeError("guard Lambda error")):
            out = self._hook(ev, {"backend": "lambda", "function_name": "x", "language": "en"})
        reason = json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("Could not reach the guard", reason)
        self.assertNotIn("Sensitive data detected", reason)


class ConfigureAgents(unittest.TestCase):
    def run_cfg(self, home, *args):
        env = dict(os.environ, HOME=home)
        return subprocess.run([sys.executable, os.path.join(ROOT, "client", "configure_agents.py"), *args], env=env,
                              capture_output=True, text=True, check=True)

    def test_install_keeps_existing_hooks_and_uninstall_removes_only_ours(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, ".claude"))
            settings = os.path.join(home, ".claude", "settings.json")
            with open(settings, "w") as f:
                json.dump({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}, f)
            for _ in range(2):  # idempotent
                self.run_cfg(home, "install", "--agents", "claude,kiro,codex", "--command", "py decider_guard.py", "--fail-closed")
            with open(settings) as f:
                s = json.load(f)
            self.assertEqual(len(s["hooks"]["UserPromptSubmit"]), 1)
            self.assertEqual(s["hooks"]["PreToolUse"][0]["hooks"][0]["onFailure"], "block")
            self.assertTrue(os.path.exists(os.path.join(home, ".kiro", "hooks", "decider-guard.json")))
            self.run_cfg(home, "uninstall", "--agents", "claude,kiro,codex")
            with open(settings) as f:
                s = json.load(f)
            self.assertEqual(list(s["hooks"]), ["Stop"])
            self.assertFalse(os.path.exists(os.path.join(home, ".kiro", "hooks", "decider-guard.json")))


class AdminApi(unittest.TestCase):
    """The console API in local mode (policy file + audit.log), plus alerts against fake AWS clients."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ.update(POLICY_FILE=os.path.join(self.tmp.name, "policy.json"), LOCAL_DECIDER_URL="http://fake",
                          AUDIT_LOG=os.path.join(self.tmp.name, "audit.log"))
        now = __import__("datetime").datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with open(os.environ["AUDIT_LOG"], "w") as f:
            for d, types in (("block", ["kr_resident_id"]), ("allow", []), ("ask", ["email"])):
                f.write(json.dumps({"ts": now, "agent": "claude", "event": "PreToolUse", "tool": "Read",
                                    "decision": d, "types": types, "sources": ["file:a.csv"], "ms": 200}) + "\n")
        import common, monitoring, alerts, evidence, handler
        for mod in (common, monitoring, alerts, evidence, handler):
            importlib.reload(mod)
        self.api, self.monitoring, self.alerts = handler, monitoring, alerts

    def tearDown(self):
        for k in ("POLICY_FILE", "LOCAL_DECIDER_URL", "AUDIT_LOG"):
            os.environ.pop(k, None)
        self.tmp.cleanup()

    def call(self, method, path, body=None, lang="en", query=None):
        with redirect_stdout(io.StringIO()):  # swallow the audit lines
            r = self.api.handler({"requestContext": {"http": {"method": method}}, "rawPath": path, "headers": {"x-lang": lang},
                                  "queryStringParameters": query or {}, "body": json.dumps(body) if body is not None else ""})
        return r["statusCode"], json.loads(r["body"])

    def test_policy_roundtrip_history_and_test(self):
        code, r = self.call("GET", "/api/policy")
        self.assertEqual((code, r["meta"]["categories"][0]["label"]), (200, "Resident registration number"))
        self.assertEqual(self.call("GET", "/api/policy", lang="ko")[1]["meta"]["categories"][0]["label"], "주민·외국인등록번호")
        self.assertEqual(self.call("PUT", "/api/policy", {"policy": {"sensitivity": "strict"}})[1]["policy"]["sensitivity"], "strict")
        self.assertEqual(self.call("PUT", "/api/policy", {"policy": {"sensitivity": "x"}})[0], 400)
        self.call("PUT", "/api/policy", {"policy": {"sensitivity": "balanced", "categories": {"health": "ask"}}})
        versions = self.call("GET", "/api/history")[1]["versions"]
        self.assertEqual(len(versions), 2)
        code, r = self.call("GET", f"/api/history/{versions[-1]['version_id']}")   # the first save vs the current policy
        self.assertEqual({c["kind"] for c in r["changes"]}, {"sensitivity", "category"})
        with mock.patch.object(g, "ask_decider", FakeDecider()):
            code, r = self.call("POST", "/api/test", {"text": "id " + RRN, "policy": {}})
        self.assertEqual((code, r["decision"]), (200, "block"))
        self.assertEqual(self.call("POST", "/api/test", {"text": " "})[0], 400)

    def test_overview_logs_activity(self):
        with mock.patch.object(g, "health", lambda url=None, timeout=5: {"model": "m", "device": "cpu"}):
            code, o = self.call("GET", "/api/overview", query={"hours": "24"})
        self.assertEqual(code, 200)
        self.assertTrue(o["health"]["guard"]["ok"])
        self.assertEqual((o["totals"]["checks"], o["totals"]["block"], o["totals"]["ask"]), (3, 1, 1))
        self.assertEqual(sum(b["block"] for b in o["series"]), 1)
        code, logs = self.call("GET", "/api/logs", query={"hours": "24", "decision": "block,ask"})
        self.assertEqual((code, len(logs["rows"])), (200, 2))
        self.assertEqual(len(self.call("GET", "/api/logs", query={"category": "resident_id"})[1]["rows"]), 1)
        self.assertEqual(self.call("GET", "/api/logs", query={"q": 'x" | fields @message'})[0], 400)
        self.assertEqual(self.call("GET", "/api/logs", query={"decision": "maybe"})[0], 400)
        self.call("PUT", "/api/policy", {"policy": {"sensitivity": "strict"}})
        rows = self.call("GET", "/api/activity")[1]["rows"]
        self.assertEqual((rows[0]["action"], rows[0]["detail"][0]["kind"]), ("policy_saved", "sensitivity"))
        self.assertEqual(self.call("GET", "/api/alerts")[1], {"available": False})

    def test_local_evidence_roundtrip_is_audited(self):
        sys.path.insert(0, os.path.join(ROOT, "client"))
        os.environ["DECIDER_GUARD_HOME"] = self.tmp.name
        import decider_guard
        h = importlib.reload(decider_guard)
        verdict = {"decision": "block", "results": [{"decision": "block", "basis": "pattern", "reasons": ["r"]}]}
        key = h.save_local_evidence([{"source": "prompt", "text": "secret text"}], verdict, {"evidence": "blocked"}, "claude")
        os.environ.pop("DECIDER_GUARD_HOME")
        code, ev = self.call("GET", "/api/evidence", query={"key": key})
        self.assertEqual((code, ev["items"][0]["text"]), (200, "secret text"))
        self.assertEqual(self.call("GET", "/api/evidence", query={"key": "../../etc/passwd"})[0], 400)

    def test_policy_changes(self):
        old = g.normalize_policy({"custom_rules": [{"id": "a", "name": "A", "question": "a?"}], "allow": {"terms": ["x"]}})
        new = g.normalize_policy({"sensitivity": "strict", "custom_rules": [{"id": "a", "name": "A", "question": "changed?"},
                                  {"id": "b", "name": "B", "question": "b?"}], "allow": {"terms": ["y"]}, "message": "hi"})
        kinds = [c["kind"] for c in self.monitoring.policy_changes(old, new)]
        self.assertEqual(kinds, ["sensitivity", "rule_changed", "rule_added", "allow_added", "allow_removed", "message"])

    def test_alert_settings_and_alarms(self):
        n = self.alerts.normalize({"emails": [MAIL("ops")], "rules": {"block_spike": {"enabled": True, "threshold": 0}}})
        self.assertEqual((n["rules"]["block_spike"]["threshold"], n["rules"]["guard_down"]["enabled"]), (1, True))
        for bad in ({"emails": ["not-an-email"]}, {"rules": {"nope": {}}}):
            with self.assertRaises(ValueError):
                self.alerts.normalize(bad)
        fake = {"s3": mock.MagicMock(), "sns": mock.MagicMock(), "cloudwatch": mock.MagicMock()}
        fake["s3"].exceptions.NoSuchKey = type("NoSuchKey", (Exception,), {})
        fake["s3"].get_object.side_effect = fake["s3"].exceptions.NoSuchKey
        fake["sns"].list_subscriptions_by_topic.return_value = {"Subscriptions": [
            {"Protocol": "email", "Endpoint": MAIL("old"), "SubscriptionArn": "arn:aws:sns:x:1:t:abc"}]}
        with mock.patch.object(self.alerts, "LOCAL", False), mock.patch.object(self.alerts, "ALERTS_TOPIC", "arn:aws:sns:x:1:t"), \
                mock.patch.object(self.alerts, "GUARD_FUNCTION", "guard"), mock.patch.object(self.alerts, "aws", lambda name: fake[name]):
            cfg, changes = self.alerts.save({"emails": [MAIL("ops")], "rules": {"latency": {"enabled": True, "threshold_ms": 2500}}})
        fake["sns"].subscribe.assert_called_once()
        fake["sns"].unsubscribe.assert_called_once_with(SubscriptionArn="arn:aws:sns:x:1:t:abc")
        alarms = {c.kwargs["AlarmName"]: c.kwargs for c in fake["cloudwatch"].put_metric_alarm.call_args_list}
        self.assertEqual(sorted(alarms), ["DeciderGuard-guard_down", "DeciderGuard-guard_errors", "DeciderGuard-latency"])
        self.assertEqual(alarms["DeciderGuard-latency"]["Threshold"], 2500)
        fake["cloudwatch"].delete_alarms.assert_called_once_with(AlarmNames=["DeciderGuard-block_spike"])
        self.assertEqual({c["kind"] for c in changes}, {"email_added", "email_removed", "rule"})


if __name__ == "__main__":
    unittest.main()
