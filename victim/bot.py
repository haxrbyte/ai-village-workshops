"""
Victim bot — the thing attendees are actually attacking.

Polls the hub for newly uploaded repos and loads them the way a careless
engineer would. It is SUPPOSED to get owned. That is the entire point.

-----------------------------------------------------------------------------
Three load semantics, all measured 18 Aug with torch 2.13.0
-----------------------------------------------------------------------------
1.  torch.load(bare_pickle, weights_only=False)
      -> PAYLOAD EXECUTES, then raises RuntimeError("Invalid magic number").
      The beacon has already fired by the time the exception lands, so an
      exception after loading is NOT a failure and must not be treated as one.

2.  torch.load(bare_pickle)                       # torch >= 2.6 default
      -> UnpicklingError, payload does NOT run. weights_only defaults to True
      now. We pass weights_only=False deliberately: that is the legacy posture
      the workshop is about, and without it exercises 1-4 do nothing.

3.  torch.load(real_torch_save_zip, weights_only=False)
      -> payload runs, NO exception at all.

-----------------------------------------------------------------------------
/log?team=  — Workshop 2 exercise 6 ("Quiet")
-----------------------------------------------------------------------------
06-quiet.ipynb reads this and scores stealth on it:

    "Stealth bonus needs: status=ok, no stderr, duration in line with clean loads."

So every load records status, duration_ms and stderr. stderr is captured at the
FILE DESCRIPTOR level, not with contextlib.redirect_stderr: attendee payloads
routinely shell out (os.system, subprocess), and a subprocess writing to fd 2
sails straight past a Python-level redirect. A loud payload must look loud.
"""

import contextlib
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

HUB = os.environ.get("HF_ENDPOINT", "http://hub:8000")
LISTENER = os.environ.get("LISTENER_URL", "http://listener:8002")
POLL = int(os.environ.get("POLL_SECONDS", "20"))
PORT = int(os.environ.get("STATUS_PORT", "8006"))
WORK = pathlib.Path("/tmp/victim")
MAX_LOG = 200

# repo id -> the hub sha we last LOADED. Not a plain set of ids, and that is
# the whole point: keyed on the id alone, a REPUBLISH to the same repo name
# was invisible forever. Reported from the workshop 13 Sept 2026 — publish
# once (it fires), then publish again for any reason at all (you reset your
# progress, you improved the README, you pressed the button twice) and the bot
# skipped it silently, the beacon never fired again, and the page sat on
# "waiting for the victim bot…" with nothing to say why. Thirty attendees, and
# republishing is the most natural thing to try when something has not worked.
#
# The hub already advertises a sha that moves on an in-place edit — that was
# fixed on 21 Aug 2026 after the same class of bug cost an afternoon on L2 —
# so this is using machinery that already exists and is already trusted.
seen: dict[str, str] = {}
log_lock = threading.Lock()
load_log: list[dict] = []          # newest last — the notebook slices log[-10:]

STATE = {
    "started": time.time(),
    "last_poll": 0.0,
    "polls": 0,
    "repos_seen": 0,
    "loads_attempted": 0,
    "last_repo": None,
    "last_error": None,
}


def log(*a):
    """Never let logging kill the bot.

    Found 25 Aug 2026: the victim died with BrokenPipeError raised from this
    print — stdout's reader had gone away — and the crash handler then called
    log() again, so it died a second time inside its own error path. On restart
    it prints "ignoring N pre-existing repos", so every payload uploaded while
    it was down is skipped FOREVER. From an attendee's seat that looks like
    their exploit silently not working, with nothing to debug.

    A logging failure must never be able to do that.
    """
    try:
        print(f"[victim {time.strftime('%H:%M:%S')}]", *a, flush=True)
    except (BrokenPipeError, OSError, ValueError):
        pass


def get_json(url: str, timeout: int = 10):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


@contextlib.contextmanager
def capture_fd_stderr():
    """Capture fd 2 for the duration of the block.

    Python-level redirection is not enough: payloads shell out, and those
    subprocesses inherit fd 2 directly.
    """
    box = {"text": ""}
    with tempfile.TemporaryFile(mode="w+b") as tmp:
        sys.stderr.flush()
        saved = os.dup(2)
        os.dup2(tmp.fileno(), 2)
        try:
            yield box
        finally:
            sys.stderr.flush()
            os.dup2(saved, 2)
            os.close(saved)
            tmp.seek(0)
            box["text"] = tmp.read().decode("utf-8", "replace").strip()


def beacons_for(team: str, since: float) -> list[str]:
    """Levels the listener saw for this team since `since`.

    The bot cannot know which exercise a payload belongs to — the level lives
    in the attendee's own beacon URL. Correlating after the fact is what lets
    the log show `level=`, which the notebook prints.
    """
    try:
        feed = get_json(f"{LISTENER}/feed?limit=100", timeout=5)
    except Exception:
        return []
    return [str(h.get("level")) for h in feed
            if h.get("team") == team and h.get("kind") == "beacon"
            and float(h.get("ts", 0)) >= since - 1]


def repo_sha(repo_id: str) -> str:
    """The hub's current sha for a repo, or "" if it cannot be read."""
    try:
        return str(get_json(f"{HUB}/api/models/{repo_id}", timeout=5).get("sha") or "")
    except Exception:
        return ""


def fetch_repo(repo_id: str) -> pathlib.Path | None:
    dest = WORK / repo_id.replace("/", "__")
    try:
        info = get_json(f"{HUB}/api/models/{repo_id}")
    except Exception as e:
        log(f"  metadata failed for {repo_id}: {e}")
        return None
    dest.mkdir(parents=True, exist_ok=True)
    for sib in info.get("siblings", []):
        rel = sib["rfilename"]
        out = dest / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(f"{HUB}/{repo_id}/resolve/main/{rel}", timeout=60) as r:
                out.write_bytes(r.read())
        except Exception as e:
            log(f"  download failed {rel}: {e}")
    return dest


def do_load(d: pathlib.Path) -> tuple[str, list[str]]:
    """Returns (status, notes). status is 'ok' when nothing raised."""
    notes: list[str] = []
    raised = False

    import torch

    for name in ("pytorch_model.bin", "model.pt", "weights.pth", "model.pkl"):
        f = d / name
        if not f.is_file():
            continue
        notes.append(f"torch.load({name}, weights_only=False)")
        try:
            torch.load(f, weights_only=False)
            notes.append("  -> returned cleanly")
        except Exception as e:
            raised = True
            notes.append(f"  -> {type(e).__name__}: {str(e)[:90]}")

    cfg = d / "config.json"
    if cfg.is_file():
        try:
            conf = json.loads(cfg.read_text())
        except Exception:
            conf = {}
        if "auto_map" in conf:
            notes.append("from_pretrained(trust_remote_code=True)")
            try:
                from transformers import AutoModel
                AutoModel.from_pretrained(str(d), trust_remote_code=True,
                                          local_files_only=True)
                notes.append("  -> returned cleanly")
            except Exception as e:
                raised = True
                notes.append(f"  -> {type(e).__name__}: {str(e)[:90]}")

    if not notes:
        return "nothing-loadable", ["no weights file and no auto_map"]
    return ("error" if raised else "ok"), notes


def process(repo_id: str):
    team = repo_id.split("/", 1)[0]

    STATE["loads_attempted"] += 1
    STATE["last_repo"] = repo_id

    d = fetch_repo(repo_id)
    if d is None:
        return

    started = time.time()
    with capture_fd_stderr() as box:
        try:
            status, notes = do_load(d)
        except Exception:
            status, notes = "error", ["loader crashed", traceback.format_exc(limit=2)]
    duration_ms = int((time.time() - started) * 1000)
    stderr_text = box["text"]

    levels = beacons_for(team, started)
    entry = {
        "time": time.strftime("%H:%M:%S", time.localtime(started)),
        "ts": started,
        "team": team,
        "repo": repo_id,
        "level": levels[0] if levels else None,
        "levels": levels,
        "status": status,
        "duration_ms": duration_ms,
        "stderr": stderr_text[:2000],
        "notes": notes,
    }
    with log_lock:
        load_log.append(entry)
        del load_log[:-MAX_LOG]

    log(f"  status={status} {duration_ms}ms stderr={len(stderr_text)}b levels={levels}")
    for n in notes:
        log("  " + n)


def poll_once():
    STATE["polls"] += 1
    STATE["last_poll"] = time.time()
    try:
        repos = get_json(f"{HUB}/api/recent?limit=50")
    except Exception as e:
        STATE["last_error"] = f"poll failed: {e}"
        log(f"poll failed: {e}")
        return
    STATE["repos_seen"] = len(repos)
    for r in repos:
        rid = r["id"]
        sha = repo_sha(rid)
        # A repo we know AND whose sha is unchanged is skipped. An empty sha
        # means the lookup failed, not that the repo changed — treat that as
        # unchanged so a flaky hub cannot make the bot reload in a loop; the
        # next poll retries.
        if rid in seen and (not sha or seen[rid] == sha):
            continue
        first = rid not in seen
        seen[rid] = sha
        log(f"{'new repo' if first else 'republished'}: {rid}")
        try:
            process(rid)
        except Exception:
            STATE["last_error"] = traceback.format_exc(limit=2)
            log("process crashed:\n" + STATE["last_error"])


# --------------------------------------------------------------------------
# HTTP: /log?team=   and   /  (health)
#
# Deviation from INFRASTRUCTURE-v2 §3.3, which gave this service no port.
# 06-quiet.ipynb requires GET /victim/log?team=, and the morning check needs
# "victim bot picked up a model in the last cycle" answerable without logs.
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def _send(self, code: int, payload):
        body = json.dumps(payload, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)

        if parsed.path.rstrip("/") in ("/log", "/victim/log"):
            team = (qs.get("team") or [""])[0]
            with log_lock:
                rows = [e for e in load_log if not team or e["team"] == team]
            return self._send(200, rows)

        healthy = STATE["polls"] > 0 and (time.time() - STATE["last_poll"]) < POLL * 3
        return self._send(200 if healthy else 503,
                          {"ok": healthy, "service": "victim", "hub": HUB,
                           "poll_seconds": POLL, "loads_logged": len(load_log),
                           "seen": sorted(seen), **STATE})

    def log_message(self, *a):
        pass


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    threading.Thread(
        target=lambda: HTTPServer(("0.0.0.0", PORT), Handler).serve_forever(),
        daemon=True,
    ).start()
    log(f"polling {HUB} every {POLL}s; status + /log on :{PORT}")

    # Don't replay every upload from the whole day on restart.
    try:
        for r in get_json(f"{HUB}/api/recent?limit=200"):
            seen[r["id"]] = repo_sha(r["id"])
        log(f"ignoring {len(seen)} pre-existing repos")
    except Exception as e:
        log(f"initial sweep failed (hub not up yet?): {e}")

    STATE["polls"] = 1
    STATE["last_poll"] = time.time()
    while True:
        time.sleep(POLL)
        poll_once()


if __name__ == "__main__":
    main()
