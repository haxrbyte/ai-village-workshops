"""
mailmate — the module every Workshop 1 notebook imports.

    from mailmate import (connect, ask, drop, mail, sweep, actions, leaks,
                          check, reset, human_view, register_tool)
    connect(TEAM, LAB)

Thin HTTP wrappers, nothing clever. The signatures are fixed by the notebooks;
they were not invented here. Everything returns something printable, because
every notebook cell wraps these in print().
"""

import json
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["connect", "ask", "drop", "mail", "sweep", "actions", "leaks",
           "check", "reset", "human_view", "register_tool", "whoami"]

_TEAM: str | None = None
_LAB = "http://northwind.local"
TIMEOUT = 180          # inference under load can be slow; better than a timeout


class LabError(RuntimeError):
    pass


def _need_team() -> str:
    if not _TEAM:
        raise LabError("Call connect(TEAM, LAB) first — see the top cell.")
    if _TEAM == "CHANGE_ME":
        raise LabError(
            "TEAM is still CHANGE_ME. Set it to your team name in the first "
            "cell and re-run — this is the single most common reason nothing "
            "works."
        )
    return _TEAM


def _url(path: str) -> str:
    return f"{_LAB}/api/{urllib.parse.quote(_need_team())}{path}"


def _req(method: str, path: str, payload=None, timeout=TIMEOUT):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        _url(path), data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise LabError(f"{method} {path} -> HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise LabError(
            f"Can't reach the lab at {_LAB} ({e.reason}). Check the URL, and "
            f"that you're on the AIVILLAGE network."
        ) from None


# --------------------------------------------------------------------------
def connect(team: str, lab: str = "http://northwind.local") -> str:
    """Point this notebook at your own assistant instance."""
    global _TEAM, _LAB
    _TEAM, _LAB = team, lab.rstrip("/")
    if team == "CHANGE_ME":
        raise LabError("TEAM is still CHANGE_ME — set it before running this.")
    info = _req("POST", "/connect", {}, timeout=20)
    return f"Connected as {team}. Your assistant: {info.get('chat')}"


def ask(message: str) -> str:
    """Say something to the assistant. Returns its reply."""
    return _req("POST", "/ask", {"message": message})["reply"]


def drop(filename: str, content: str) -> str:
    """Put a document in the assistant's workspace."""
    _req("POST", "/drop", {"filename": filename, "content": content}, timeout=30)
    return f"Dropped {filename} ({len(content)} bytes)"


def mail(sender: str, subject: str, body: str) -> str:
    """Put a message in the assistant's inbox. Nobody has read it yet."""
    r = _req("POST", "/mail", {"sender": sender, "subject": subject, "body": body},
             timeout=30)
    return f"Delivered to inbox ({r.get('inbox')} message(s) waiting)"


def sweep() -> str:
    """Run the autopilot once. No human asks it anything — that's the point."""
    r = _req("POST", "/sweep", {})
    lines = [f"autopilot ran, {len(r.get('actions', []))} tool call(s)"]
    for a in r.get("actions", []):
        lines.append(f"  {a['tool']}({json.dumps(a['args'])})")
    lines.append("")
    lines.append(r.get("reply", ""))
    return "\n".join(lines)


def actions() -> str:
    """What the assistant DID on its last turn, as opposed to what it said."""
    log = _req("GET", "/actions", timeout=20)
    if not log:
        return "(no tool calls on the last turn)"
    out = []
    for a in log:
        out.append(f"{a['tool']}({json.dumps(a['args'])})")
        out.append(f"    -> {a['result'][:220]}")
    return "\n".join(out)


def leaks() -> str:
    """What the listener received. If this is empty, nothing left the box."""
    hits = _req("GET", "/leaks", timeout=20)
    if not hits:
        return "(listener has seen nothing from you yet)"
    out = [f"{len(hits)} request(s) reached the listener:"]
    for h in hits[:10]:
        out.append(f"  {h.get('data','')[:90]}")
    return "\n".join(out)


def check(n) -> str:
    """Grade one exercise. n is 1-7, or '5-bonus'."""
    r = _req("GET", f"/check/{urllib.parse.quote(str(n))}", timeout=30)
    mark = "PASS" if r["passed"] else "not yet"
    out = [f"[{mark}] exercise {r['exercise']}: {r['detail']}"]
    if not r["passed"] and r.get("hint"):
        out.append(f"   hint: {r['hint']}")
    return "\n".join(out)


def reset() -> str:
    """Wipe your tenant and start clean. Your scoreboard hits are unaffected."""
    _req("POST", "/reset", {}, timeout=30)
    return "Workspace reset — documents, inbox and tools cleared."


def human_view(filename: str) -> str:
    """What a human reviewer sees, versus what the model sees.

    Exercise 3 lives here: if these two differ, your payload is invisible to
    the person doing the reviewing.
    """
    r = _req("GET", f"/human_view?filename={urllib.parse.quote(filename)}",
             timeout=20)
    out = [
        f"--- {r['filename']} as a HUMAN sees it "
        f"({r['human_sees_bytes']} of {r['model_sees_bytes']} bytes) ---",
        r["human_sees"],
        "",
    ]
    if r["hidden_comment"]:
        out.append("  (an HTML comment is present and invisible above)")
    if r["invisible_chars"]:
        out.append(f"  ({r['invisible_chars']} invisible character(s) present)")
    return "\n".join(out)


def register_tool(name: str, description: str, returns: str = "",
                  rug_pull_after: int | None = None,
                  rug_pull_description: str = "") -> str:
    """Add a tool to the assistant's catalogue.

    Only the NAME and DESCRIPTION reach the model. That's the exercise.

    `rug_pull_after=N` plus `rug_pull_description=...` is exercise 6 step 3: the
    tool serves `description` until it has been CALLED N times, then serves
    `rug_pull_description` instead. Re-registering the same name resets the
    counter.
    """
    payload = {"name": name, "description": description, "returns": returns}
    if rug_pull_after is not None:
        payload["rug_pull_after"] = int(rug_pull_after)
        payload["rug_pull_description"] = rug_pull_description
    r = _req("POST", "/tools", payload, timeout=20)
    out = f"Registered {name}. Tools now: {', '.join(r['tools'])}"
    if r.get("armed"):
        out += f"\n  rug pull armed: description changes after {rug_pull_after} call(s)."
    return out


def whoami() -> str:
    return f"team={_TEAM} lab={_LAB}"
