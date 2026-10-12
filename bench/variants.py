"""Question-set variants for the guard, compared by tune.py. V0 is guard_core.QUESTIONS as shipped."""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "guard"))
import guard_core as g  # noqa: E402

V0 = copy.deepcopy(g.QUESTIONS)

V1 = copy.deepcopy(g.QUESTIONS)
V1["kind"]["criteria"] = {
    "none": "no personal or secret data: code, schemas, column names, placeholders, templates, policies, statistics or general text",
    "contact": "a specific person's name together with a phone number, email, home address, date of birth or account/customer ID",
    "government_id": "a national ID or resident registration number, passport, driver's license, SSN or tax ID",
    "financial": "a card number, bank account or IBAN, or a specific person's transactions or debts",
    "health": "medical or health information about a specific person",
    "private_life": "a specific person's HR or disciplinary matter, legal case, criminal record, immigration status, religion, "
                    "political views, union membership, sexual orientation or family situation",
    "credential": "passwords, API keys, access tokens or private keys",
}

V2 = copy.deepcopy(V1)
V2["record"] = {"type": "noul", "instructions": "Is this text a record, form, message or document that contains information "
                                                 "identifying a real person, such as a name with contact details or an ID number?"}

VARIANTS = {"V0": V0, "V1": V1, "V2": V2}
