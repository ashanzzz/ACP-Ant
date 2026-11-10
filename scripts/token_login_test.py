# -*- coding: utf-8 -*-
"""Offline test of logging an account in with a Google refresh_token (panel: POST /panel/api/accounts/<name>/login/token).

    python3 scripts/token_login_test.py

Needs no account, network or agy (Linux only, like the panel): `agy models` is replaced by a fake. Checks what the
owner may paste, the login file that gets written (same shape as agy's own, mode 600), that a rejected token puts the
previous login back (or leaves no file), that the token never shows up in errors or the activity log, and the warning
when two accounts are logged in to the same Google account."""
import asyncio
import atexit
import json
import os
import shutil
import stat
import sys
import tempfile

os.environ["AGY_ROOT"] = tempfile.mkdtemp(prefix="acp-ant-token-test-")
atexit.register(shutil.rmtree, os.environ["AGY_ROOT"], True)
os.environ["AGY_GATEWAY_KEY"] = "test-key"
os.environ["AGY_REQUIRE_PROXY"] = "0"
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]

import acp_ant as gw  # noqa: E402
import acp_panel as panel  # noqa: E402
from fastapi import HTTPException  # noqa: E402

RT = "1//0g" + "AbC-d_9" * 14
RT2 = "1//0e" + "xYz_7-Q" * 14
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print("%s  %s%s" % ("PASS" if cond else "FAIL", name, "" if cond else "  -> " + str(detail)[:300]))


# ---------------------------------------------------------------- what the owner may paste
P = panel.parse_refresh_token
check("bare token", P(RT) == (RT, ""))
check("token with spaces and newline around it", P("  %s\n" % RT) == (RT, ""))
check("agy / Antigravity token file", P(json.dumps({"token": {"access_token": "ya29.x", "refresh_token": RT}, "auth_method": "consumer"})) == (RT, ""))
check("account-manager export (camelCase, nested list)", P(json.dumps({"accounts": [{"email": "a@b.c", "refreshToken": RT}]})) == (RT, ""))
check("one-account export {email, refresh_token}", P(json.dumps({"email": "a@b.c", "refresh_token": RT}, indent=2)) == (RT, ""))
check("same export wrapped in a list", P(json.dumps([{"email": "a@b.c", "refresh_token": RT}])) == (RT, ""))
check("refresh_token=... line", P("email=a@b.c\nrefresh_token=%s\n" % RT) == (RT, ""))
check("same token twice counts once", P(json.dumps([{"refresh_token": RT}, {"refresh_token": RT}])) == (RT, ""))
tok, why = P(json.dumps([{"refresh_token": RT}, {"refresh_token": RT2}]))
check("two different tokens refused", tok == "" and "2 个" in why, why)
tok, why = P("4/0AeanS0abc-authorization-code")
check("authorization code refused", tok == "" and "1//" in why, why)
tok, why = P("ya29.a0AfH6SMBaccess-token-not-refresh")
check("access token refused", tok == "" and "1//" in why, why)
check("empty refused", P("   ")[0] == "")
check("huge paste refused", P("x" * 60000)[0] == "")
body = json.loads(panel.token_body(RT))
check("login file has agy's shape", body == {"token": {"access_token": "", "token_type": "Bearer", "refresh_token": RT,
                                                       "expiry": "2000-01-01T00:00:00Z"}, "auth_method": "consumer"}, body)


# ---------------------------------------------------------------- the route, with a fake `agy models`
class FakeRequest:
    def __init__(self, data):
        self.data = data


async def fake_body(request):
    return request.data


panel.require = lambda request, write=False: None
panel.body_of = fake_body
panel.setup(gw.app, gw)
ACC = gw.ACCOUNTS_DIR
VERDICT = {}          # home -> (ok, output, e-mail agy would write)
SEEN = {}


async def fake_logged_in(home):
    with open(panel.token_path(home)) as f:
        SEEN[home] = (f.read(), stat.S_IMODE(os.stat(panel.token_path(home)).st_mode))
    ok, out, email = VERDICT[home]
    if ok:   # like agy: exchange the refresh token, fill in the access token and the e-mail
        d = json.loads(SEEN[home][0])
        d["token"].update({"access_token": "ya29.fresh", "expiry": "2026-11-10T12:00:00Z", "expires_in": 3599})
        d["id_token_email"] = email
        with open(panel.token_path(home), "w") as f:
            json.dump(d, f)
    return ok, out


panel.logged_in = fake_logged_in


def new_account(name):
    home = os.path.join(ACC, name)
    os.makedirs(os.path.join(home, "workspace"), exist_ok=True)
    os.makedirs(os.path.join(home, ".gemini"), exist_ok=True)
    return home


def call(name, text):
    try:
        return asyncio.run(panel.api_login_token(name, FakeRequest({"refresh_token": text})))
    except HTTPException as e:
        return e


h1 = new_account("g1")
VERDICT[h1] = (True, "gemini-4-argon-high\n", "owner@example.com")
r = call("g1", json.dumps({"refresh_token": RT}))
check("good token accepted", isinstance(r, dict) and r.get("ok"), r)
check("e-mail returned", isinstance(r, dict) and r.get("email") == "owner@example.com", r)
check("no other account with that e-mail", isinstance(r, dict) and r.get("same_email_as") == [], r)
check("written file is what agy expects", json.loads(SEEN[h1][0]) == json.loads(panel.token_body(RT)))
check("written file is mode 600", SEEN[h1][1] == 0o600, oct(SEEN[h1][1]))
check("no temp file left", not os.path.exists(panel.token_path(h1) + ".tmp"))

h2 = new_account("g2")
VERDICT[h2] = (True, "gemini-4-argon-high\n", "OWNER@example.com")
r = call("g2", RT)
check("same Google account on two accounts is reported", isinstance(r, dict) and r.get("same_email_as") == ["g1"], r)

# rejected token on an account that was logged in: the previous login comes back byte for byte
with open(panel.token_path(h1), "rb") as f:
    before = f.read()
VERDICT[h1] = (False, "Fetching available models...\nError: Please sign in to view available models.", "")
r = call("g1", RT2)
check("rejected token -> 400", isinstance(r, HTTPException) and r.status_code == 400, r)
check("message says the token cannot be used", isinstance(r, HTTPException) and "用不了" in r.detail, getattr(r, "detail", r))
with open(panel.token_path(h1), "rb") as f:
    check("previous login restored", f.read() == before)
check("restored file is mode 600", stat.S_IMODE(os.stat(panel.token_path(h1)).st_mode) == 0o600)

# rejected token on a new account: no login file is left behind
h3 = new_account("g3")
VERDICT[h3] = (False, "Error: Please sign in to view available models.", "")
r = call("g3", RT2)
check("new account + rejected token -> no login file", isinstance(r, HTTPException) and not os.path.exists(panel.token_path(h3)), r)

# proxy trouble is told apart from a bad token
VERDICT[h3] = (False, "Error: dial tcp: proxyconnect tcp: connection refused", "")
r = call("g3", RT2)
check("network problem reported as such", isinstance(r, HTTPException) and "代理" in r.detail, getattr(r, "detail", r))

r = call("g3", "not a token")
check("garbage refused before touching files", isinstance(r, HTTPException) and r.status_code == 400 and not os.path.exists(panel.token_path(h3)), r)
r = call("nobody", RT)
check("unknown account -> 404", isinstance(r, HTTPException) and r.status_code == 404, r)
r = call("../g1", RT)
check("bad account name -> 400", isinstance(r, HTTPException) and r.status_code == 400, r)

errors = " ".join(str(getattr(x, "detail", "")) for x in [call("g3", RT2), call("g3", "x")])
log = json.dumps(list(gw.EVENTS), ensure_ascii=False)
check("token never in errors or the activity log", RT not in errors + log and RT2 not in errors + log)

os.environ["AGY_REQUIRE_PROXY"] = "1"
gw.REQUIRE_PROXY = True
r = call("g2", RT)
check("proxy required and missing -> 400", isinstance(r, HTTPException) and "代理" in r.detail, getattr(r, "detail", r))

print("\n%d/%d passed" % (sum(results), len(results)))
sys.exit(0 if all(results) else 1)
