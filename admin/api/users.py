"""Developer sign-ins for --auth jwt hooks: the stack's Developers user pool (DEV_POOL_ID), managed from the console.

Invites go out by email from Cognito (temporary password). Groups are Cognito groups: they ride in the ID token
(cognito:groups), so the guard logs them with every decision. Not available locally or with an external IdP (devIssuer),
where users are managed in the IdP.
"""
import re

from common import LOCAL, env, aws

DEV_POOL_ID = env("DEV_POOL_ID")
INSTALL = {k: env(v) for k, v in (("api_url", "GUARD_API_URL"), ("client_id", "DEV_CLIENT_ID"),
                                    ("authorize_url", "DEV_AUTHORIZE_URL"), ("token_url", "DEV_TOKEN_URL"), ("issuer", "DEV_ISSUER"))}
EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
GROUP = re.compile(r"^[^\s,]{1,64}$")
MAX_INVITES = 50   # Cognito's own email sender allows 50 messages a day

MESSAGES = {
    "en": {"bad_email": "Not an email address: {v}", "bad_group": "Group names are 1-64 characters without spaces or commas: {v}",
           "exists": "already has a sign-in", "too_many": "Invite at most {n} people at a time", "no_group": "No such group: {v}",
           "not_invited": "Only people who have not signed in yet can get the invitation again"},
    "ko": {"bad_email": "이메일 주소가 아닙니다: {v}", "bad_group": "그룹 이름은 공백·쉼표 없이 1-64자입니다: {v}",
           "exists": "이미 계정이 있습니다", "too_many": "한 번에 최대 {n}명까지 초대할 수 있습니다", "no_group": "없는 그룹입니다: {v}",
           "not_invited": "아직 로그인하지 않은 사람에게만 초대를 다시 보낼 수 있습니다"},
}


def _m(lang, key, **kw):
    return MESSAGES.get(lang, MESSAGES["en"])[key].format(**kw)


def install_command():
    i = INSTALL
    if not i["api_url"]:
        return None
    auth = f"--issuer {i['issuer']}" if i["issuer"] else f"--authorize-url {i['authorize_url']} --token-url {i['token_url']}"
    return f"client/install.sh --api-url {i['api_url']} --client-id {i['client_id']} {auth}"


def _cog():
    return aws("cognito-idp")


def _attr(u, name):
    return next((a["Value"] for a in u.get("Attributes", []) if a["Name"] == name), "")


def groups():
    out, kw = [], {"UserPoolId": DEV_POOL_ID, "Limit": 60}
    while True:
        r = _cog().list_groups(**kw)
        out += [{"name": g["GroupName"], "description": g.get("Description", "")} for g in r["Groups"]]
        if not r.get("NextToken"):
            return sorted(out, key=lambda g: g["name"].lower())
        kw["NextToken"] = r["NextToken"]


def _members(group):
    names, kw = [], {"UserPoolId": DEV_POOL_ID, "GroupName": group, "Limit": 60}
    while True:
        r = _cog().list_users_in_group(**kw)
        names += [u["Username"] for u in r["Users"]]
        if not r.get("NextToken"):
            return names
        kw["NextToken"] = r["NextToken"]


def status():
    if LOCAL or not DEV_POOL_ID:
        return {"available": False, "reason": "local" if LOCAL else ("idp" if INSTALL["issuer"] else "none"),
                "issuer": INSTALL["issuer"], "install": install_command()}
    gs = groups()
    member_of = {}
    for g in gs:
        for name in _members(g["name"]):
            member_of.setdefault(name, []).append(g["name"])
    users, kw = [], {"UserPoolId": DEV_POOL_ID, "Limit": 60}
    while len(users) < 2000:
        r = _cog().list_users(**kw)
        for u in r["Users"]:
            state = "disabled" if not u.get("Enabled", True) else "invited" if u["UserStatus"] == "FORCE_CHANGE_PASSWORD" else "active"
            users.append({"username": u["Username"], "email": _attr(u, "email"), "state": state,
                          "created": u["UserCreateDate"].isoformat(timespec="seconds"), "groups": sorted(member_of.get(u["Username"], []))})
        if not r.get("NextToken"):
            break
        kw["NextToken"] = r["NextToken"]
    for g in gs:
        g["members"] = sum(g["name"] in u["groups"] for u in users)
    return {"available": True, "users": sorted(users, key=lambda u: u["email"].lower()), "groups": gs,
            "install": install_command(), "max_invites": MAX_INVITES}


def _known_groups(names, lang):
    known = {g["name"] for g in groups()}
    for n in names:
        if n not in known:
            raise ValueError(_m(lang, "no_group", v=n))
    return names


def invite(emails, group_names, lang="en"):
    """Returns per-address results; one address failing does not stop the others."""
    emails = [e.strip() for e in emails if str(e).strip()]
    if len(emails) > MAX_INVITES:
        raise ValueError(_m(lang, "too_many", n=MAX_INVITES))
    for e in emails:
        if not EMAIL.match(e):
            raise ValueError(_m(lang, "bad_email", v=e))
    _known_groups(group_names, lang)
    results = []
    for e in emails:
        try:
            u = _cog().admin_create_user(UserPoolId=DEV_POOL_ID, Username=e, DesiredDeliveryMediums=["EMAIL"],
                                         UserAttributes=[{"Name": "email", "Value": e}, {"Name": "email_verified", "Value": "true"}])["User"]
            for g in group_names:
                _cog().admin_add_user_to_group(UserPoolId=DEV_POOL_ID, Username=u["Username"], GroupName=g)
            results.append({"email": e, "ok": True})
        except _cog().exceptions.UsernameExistsException:
            results.append({"email": e, "ok": False, "error": _m(lang, "exists")})
    return results


def act(username, action, lang="en"):
    """resend | disable | enable | delete. Disabling and deleting also end the user's sessions (refresh tokens)."""
    c = _cog()
    if action == "resend":
        u = c.admin_get_user(UserPoolId=DEV_POOL_ID, Username=username)
        if u["UserStatus"] != "FORCE_CHANGE_PASSWORD":
            raise ValueError(_m(lang, "not_invited"))
        c.admin_create_user(UserPoolId=DEV_POOL_ID, Username=username, MessageAction="RESEND", DesiredDeliveryMediums=["EMAIL"])
    elif action == "disable":
        c.admin_user_global_sign_out(UserPoolId=DEV_POOL_ID, Username=username)
        c.admin_disable_user(UserPoolId=DEV_POOL_ID, Username=username)
    elif action == "enable":
        c.admin_enable_user(UserPoolId=DEV_POOL_ID, Username=username)
    elif action == "delete":
        c.admin_user_global_sign_out(UserPoolId=DEV_POOL_ID, Username=username)
        c.admin_delete_user(UserPoolId=DEV_POOL_ID, Username=username)
    else:
        raise ValueError(f"unknown action {action}")


def set_groups(username, wanted, lang="en"):
    """Make the user a member of exactly these groups. Returns (added, removed)."""
    _known_groups(wanted, lang)
    have = {g["GroupName"] for g in _cog().admin_list_groups_for_user(UserPoolId=DEV_POOL_ID, Username=username, Limit=60)["Groups"]}
    added, removed = sorted(set(wanted) - have), sorted(have - set(wanted))
    for g in added:
        _cog().admin_add_user_to_group(UserPoolId=DEV_POOL_ID, Username=username, GroupName=g)
    for g in removed:
        _cog().admin_remove_user_from_group(UserPoolId=DEV_POOL_ID, Username=username, GroupName=g)
    return added, removed


def create_group(name, description="", lang="en"):
    if not GROUP.match(name or ""):
        raise ValueError(_m(lang, "bad_group", v=name))
    _cog().create_group(UserPoolId=DEV_POOL_ID, GroupName=name, Description=str(description)[:200])


def delete_group(name):
    _cog().delete_group(UserPoolId=DEV_POOL_ID, GroupName=name)   # members stay; they just leave the group
