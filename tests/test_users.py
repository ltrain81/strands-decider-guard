#!/usr/bin/env python3
"""Offline tests for developer management (admin/api/users.py through the admin API) and the developer installer.
A fake Cognito stands in for the Developers user pool. Run: python3 -I tests/test_users.py
"""
import datetime as dt
import importlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "guard"), os.path.join(ROOT, "admin", "api")]
MAIL = lambda user: "@".join([user, "example.com"])   # synthetic addresses


class FakeCognito:
    """Just enough of cognito-idp for users.py: users with status/enabled, groups, sign-outs."""
    class exceptions:
        class UsernameExistsException(Exception):
            pass

    def __init__(self):
        self.users, self.groups, self.signed_out, self.sent = {}, {}, [], []

    def _u(self, name):
        return next(u for k, u in self.users.items() if name in (k, u["email"]))

    def admin_create_user(self, UserPoolId, Username, DesiredDeliveryMediums, UserAttributes=None, MessageAction=None):
        if MessageAction == "RESEND":
            self.sent.append(("resend", self._u(Username)["email"]))
            return {"User": {}}
        if any(u["email"] == Username for u in self.users.values()):
            raise self.exceptions.UsernameExistsException()
        name = f"uuid-{len(self.users)}"
        self.users[name] = {"email": Username, "status": "FORCE_CHANGE_PASSWORD", "enabled": True, "groups": set()}
        self.sent.append(("invite", Username))
        return {"User": {"Username": name}}

    def list_users(self, UserPoolId, Limit, NextToken=None):
        return {"Users": [{"Username": k, "Enabled": u["enabled"], "UserStatus": u["status"],
                           "UserCreateDate": dt.datetime(2026, 10, 12, tzinfo=dt.timezone.utc),
                           "Attributes": [{"Name": "email", "Value": u["email"]}]} for k, u in self.users.items()]}

    def list_groups(self, UserPoolId, Limit, NextToken=None):
        return {"Groups": [{"GroupName": g, "Description": d} for g, d in self.groups.items()]}

    def list_users_in_group(self, UserPoolId, GroupName, Limit, NextToken=None):
        return {"Users": [{"Username": k} for k, u in self.users.items() if GroupName in u["groups"]]}

    def admin_list_groups_for_user(self, UserPoolId, Username, Limit):
        return {"Groups": [{"GroupName": g} for g in self._u(Username)["groups"]]}

    def admin_add_user_to_group(self, UserPoolId, Username, GroupName):
        self._u(Username)["groups"].add(GroupName)

    def admin_remove_user_from_group(self, UserPoolId, Username, GroupName):
        self._u(Username)["groups"].discard(GroupName)

    def admin_get_user(self, UserPoolId, Username):
        return {"UserStatus": self._u(Username)["status"]}

    def admin_user_global_sign_out(self, UserPoolId, Username):
        self.signed_out.append(Username)

    def admin_disable_user(self, UserPoolId, Username):
        self._u(Username)["enabled"] = False

    def admin_enable_user(self, UserPoolId, Username):
        self._u(Username)["enabled"] = True

    def admin_delete_user(self, UserPoolId, Username):
        del self.users[next(k for k, u in self.users.items() if Username in (k, u["email"]))]

    def create_group(self, UserPoolId, GroupName, Description):
        self.groups[GroupName] = Description

    def delete_group(self, UserPoolId, GroupName):
        self.groups.pop(GroupName)
        for u in self.users.values():
            u["groups"].discard(GroupName)


class Developers(unittest.TestCase):
    def setUp(self):
        env = {"DEV_POOL_ID": "pool", "GUARD_API_URL": "https://api.example/guard/check", "DEV_CLIENT_ID": "cid",
               "DEV_AUTHORIZE_URL": "https://auth.example/oauth2/authorize", "DEV_TOKEN_URL": "https://auth.example/oauth2/token",
               "POLICY_BUCKET": "b"}
        self.env = mock.patch.dict(os.environ, env)
        self.env.start()
        import common
        import users
        import handler
        for mod in (common, users, handler):
            importlib.reload(mod)
        self.cog = FakeCognito()
        common._clients["cognito-idp"] = self.cog
        self.handler = handler

    def tearDown(self):
        self.env.stop()

    def call(self, method, path, body=None):
        ev = {"requestContext": {"http": {"method": method}, "authorizer": {"jwt": {"claims": {"email": MAIL("admin")}}}},
              "rawPath": path, "headers": {"x-lang": "en"}, "body": json.dumps(body) if body is not None else ""}
        with redirect_stdout(io.StringIO()) as out:
            r = self.handler.handler(ev)
        audits = [json.loads(l) for l in out.getvalue().splitlines() if l.startswith('{"action"')]
        return r["statusCode"], json.loads(r["body"]), audits

    def users(self):
        return {u["email"]: u for u in self.call("GET", "/api/users")[1]["users"]}

    def test_invite_group_disable_delete(self):
        self.assertEqual(self.call("POST", "/api/groups", {"name": "backend", "description": "API team"})[0], 200)
        status, out, audits = self.call("POST", "/api/users", {"emails": [MAIL("kim"), MAIL("lee")], "groups": ["backend"]})
        self.assertEqual((status, [r["ok"] for r in out["results"]]), (200, [True, True]))
        self.assertEqual(audits[0]["action"], "users_invited")
        self.assertEqual([k for k, _ in self.cog.sent], ["invite", "invite"])

        u = self.users()
        self.assertEqual((u[MAIL("kim")]["state"], u[MAIL("kim")]["groups"]), ("invited", ["backend"]))
        listing = self.call("GET", "/api/users")[1]
        self.assertEqual(listing["groups"][0]["members"], 2)
        self.assertIn("--client-id cid --authorize-url", listing["install"])

        again = self.call("POST", "/api/users", {"emails": [MAIL("kim")]})[1]["results"][0]
        self.assertEqual((again["ok"], again["error"]), (False, "already has a sign-in"))

        kim = u[MAIL("kim")]["username"]
        self.call("POST", "/api/users/action", {"username": kim, "email": MAIL("kim"), "action": "resend"})
        self.assertEqual(self.cog.sent[-1], ("resend", MAIL("kim")))
        self.call("POST", "/api/users/action", {"username": kim, "action": "disable"})
        self.assertEqual((self.users()[MAIL("kim")]["state"], self.cog.signed_out), ("disabled", [kim]))   # sessions ended too
        self.call("POST", "/api/users/action", {"username": kim, "action": "enable"})
        self.assertEqual(self.users()[MAIL("kim")]["state"], "invited")

        self.call("POST", "/api/groups", {"name": "data"})
        _, out, audits = self.call("PUT", "/api/users/groups", {"username": kim, "email": MAIL("kim"), "groups": ["data"]})
        self.assertEqual((out["added"], out["removed"]), (["data"], ["backend"]))
        self.assertEqual([c["kind"] for c in audits[0]["detail"]], ["user", "group_added", "group_removed"])

        self.call("POST", "/api/users/action", {"username": kim, "action": "delete"})
        self.assertNotIn(MAIL("kim"), self.users())
        self.call("POST", "/api/groups/delete", {"name": "backend"})
        self.assertEqual(self.users()[MAIL("lee")]["groups"], [])

    def test_validation(self):
        self.assertEqual(self.call("POST", "/api/users", {"emails": ["not-an-address"]})[0], 400)
        self.assertEqual(self.call("POST", "/api/users", {"emails": [MAIL("a")], "groups": ["nope"]})[0], 400)
        self.assertEqual(self.call("POST", "/api/groups", {"name": "has space"})[0], 400)
        self.assertEqual(self.call("POST", "/api/users", {"emails": [MAIL(f"u{i}") for i in range(51)]})[0], 400)
        self.assertEqual(self.cog.users, {})

    def test_resend_only_before_first_sign_in(self):
        self.call("POST", "/api/users", {"emails": [MAIL("park")]})
        name = next(iter(self.cog.users))
        self.cog.users[name]["status"] = "CONFIRMED"
        status, out, _ = self.call("POST", "/api/users/action", {"username": name, "action": "resend"})
        self.assertEqual(status, 400)
        self.assertEqual(self.users()[MAIL("park")]["state"], "active")

    def test_not_available_without_a_pool(self):
        with mock.patch.dict(os.environ, {"DEV_POOL_ID": "", "DEV_ISSUER": "https://idp.example"}):
            import users
            importlib.reload(users)
            out = users.status()
        self.assertEqual((out["available"], out["reason"], out["issuer"]), (False, "idp", "https://idp.example"))


class GuardLogsGroups(unittest.TestCase):
    def test_groups_from_the_token_are_logged(self):
        import lambda_handler as lh
        for claim, want in ((["backend", "data"], "backend,data"), ("[backend data]", "backend,data"), (None, "")):
            claims = {"email": MAIL("dev")}
            if claim is not None:
                claims["cognito:groups"] = claim
            ev = {"requestContext": {"http": {}, "authorizer": {"jwt": {"claims": claims}}},
                  "body": json.dumps({"items": [{"source": "prompt", "text": "hello"}]})}
            with redirect_stdout(io.StringIO()) as out, mock.patch.dict(os.environ, {"DECIDER_URL": "http://127.0.0.1:9"}):
                lh.handler(ev, None)
            self.assertEqual(json.loads(out.getvalue().splitlines()[-1])["groups"], want)


class DevInstaller(unittest.TestCase):
    def test_render_and_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run([sys.executable, os.path.join(ROOT, "scripts", "render_dev_installer.py"), d, "https://console.example/",
                            "https://api.example/guard/check", "cid", "", "https://auth.example/a", "https://auth.example/t"], check=True)
            with open(os.path.join(d, "install.sh")) as f:
                script = f.read()
            self.assertEqual(re.findall(r"@[A-Z_]+@", script), [])               # every placeholder filled
            self.assertIn('"$@"', script)                                         # options still pass through
            self.assertIn('BASE="https://console.example"', script)
            subprocess.run(["bash", "-n", os.path.join(d, "install.sh")], check=True)
            with open(os.path.join(d, "config.json")) as f:
                cfg = json.load(f)
            self.assertEqual(cfg["oneliner"], 'bash -c "$(curl -fsSL https://console.example/dev/install.sh)"')
            self.assertIn("--authorize-url https://auth.example/a --token-url https://auth.example/t", cfg["manual"])


if __name__ == "__main__":
    unittest.main(verbosity=1)
