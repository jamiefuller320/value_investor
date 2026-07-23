# CURSOR_API_KEY verification handover

Use this after refreshing the cloud secret and starting a **new** Cloud Agent
(secrets do not update mid-run).

## Goal

Confirm `CURSOR_API_KEY` authenticates with Cursor’s Cloud Agents API so SDK
calls (`ftse-verify-key`, research, deep analysis, gap-fill) can proceed.

## Context from prior shell (`bc-53006131`)

- Secret was injected (`crsr_` + 64 hex, len 69) but `/v0/me` returned
  `401 Invalid User API Key` (same message as a fake key).
- Not a missing-header bug: SDK sends bridge `Authorization` + body
  `options.apiKey`; raw REST with Bearer/Basic also failed.
- User API Keys UI was hard to find; Dashboard → API Keys often only shows
  `admin:*`. Prefer a User API Key when the UI exposes one.
- Fingerprint of the **old** rejected key (for “did the secret change?”):
  `sha256` prefix `ff143faf1516`.

## New-agent prompt (paste as-is)

```text
Handover: verify refreshed CURSOR_API_KEY for FTSE value_investor.

Follow docs/ops/cursor-api-key-handover.md exactly.

1. Install package if needed: pip3 install -e ".[dev]" and ensure ~/.local/bin is on PATH.
2. Run the checklist commands in that doc (fingerprint, ftse-verify-key, raw /v0/me + /v1/me, SDK Cursor.me).
3. Report PASS/FAIL with the command outputs (redact the key; show only prefix crsr_…, len, sha256_12).
4. If PASS and --list-models works, stop unless asked to run research/gap-fill.
5. If FAIL, do not invent fixes — report which step failed and whether sha256_12 still equals ff143faf1516 (old key) or changed.
```

## Checklist (run in order)

### 0) Environment

```bash
export PATH="$HOME/.local/bin:$PATH"
cd /workspace
pip3 install -e ".[dev]" >/tmp/vi-install.log 2>&1 || pip3 install -e . >/tmp/vi-install.log 2>&1
tail -5 /tmp/vi-install.log
```

### 1) Secret injected and changed?

```bash
python3 <<'PY'
import os, hashlib, re
k = os.environ.get("CURSOR_API_KEY") or ""
s = k.strip()
print("present:", bool(k))
print("len:", len(k), "stripped_len:", len(s))
print("prefix:", (s[:5] + "...") if s else None)
print("format_ok:", bool(re.fullmatch(r"crsr_[0-9a-f]{64}", s)))
print("has_whitespace:", bool(re.search(r"\s", k)))
print("sha256_12:", hashlib.sha256(s.encode()).hexdigest()[:12] if s else None)
print("changed_from_old_ff143faf1516:", (hashlib.sha256(s.encode()).hexdigest()[:12] != "ff143faf1516") if s else None)
print("injected:", os.environ.get("CLOUD_AGENT_INJECTED_SECRET_NAMES"))
PY
```

**Expect:** `present True`, `format_ok True`, `changed_from_old_ff143faf1516 True`.  
If sha256 still `ff143faf1516`, the new agent still has the old secret — stop and re-check cloud secrets / start another new agent.

### 2) Project CLI (primary gate)

```bash
ftse-verify-key
echo exit=$?
ftse-verify-key --list-models
echo exit=$?
```

**PASS:** prints `Authentication succeeded` and exit `0`.  
**FAIL:** `Invalid User API Key` / exit `1`.

### 3) Raw REST `/v0/me` and `/v1/me`

```bash
python3 <<'PY'
import os, base64, httpx
key = os.environ["CURSOR_API_KEY"].strip()
basic = base64.b64encode(f"{key}:".encode()).decode()
for label, url, headers in [
    ("Bearer /v0/me", "https://api.cursor.com/v0/me", {"Authorization": f"Bearer {key}"}),
    ("Basic /v0/me", "https://api.cursor.com/v0/me", {"Authorization": f"Basic {basic}"}),
    ("Bearer /v1/me", "https://api.cursor.com/v1/me", {"Authorization": f"Bearer {key}"}),
    ("Basic /v1/me", "https://api.cursor.com/v1/me", {"Authorization": f"Basic {basic}"}),
]:
    r = httpx.get(url, headers=headers, timeout=30)
    print(label, r.status_code, r.text[:200])
PY
```

**PASS:** HTTP `200` with `apiKeyName` / account fields.  
**FAIL:** HTTP `401` `Invalid User API Key`.

### 4) SDK path (same stack as research agents)

```bash
python3 <<'PY'
import os, json, httpx
from cursor_sdk import Cursor
from cursor_sdk.errors import AuthenticationError

key = os.environ["CURSOR_API_KEY"].strip()
captured = []
orig = httpx.Client.send

def logged(self, request, *a, **k):
    import json as _json
    body = _json.loads(request.content.decode()) if request.content else {}
    auth = request.headers.get("Authorization", "")
    api_key = (body.get("options") or {}).get("apiKey")
    captured.append({
        "url": str(request.url).split("?")[0],
        "authorization_present": bool(auth),
        "auth_is_user_key": auth.endswith(key) if auth else False,
        "body_apiKey_len": len(api_key) if isinstance(api_key, str) else None,
        "body_apiKey_matches_env": api_key == key,
    })
    return orig(self, request, *a, **k)

httpx.Client.send = logged
try:
    user = Cursor.me(api_key=key)
    print("SDK OK", {
        "api_key_name": user.api_key_name,
        "email": user.user_email,
    })
except AuthenticationError as e:
    print("SDK FAIL", e.code, e)
except Exception as e:
    print("SDK ERR", type(e).__name__, e)
print("wire:", json.dumps(captured, indent=2))
PY
```

**PASS:** `SDK OK` with key/account metadata; wire shows `authorization_present true`, `body_apiKey_matches_env true`.  
Note: `auth_is_user_key` is expected **false** (bridge token in `Authorization`, user key in body).

### 5) Optional smoke (only if steps 2–4 PASS)

```bash
# Cheapest confirmation that Agent.create auth works — will start a tiny local agent.
# Skip unless you explicitly want a live agent create.
python3 <<'PY'
import os
from cursor_sdk import Agent, AgentOptions, LocalAgentOptions, CursorAgentError
try:
    agent = Agent.create(AgentOptions(
        api_key=os.environ["CURSOR_API_KEY"].strip(),
        model="composer-2.5",
        local=LocalAgentOptions(cwd="/workspace"),
    ))
    print("Agent.create OK", getattr(agent, "id", None) or agent)
    try:
        agent.close()
    except Exception:
        pass
except Exception as e:
    print("Agent.create FAIL", type(e).__name__, e)
PY
```

## Verdict template

```text
CURSOR_API_KEY verification: PASS|FAIL
sha256_12: <12 hex> (changed_from_old: yes|no)
ftse-verify-key: exit=<n>
/v0/me Bearer: <status>
/v1/me Bearer: <status>
SDK Cursor.me: OK|FAIL
notes: <one line>
```

## If FAIL after a real refresh

1. Confirm sha256_12 changed (secret actually updated in the new pod).
2. Confirm the key was created as a **User** API key (not only `admin:*` Admin API).
3. Re-copy the key with no spaces/newlines; replace the cloud secret; new agent again.
4. Do not chase Authorization-header bugs unless wire capture shows `authorization_present false` or `body_apiKey_matches_env false`.
