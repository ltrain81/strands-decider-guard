#!/usr/bin/env python3
"""Render the developer installer for the console site (called by scripts/lib.sh publish_dev_installer).

  render_dev_installer.py OUT_DIR CONSOLE_URL API_URL CLIENT_ID ISSUER AUTHORIZE_URL TOKEN_URL

Writes OUT_DIR/install.sh (client/bootstrap.sh with this deployment's values) and OUT_DIR/config.json (read by install.html).
"""
import json
import os
import sys

out, console, api, client, issuer, authorize, token = sys.argv[1:8]
base = console.rstrip("/")
auth = ["--issuer", issuer] if issuer else ["--authorize-url", authorize, "--token-url", token]
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
script = open(os.path.join(root, "client", "bootstrap.sh")).read()
for k, v in (("@BASE@", base), ("@API_URL@", api), ("@CLIENT_ID@", client), ("@AUTH_ARGS@", " ".join(f'"{a}"' for a in auth))):
    script = script.replace(k, v)
with open(os.path.join(out, "install.sh"), "w") as f:
    f.write(script)
with open(os.path.join(out, "config.json"), "w") as f:
    json.dump({"base": base, "oneliner": f'bash -c "$(curl -fsSL {base}/dev/install.sh)"',
               "manual": " ".join(["client/install.sh", "--api-url", api, "--client-id", client] + auth)}, f, indent=2)
