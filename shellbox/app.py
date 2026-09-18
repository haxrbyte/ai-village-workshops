"""
shellbox — the lab's own reverse-shell catcher, for Workshop 2 exercise 7.

WHY THIS EXISTS
---------------
Exercise 7 is a reverse shell: the payload connects back to a listener the
attendee is running, and they get a shell inside the victim container. In the
notebook the attendee opens that socket themselves. A BROWSER CANNOT LISTEN ON
A PORT, so the web version had no way to do the exercise at all.

So the lab listens on their behalf. The payload connects here instead of to a
laptop; this service holds the socket and the web page drives it. The attendee
gets a genuine shell in the victim container — the same capability the notebook
gives them, reached differently. Nothing is simulated.

Deliberately its OWN service, not part of the listener: the listener is the
feedback layer for both workshops and is protected above everything else. If
this crashes, only exercise 7's web path is affected.

Scope: one session per team, on the lab's isolated network, against a container
that exists to be popped and is rebuilt after the con.
"""

import os
import re
import socket
import threading
import time

from fastapi import FastAPI, HTTPException

app = FastAPI(title="shellbox", docs_url=None, redoc_url=None)

TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
HOST = os.environ.get("SHELLBOX_HOST", "shellbox")
PORT_BASE = int(os.environ.get("SHELLBOX_PORT_BASE", "9100"))
PORT_SPAN = int(os.environ.get("SHELLBOX_PORT_SPAN", "40"))
IDLE_SECONDS = 900

_lock = threading.Lock()
_sessions: dict[str, dict] = {}       # team -> session


def _reap() -> None:
    """Drop sessions nobody has touched in a while, so ports come back."""
    now = time.time()
    for team, s in list(_sessions.items()):
        if now - s["touched"] > IDLE_SECONDS:
            _close(team)


def _close(team: str) -> None:
    s = _sessions.pop(team, None)
    if not s:
        return
    for k in ("conn", "sock"):
        try:
            if s.get(k):
                s[k].close()
        except Exception:
            pass


def _accept_loop(team: str, sock: socket.socket) -> None:
    """One connection per session. The payload dials in exactly once.

    The listener must POLL rather than block forever in accept(): most sessions
    are opened and never dialled back to (the attendee opens a listener but the
    victim never loads the model), and a bare accept() would pin the thread —
    and the port — until the container restarted. Closing the socket from
    _close() does NOT interrupt a blocking accept() on Linux, so the port leaked
    permanently and the 40-port span drained. Instead we time out every second
    and stop the moment our session is gone or has been replaced, releasing the
    port immediately.
    """
    sock.settimeout(1.0)
    try:
        while True:
            with _lock:
                s = _sessions.get(team)
                if not s or s.get("sock") is not sock:
                    return                     # closed, reaped, or re-opened
            try:
                conn, addr = sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return                         # socket closed under us
            conn.settimeout(2.0)
            with _lock:
                s = _sessions.get(team)
                if not s or s.get("sock") is not sock:
                    conn.close()
                    return
                s["conn"] = conn
                s["peer"] = f"{addr[0]}:{addr[1]}"
                s["connected_at"] = time.time()
                s["touched"] = time.time()
            return
    finally:
        try:
            sock.close()
        except Exception:
            pass


@app.get("/health")
@app.get("/shell/health")   # nginx proxies /shell/* through unchanged
def health():
    return {"ok": True, "service": "shellbox", "sessions": len(_sessions)}


@app.post("/shell/open")
def open_session(body: dict):
    """Allocate a port and start listening. Returns what to put in the payload."""
    team = (body or {}).get("team", "")
    if not TOKEN.match(team):
        raise HTTPException(400, "team must match [A-Za-z0-9._-]{1,64}")
    with _lock:
        _reap()
        _close(team)                                   # restart is idempotent
        used = {s["port"] for s in _sessions.values()}
        # Walk the span and BIND the first port that actually takes. A port can
        # be free of any tracked session yet still held for up to a second by a
        # just-closed session's accept thread winding down (see _accept_loop) —
        # binding blind would 500 with EADDRINUSE on a rapid re-open. Skip it
        # and try the next; only a genuinely full span is a 503.
        sock = port = None
        for p in range(PORT_BASE, PORT_BASE + PORT_SPAN):
            if p in used:
                continue
            cand = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            cand.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                cand.bind(("0.0.0.0", p))
                cand.listen(1)
            except OSError:
                cand.close()
                continue
            sock, port = cand, p
            break
        if sock is None:
            raise HTTPException(503, "no free ports — ask an instructor")
        _sessions[team] = {"port": port, "sock": sock, "conn": None, "peer": None,
                           "connected_at": None, "touched": time.time()}
    threading.Thread(target=_accept_loop, args=(team, sock), daemon=True).start()
    # The payload runs INSIDE the victim container, where only Docker's DNS
    # resolves — so it must dial the service name, never localhost.
    return {"ok": True, "team": team, "host": HOST, "port": port,
            "listening": True}


@app.get("/shell/status")
def status(team: str):
    if not TOKEN.match(team):
        raise HTTPException(400, "bad team")
    s = _sessions.get(team)
    if not s:
        return {"open": False, "connected": False}
    s["touched"] = time.time()
    return {"open": True, "connected": s["conn"] is not None,
            "host": HOST, "port": s["port"], "peer": s["peer"],
            "waited": round(time.time() - (s["connected_at"] or s["touched"]), 1)}


@app.post("/shell/exec")
def run(body: dict):
    """Send one command down the socket and read what comes back."""
    team = (body or {}).get("team", "")
    cmd = (body or {}).get("cmd", "")
    if not TOKEN.match(team):
        raise HTTPException(400, "bad team")
    s = _sessions.get(team)
    if not s or not s["conn"]:
        raise HTTPException(409, "nothing has connected back yet")
    if not cmd.strip():
        raise HTTPException(400, "empty command")
    s["touched"] = time.time()
    conn = s["conn"]
    try:
        conn.sendall(cmd.rstrip("\n").encode() + b"\n")
    except Exception as e:
        _close(team)
        raise HTTPException(410, f"the shell went away: {type(e).__name__}")

    out, deadline = b"", time.time() + 3.0
    while time.time() < deadline:
        try:
            chunk = conn.recv(65536)
            if not chunk:
                break
            out += chunk
            deadline = time.time() + 0.35      # keep reading while it's talking
        except socket.timeout:
            break
        except Exception:
            break
    return {"ok": True, "output": out.decode(errors="replace")[-8000:]}


@app.post("/shell/close")
def close(body: dict):
    team = (body or {}).get("team", "")
    if not TOKEN.match(team):
        raise HTTPException(400, "bad team")
    with _lock:
        _close(team)
    return {"ok": True}
