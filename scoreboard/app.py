"""
Scoreboard — the big-screen view for both workshops.

Reads hits from the listener over HTTP rather than opening hits.db directly.
A read-only bind mount of a WAL database fails when SQLite needs to recover
the -wal file, and that failure would land during a workshop.

Route note: the board fetches /scores and /feed, NOT /api/*. nginx routes
/api/* to mailmate, so anything under /api here would be unreachable through
the proxy.
"""

import json
import os
import pathlib
import urllib.error
import urllib.request

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

app = FastAPI(title="scoreboard", docs_url=None, redoc_url=None)

LISTENER = os.environ.get("LISTENER_URL", "http://listener:8002")
STATIC = pathlib.Path(__file__).parent / "static"


def upstream(path: str):
    try:
        with urllib.request.urlopen(f"{LISTENER}{path}", timeout=4) as r:
            return JSONResponse(content=json.loads(r.read()))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return JSONResponse(status_code=503, content={"error": "listener unreachable", "detail": str(e)})


def upstream_post(path: str):
    try:
        req = urllib.request.Request(f"{LISTENER}{path}", method="POST")
        with urllib.request.urlopen(req, timeout=4) as r:
            return JSONResponse(content=json.loads(r.read()))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        return JSONResponse(status_code=503, content={"error": "listener unreachable", "detail": str(e)})


@app.get("/health")
def health():
    return {"ok": True, "service": "scoreboard"}


@app.get("/scores")
def scores():
    return upstream("/api/scores")


@app.get("/feed")
def feed():
    return upstream("/feed?limit=25")


@app.post("/archive")
def archive(undo: bool = False):
    """The board's Clear button.

    NOT /api/archive: nginx routes /api/* to mailmate, so anything under /api
    is unreachable through the proxy — same trap the module docstring warns
    about for /scores and /feed. This path falls through nginx's catch-all,
    which lands here.
    """
    return upstream_post(f"/api/archive?undo={'true' if undo else 'false'}")


@app.get("/stats")
def stats():
    return upstream("/api/stats")


@app.get("/")
@app.get("/scoreboard")
@app.get("/board")
def board():
    """All 14 attendee notebooks print `{LAB}/scoreboard` as the place to look.

    Serving the board there as well as at / is one line; correcting the URL in
    fourteen notebooks is fourteen chances to miss one.
    """
    # Substituted at request time, not baked. The header used to hardcode
    # "northwind.local · a hardcoded IP" — a name attendees cannot resolve on
    # conference wifi, beside an IP from a network that no longer exists. This
    # is the BIG SCREEN in the room, so it was telling everyone the wrong
    # address. LAB_URL was already declared in docker-compose and .env and was
    # simply never read; now it is. `make qr` keeps .env in step with the QR,
    # so the board, the slides and the printed cards cannot disagree.
    url = os.environ.get("LAB_URL", "http://northwind.local").rstrip("/")
    host = url.split("://", 1)[-1]
    html = (STATIC / "board.html").read_text()
    html = html.replace("__LAB_URL__", url).replace("__LAB_HOST__", host)
    return HTMLResponse(html)
