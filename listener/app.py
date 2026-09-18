"""
Listener — the feedback layer. Protect this above everything else.

Both workshops write here:
  Workshop 2  GET /pwned?team=X&level=N        payload fired inside victim bot
  Workshop 1  GET /img/<data>.png              chat pane fetched a remote image

Without this service both workshops are thirty people quietly failing, so it
has no dependencies beyond SQLite and it starts before anything else.
"""

import base64
import json
import os
import pathlib
import re
import sqlite3
import threading
import time
import urllib.request
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import Response


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="listener", docs_url=None, redoc_url=None, lifespan=lifespan)

DATA = pathlib.Path(os.environ.get("LISTENER_DATA", "/data"))
DB = DATA / "hits.db"
FLAGS = DATA / "flags.json"
HUB_URL = os.environ.get("HUB_URL", "http://hub:8000")

TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# 1x1 transparent PNG. The chat pane renders this; what matters is the request.
PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)

_lock = threading.Lock()


# --------------------------------------------------------------------------
# Storage
# --------------------------------------------------------------------------
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with db() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            """CREATE TABLE IF NOT EXISTS hits (
                 id       INTEGER PRIMARY KEY AUTOINCREMENT,
                 ts       REAL    NOT NULL,
                 team     TEXT    NOT NULL,
                 kind     TEXT    NOT NULL,   -- beacon | exfil
                 -- TEXT, not INTEGER: Workshop 2 exercise 4 beacons at
                 -- level=4a and level=4b. An INTEGER column plus an int-typed
                 -- route parameter made those beacons 422 and vanish.
                 level    TEXT    DEFAULT '0',
                 data     TEXT,
                 ua       TEXT,
                 ip       TEXT,
                 archived INTEGER DEFAULT 0
               )"""
        )
        # WHICH WORKSHOP — added 12 Sept 2026. Both workshops beacon through
        # /pwned with a bare number, so Workshop 1 exercise 3 and Workshop 2
        # level 3 were indistinguishable on the board: it showed "level 3" for
        # both and the room could not tell which session a team was in.
        #
        # ADD COLUMN rather than a new table, because this database is live and
        # holds the scoreboard. Existing rows default to '2'; the backfill then
        # corrects the ones we can know for certain, which is every exfil —
        # /img/<flag>.png is Workshop 1 BY CONSTRUCTION, nothing else uses it.
        # Historical beacons stay '2' and that is accepted: the board is cleared
        # before the sessions anyway (`make boardclear`).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(hits)")}
        if "ws" not in cols:
            conn.execute("ALTER TABLE hits ADD COLUMN ws TEXT DEFAULT '2'")
            conn.execute("UPDATE hits SET ws='1' WHERE kind='exfil'")

        conn.execute("CREATE INDEX IF NOT EXISTS hits_ts   ON hits(ts DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS hits_team ON hits(team)")


def record(team: str, kind: str, level: str = "0", data: str = "", ua: str = "", ip: str = "", ws: str = "2") -> int:
    with _lock, db() as conn:
        cur = conn.execute(
            "INSERT INTO hits (ts,team,kind,level,data,ua,ip,ws) VALUES (?,?,?,?,?,?,?,?)",
            (time.time(), team, kind, str(level)[:8], data[:512], ua[:256], ip[:64],
             "1" if str(ws) == "1" else "2"),
        )
        return cur.lastrowid


# --------------------------------------------------------------------------
# Team attribution.
#
# Workshop 2 beacons carry ?team= explicitly. Workshop 1 exfil doesn't — the
# URL carries the tenant's unique flag, raw or encoded depending on which
# exercise built the payload. MailMate writes {flag: team} into flags.json on
# tenant creation; we match against it here.
# --------------------------------------------------------------------------
_flags_cache: tuple[float, dict] | None = None


def flags() -> dict:
    global _flags_cache
    if not FLAGS.exists():
        return {}
    mtime = FLAGS.stat().st_mtime
    if _flags_cache is None or _flags_cache[0] != mtime:
        try:
            _flags_cache = (mtime, json.loads(FLAGS.read_text()))
        except json.JSONDecodeError:
            return {}
    return _flags_cache[1]


def decodings(data: str) -> list[str]:
    """Exercises 3 and 5 encode differently. Try the obvious ones."""
    out = [data]
    for pad in ("", "=", "=="):
        for dec in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                out.append(dec(data + pad).decode("utf-8", "replace"))
            except Exception:
                pass
    try:  # percent-encoding, in case the payload used it
        from urllib.parse import unquote

        out.append(unquote(data))
    except Exception:
        pass
    return out


def known_teams() -> set[str]:
    """Teams we've already seen, from flags.json and from prior hits."""
    names = set(flags().values())
    try:
        with db() as conn:
            for r in conn.execute(
                    "SELECT DISTINCT team FROM hits WHERE team != 'UNKNOWN'"):
                names.add(r["team"])
    except Exception:
        pass
    return names


def team_for(data: str) -> str:
    """Attribute an exfil hit.

    Two mechanisms, both needed. The FLAG is what exercises 4-7 exfiltrate, but
    exercise 5's warm-up URL is literally {TEAM}-warmup.png — no flag in sight.
    Matching flags alone left every warm-up hit as UNKNOWN, which reads on the
    scoreboard as "your payload didn't work".
    """
    probes = decodings(data)
    for flag, team in flags().items():
        if any(flag in p for p in probes):
            return team
    for team in sorted(known_teams(), key=len, reverse=True):
        if any(p.startswith(team) or f"{team}-" in p for p in probes):
            return team
    return "UNKNOWN"


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    with db() as conn:
        n = conn.execute("SELECT COUNT(*) c FROM hits").fetchone()["c"]
    return {"ok": True, "service": "listener", "hits": n, "flags": len(flags())}


@app.get("/pwned")
def pwned(team: str, request: Request, level: str = "0", ws: str = "2"):
    """A beacon. Workshop 2's payloads fire inside the victim bot.

    `ws` says WHICH WORKSHOP, and defaults to "2" so that every existing
    caller — the victim bot, the w2 page, the notebooks and the gates — keeps
    working untouched. Workshop 1 reaches the board through mailmate's
    `award()`, which passes ws=1 explicitly.
    """
    if not TOKEN.match(team):
        raise HTTPException(400, "team must match [A-Za-z0-9._-]{1,64}")
    record(
        team=team,
        kind="beacon",
        level=level,
        ws=ws,
        ua=request.headers.get("user-agent", ""),
        ip=request.headers.get("x-real-ip", request.client.host if request.client else ""),
    )
    return {"ok": True, "team": team, "level": level, "ws": "1" if str(ws) == "1" else "2"}


@app.get("/img/{data}.png")
def img(data: str, request: Request):
    """Workshop 1 exfil — the money route.

    The CLIENT makes this request, not MailMate. That's the whole demo.
    """
    record(
        team=team_for(data),
        kind="exfil",
        # Workshop 1 by construction — nothing else fetches /img/<flag>.png.
        ws="1",
        data=data,
        ua=request.headers.get("user-agent", ""),
        ip=request.headers.get("x-real-ip", request.client.host if request.client else ""),
    )
    return Response(
        PNG_1PX,
        media_type="image/png",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


@app.get("/feed")
def feed(limit: int = 50):
    """Live tail for the big screen."""
    with db() as conn:
        rows = conn.execute(
            "SELECT id,ts,team,kind,level,data,ua,ws FROM hits "
            "WHERE archived=0 ORDER BY id DESC LIMIT ?",
            (min(limit, 500),),
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/api/scores")
def scores():
    """Aggregated per team, for the scoreboard."""
    with db() as conn:
        # GROUPED BY (team, ws), not by team. One person can do BOTH
        # workshops under the same team name, and a single row cannot honestly
        # carry one workshop label or one "top level" for two different
        # ladders. So such a team appears once per workshop, which is also what
        # makes the split view a filter rather than a second query.
        #
        # `level` is TEXT and not always numeric: Workshop 2 exercise 4 beacons
        # at 4a/4b and Talk 2's staged payloads at L1..L5. CAST stops at the
        # first non-digit, so TRIM the known prefix before casting or every
        # `L1` row reports top_level 0 and shows no level at all on the board.
        rows = conn.execute(
            """SELECT team,
                      ws,
                      COUNT(*)                                   AS hits,
                      SUM(kind='beacon')                         AS beacons,
                      SUM(kind='exfil')                          AS exfils,
                      MAX(CAST(LTRIM(level, 'Ll') AS INTEGER))   AS top_level,
                      GROUP_CONCAT(DISTINCT level)               AS levels,
                      MAX(ts)                                    AS last_ts
               FROM hits WHERE archived=0
               GROUP BY team, ws
               ORDER BY top_level DESC, hits DESC, last_ts ASC"""
        ).fetchall()
    return [dict(r) for r in rows]


@app.get("/teardown")
def teardown(team: str, request: Request):
    """Workshop 2 exercise 7 — attendee-vs-attendee cleanup.

    The notebook prints "Listener closed, lab notified. Your uploads will be
    purged with the server rebuild." So: record it, and purge the team's
    uploaded repos now rather than waiting for the rebuild, which also stops
    the victim bot re-loading a payload after someone has bowed out.
    """
    if not TOKEN.match(team):
        raise HTTPException(400, "team must match [A-Za-z0-9._-]{1,64}")
    record(team=team, kind="teardown", ws="2",
           ip=request.headers.get("x-real-ip", request.client.host if request.client else ""))

    purged = "not attempted"
    try:
        req = urllib.request.Request(f"{HUB_URL}/api/purge/{team}", method="POST")
        with urllib.request.urlopen(req, timeout=8) as r:
            purged = json.loads(r.read()).get("removed", "?")
    except Exception as e:
        purged = f"failed: {type(e).__name__}"

    return {"ok": True, "team": team, "uploads_purged": purged}


@app.post("/api/archive")
def archive(undo: bool = False):
    """Clear the board between runs — WITHOUT destroying the log.

    Every read path here already filters `archived=0`, but nothing ever set it
    to 1, so the column has been dead since the schema was written. Flipping it
    is the whole feature. Deleting rows would have been fewer lines and would
    have thrown away the only record of a workshop.

    `known_teams()` deliberately does NOT filter on archived, so attribution of
    later hits survives a clear — don't "fix" that to match the other queries.
    """
    with _lock, db() as conn:
        cur = conn.execute(
            "UPDATE hits SET archived=? WHERE archived=?",
            (0, 1) if undo else (1, 0),
        )
        n = cur.rowcount
    return {"ok": True, "undo": undo, "rows": n}


@app.get("/api/stats")
def stats():
    with db() as conn:
        r = conn.execute(
            """SELECT COUNT(*) hits, COUNT(DISTINCT team) teams,
                      SUM(team='UNKNOWN') unattributed
               FROM hits WHERE archived=0"""
        ).fetchone()
    return dict(r)
