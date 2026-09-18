"""
Scanner — wraps the REAL tools, at TWO REAL VERSIONS.

Contract from workshop/notebooks/03-caught.ipynb:
    POST /scan          {"team": "HAXR", "file": "<base64 bytes>"}
    ->                  {"verdict": "flagged"|"clean"|"not_scanned", ...}
    POST /scan/upgrade  {"team": "HAXR"}      switch that team to the patched scanner

-----------------------------------------------------------------------------
Why two picklescan versions
-----------------------------------------------------------------------------
Exercise 3 must be CAUGHT. Exercise 4's two bypasses must WORK, and then stop
working after /scan/upgrade. Measured 18 Aug against the notebooks' own
payloads (urllib.request.urlopen via __reduce__):

  picklescan   ex3 full      ex4-A truncated     ex4-B 7z-named-.bin
  0.0.15       caught        BYPASS (fail-open)  BYPASS (fail-open)
  0.0.29       caught        BYPASS              caught  (7z support added)
  1.0.5        caught        caught              caught

So OLD = 0.0.15 and NEW = 1.0.5, and both bypasses are genuine historical
behaviour rather than something simulated here. On 0.0.15 an unreadable file
comes back scan_err=True with zero globals, and reporting that as "clean" is
precisely the fail-open bug exercise 4 exists to teach.

You cannot import two versions of one package into a single interpreter, so
each lives in its own venv and is invoked through runner.py.

-----------------------------------------------------------------------------
Verdict rule
-----------------------------------------------------------------------------
picklescan grades globals Innocuous / Suspicious / Dangerous, and only
Dangerous increments issues_count. Every workshop payload uses
urllib.request.urlopen, which grades SUSPICIOUS under protocol 2. Counting only
issues_count would let exercise 3 — the one designed to be caught — pass clean.
So suspicious counts as flagged.
"""

import base64
import json
import os
import pathlib
import subprocess
import tempfile
import threading
import time

from fastapi import FastAPI, HTTPException

app = FastAPI(title="scanner", docs_url=None, redoc_url=None)

MAX_BYTES = 64 * 1024 * 1024
RUNNER = "/opt/runner.py"
ENGINES = {
    "old": os.environ.get("PS_OLD", "/opt/ps-old/bin/python"),
    "new": os.environ.get("PS_NEW", "/opt/ps-new/bin/python"),
}
DEFAULT_MODE = os.environ.get("SCANNER_DEFAULT_MODE", "old")

# Per-team engine choice. Global would mean one attendee hitting /scan/upgrade
# silently breaks exercise 3 for everyone else in the room.
_mode_lock = threading.Lock()
team_mode: dict[str, str] = {}

STATS = {"scans": 0, "flagged": 0, "clean": 0, "not_scanned": 0, "upgrades": 0,
         "last_ts": 0.0}

try:
    from modelscan.modelscan import ModelScan
    HAVE_MODELSCAN = True
except Exception:  # pragma: no cover
    HAVE_MODELSCAN = False


def engine_versions() -> dict:
    out = {}
    for name, py in ENGINES.items():
        try:
            r = subprocess.run(
                [py, "-c", "import importlib.metadata as m;print(m.version('picklescan'))"],
                capture_output=True, text=True, timeout=15)
            out[name] = r.stdout.strip() or "?"
        except Exception:
            out[name] = "unavailable"
    return out


VERSIONS = engine_versions()


def sniff(blob: bytes) -> tuple[str, str]:
    """(format, suffix). The notebook sends no filename and modelscan needs one."""
    if blob[:8] == b"\x89HDF\r\n\x1a\n":
        return "hdf5", ".h5"
    if blob[:6] == b"7z\xbc\xaf\x27\x1c":
        return "7z", ".bin"          # nullifAI's trick — a 7z wearing a model's name
    if blob[:2] == b"PK":
        return "zip", ".bin"
    if len(blob) > 8:
        n = int.from_bytes(blob[:8], "little")
        if 0 < n < len(blob) and blob[8:9] == b"{":
            return "safetensors", ".safetensors"
    if blob[:1] in (b"\x80", b"(", b"]", b"}", b"c"):
        return "pickle", ".pkl"
    return "unknown", ".bin"


def run_picklescan(py: str, path: pathlib.Path) -> dict:
    try:
        r = subprocess.run([py, RUNNER, str(path)],
                           capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        return {"ran": False, "error": "timeout"}
    if r.returncode != 0 or not r.stdout.strip():
        return {"ran": False, "error": (r.stderr or "no output")[:300]}
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ran": False, "error": r.stdout[:300]}
    out["ran"] = not out.get("crashed", False)
    return out


def verdict_for(res: dict, mode: str) -> tuple[str, str]:
    """(verdict, why)."""
    if not res.get("ran"):
        return "not_scanned", res.get("error", "scanner did not run")

    globs = res.get("globals") or []
    bad = [g for g in globs if g.get("safety") in ("dangerous", "suspicious")]

    if res.get("scan_err") and not globs:
        # The scanner could not read the file.
        if mode == "old":
            # FAIL-OPEN. This is the vulnerability exercise 4 teaches, and it is
            # real 0.0.15 behaviour — not something faked here.
            return "clean", "scanner could not parse the file and reported nothing"
        return "flagged", "unreadable file treated as suspicious (patched behaviour)"

    if bad:
        worst = "dangerous" if any(g["safety"] == "dangerous" for g in bad) else "suspicious"
        names = ", ".join(f"{g['module']}.{g['name']}" for g in bad[:4])
        return "flagged", f"{worst} global(s): {names}"
    return "clean", "parsed cleanly, nothing on the blacklist"


def run_modelscan(path: pathlib.Path) -> dict:
    if not HAVE_MODELSCAN:
        return {"ran": False, "verdict": "unavailable"}
    try:
        res = ModelScan().scan(str(path))
    except Exception as e:
        return {"ran": False, "verdict": "error", "reason": f"{type(e).__name__}: {e}"}
    summary = res.get("summary", {})
    skipped = summary.get("skipped", {}) or {}
    if skipped.get("total_skipped") and not summary.get("scanned", {}).get("scanned_files"):
        files = skipped.get("skipped_files") or []
        return {"ran": False, "verdict": "not_scanned",
                "reason": files[0].get("description", "unknown") if files else "unknown",
                "note": "modelscan dispatches on file extension and declined this "
                        "one. A skip is not the same answer as a clean scan."}
    total = summary.get("total_issues", 0)
    return {"ran": True, "verdict": "flagged" if total else "clean", "issues": total,
            "by_severity": summary.get("total_issues_by_severity", {})}


def mode_for(team: str) -> str:
    with _mode_lock:
        return team_mode.get(team, DEFAULT_MODE)


@app.get("/health")
def health():
    return {"ok": True, "service": "scanner", "engines": VERSIONS,
            "default_mode": DEFAULT_MODE, "upgraded_teams": sorted(team_mode),
            **STATS}


@app.post("/scan")
def scan(body: dict):
    blob_b64 = body.get("file")
    if not blob_b64:
        raise HTTPException(400, "expected {'team':..., 'file': <base64 bytes>}")
    try:
        blob = base64.b64decode(blob_b64, validate=True)
    except Exception:
        raise HTTPException(400, "file is not valid base64")
    if len(blob) > MAX_BYTES:
        raise HTTPException(413, f"file exceeds {MAX_BYTES // 1048576} MB")

    team = body.get("team", "")
    mode = mode_for(team)
    fmt, suffix = sniff(blob)
    if body.get("name"):
        suffix = pathlib.Path(body["name"]).suffix or suffix

    with tempfile.TemporaryDirectory() as td:
        p = pathlib.Path(td) / f"upload{suffix}"
        p.write_bytes(blob)
        ps = run_picklescan(ENGINES[mode], p)
        ms = run_modelscan(p)

    verdict, why = verdict_for(ps, mode)

    STATS["scans"] += 1
    STATS[verdict] = STATS.get(verdict, 0) + 1
    STATS["last_ts"] = time.time()

    return {
        "verdict": verdict,
        "why": why,
        "detected_as": fmt,
        "scanned_as": suffix,
        "bytes": len(blob),
        "team": team,
        "scanner_version": VERSIONS.get(mode, "?"),
        "scanner_mode": mode,
        "tools": {"picklescan": ps, "modelscan": ms},
    }


@app.post("/scan/upgrade")
def upgrade(body: dict | None = None):
    """Exercise 4 step 4 — flip this team to the patched scanner.

    Per team on purpose. A global switch would break exercise 3 for anyone
    else mid-flight.
    """
    body = body or {}
    team = body.get("team", "")
    target = body.get("mode", "new")
    if target not in ENGINES:
        raise HTTPException(400, f"mode must be one of {sorted(ENGINES)}")

    with _mode_lock:
        if team:
            team_mode[team] = target
        else:
            # No team given: fall back to switching the default, and say so.
            global DEFAULT_MODE
            DEFAULT_MODE = target
    STATS["upgrades"] += 1

    return {
        "ok": True,
        "team": team or "(all — no team supplied)",
        "scanner": "picklescan",
        "was": VERSIONS.get("old" if target == "new" else "new", "?"),
        "now": VERSIONS.get(target, "?"),
        "changed": [
            "an unreadable file is now reported as suspicious, not clean",
            "non-zip containers (7z) are opened and inspected",
        ],
        "scope": "this team only" if team else "default for everyone",
    }
