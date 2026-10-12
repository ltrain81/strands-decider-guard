"""Opt-in evidence: the text of checks, kept when the policy's "evidence" setting asks for it.

AWS: objects in the evidence bucket (evidence/YYYY/MM/DD/<request id>.json), deleted by a lifecycle rule after
EVIDENCE_DAYS. Local: ~/.decider-guard/evidence/<id>.json written by the hook's local mode. Every read is recorded
in the admin activity log by handler.py.
"""
import json
import os
import re

from common import AUDIT_LOG, EVIDENCE_BUCKET, LOCAL, aws

KEY = re.compile(r"^(evidence/\d{4}/\d{2}/\d{2}/[\w-]+\.json|local/[\w-]+)$")


def read(key):
    if not key or not KEY.match(key):
        raise ValueError("invalid evidence key")
    if LOCAL:
        if not key.startswith("local/"):
            raise ValueError("invalid evidence key")
        path = os.path.join(os.path.dirname(AUDIT_LOG), "evidence", key.split("/", 1)[1] + ".json")
        with open(path) as f:
            return json.load(f)
    s3 = aws("s3")
    try:
        return json.load(s3.get_object(Bucket=EVIDENCE_BUCKET, Key=key)["Body"])
    except s3.exceptions.NoSuchKey:
        raise ValueError("evidence expired or not found")
