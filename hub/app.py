"""
Fake Hugging Face hub — an ORIGIN, not a mirror.

Serves only the models under /data/models (staged, read-only) and
/data/uploads (attendee uploads). Never reaches upstream. That is the point:
`HF_ENDPOINT=http://northwind.local/hub` must work with stock, unmodified
transformers, offline, or Talk 2's central claim is false.

Route order matters. The /{org}/{name}/... catch-alls are greedy, so every
/api/* and /health route is declared before them.
"""

import base64
import hashlib
import html
import os
import pathlib
import re
import shutil

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse

app = FastAPI(title="hub", docs_url=None, redoc_url=None)

# Overridable so the Gate 2 spike can run outside Docker.
UPLOADS = pathlib.Path(os.environ.get("HUB_UPLOADS", "/data/uploads")).resolve()
MODELS = pathlib.Path(os.environ.get("HUB_MODELS", "/data/models")).resolve()
UPLOADS.mkdir(parents=True, exist_ok=True)

MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # decoded, per repo
TOKEN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


# --------------------------------------------------------------------------
# Containment.
#
# Attendees are explicitly taught to attack this service and Workshop 2
# exercise 7 is attendee-vs-attendee. Both joins below take user input.
# --------------------------------------------------------------------------
def find(org: str, name: str) -> pathlib.Path:
    if not (TOKEN.match(org) and TOKEN.match(name)):
        raise HTTPException(400, "bad repo id")
    for root in (UPLOADS, MODELS):
        p = (root / org / name).resolve()
        if p.is_relative_to(root) and p.is_dir():
            return p
    raise HTTPException(404, "repo not found")


def safe_file(repo: pathlib.Path, rel: str) -> pathlib.Path:
    f = (repo / rel).resolve()
    if not f.is_relative_to(repo):
        raise HTTPException(400, "bad path")
    if not f.is_file():
        raise HTTPException(404, "file not found")
    return f


# --------------------------------------------------------------------------
# Cheap metadata.
# --------------------------------------------------------------------------
_sha_cache: dict[str, tuple[tuple[float, int], str]] = {}


SHA_SAMPLE = 4096
SHA_POINTS = 9          # evenly spaced probes through each file


def sha_of(p: pathlib.Path) -> str:
    """Fake commit sha for a repo.

    Cached on the NEWEST mtime in the tree, not the directory's own.

    It used to key on `p.stat().st_mtime`, and that is wrong in a way that
    cost an afternoon on 21 Aug 2026: a directory's mtime changes when an
    entry is added, removed or renamed — NOT when a file inside it is edited
    in place. So `seed_models.py` rewriting config.json left the cached sha
    untouched, the hub kept advertising the OLD commit, huggingface_hub saw a
    sha it already had in ~/.cache and never re-downloaded. Talk 2 L2 loaded a
    stale config and quietly did nothing, while `curl`ing the same URL by hand
    showed the new content — because curl has no cache and does not consult
    the sha at all.

    Walking for stats is cheap; it is the sampling READS below that this cache
    exists to avoid.

    Samples SHA_POINTS evenly spaced 4 KB windows per file, plus name and size.

    Name+size alone is NOT enough: northwind/support-7b and its clean twin
    have identical filenames and identical byte counts, so they produced the
    SAME sha — which on a real hub means "same content", and is exactly the
    tell exercise 8 attendees go hunting for.

    Head+tail alone is not enough either: the head is the safetensors header
    (identical tensor names and shapes in both) and the tail is the last
    tensor, which the LoRA never touched. The fine-tune only altered 8 of 36
    layers, all of them in the MIDDLE of the file — so the probes have to be
    spread through it.

    Still cheap: ~300 KB read for a 2.1 GB repo, versus hashing 2.1 GB.
    Unlike mtime, it survives copying the models to another machine.
    """
    files = sorted(f for f in p.rglob("*") if f.is_file())
    # max() over file mtimes, and the count, so an edit, an add and a delete
    # each move the key. The directory's own mtime is included for the case
    # of an empty repo.
    stamp = max([p.stat().st_mtime] + [f.stat().st_mtime for f in files])
    key, mtime = str(p), (stamp, len(files))
    hit = _sha_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    h = hashlib.sha1()
    for f in files:
        size = f.stat().st_size
        h.update(f.name.encode())
        h.update(str(size).encode())
        with f.open("rb") as fh:
            if size <= SHA_SAMPLE * SHA_POINTS:
                h.update(fh.read())
            else:
                step = size // SHA_POINTS
                for i in range(SHA_POINTS):
                    fh.seek(i * step)
                    h.update(fh.read(SHA_SAMPLE))
    sha = h.hexdigest()
    _sha_cache[key] = (mtime, sha)
    return sha


def etag_of(f: pathlib.Path) -> str:
    """Size+mtime, deliberately NOT a content hash.

    transformers sends HEAD before every GET. Hashing file contents here means
    reading multi-GB weights into a 512 MB container on the request type that
    is supposed to be cheap.
    """
    st = f.stat()
    return f'"{st.st_size:x}-{int(st.st_mtime):x}"'


def files_in(p: pathlib.Path) -> list[str]:
    return [f.relative_to(p).as_posix() for f in sorted(p.rglob("*")) if f.is_file()]


def human(n: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} GB"


# --------------------------------------------------------------------------
# Health + attendee API (declared before the greedy catch-alls).
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "service": "hub"}


@app.get("/api/models/{org}/{name}")
def model_info(org: str, name: str):
    """Endpoint 1 of 3 that from_pretrained() actually calls."""
    p = find(org, name)
    return {
        "id": f"{org}/{name}",
        "modelId": f"{org}/{name}",
        "sha": sha_of(p),
        "private": False,
        "downloads": 84213,
        "likes": 312,
        "tags": ["text-generation", "safetensors", "llama"],
        "pipeline_tag": "text-generation",
        "library_name": "transformers",
        "siblings": [{"rfilename": rel} for rel in files_in(p)],
    }


@app.get("/api/models/{org}/{name}/revision/{rev}")
def model_info_rev(org: str, name: str, rev: str):
    """Same answer, revision-qualified.

    `huggingface_hub` asks for this form whenever a revision is pinned, and the
    `kernels` loader always pins one. Talk 2's L2 demo is a config field naming
    a kernel repo, so without this route the fetch 404s and the CVE looks
    patched when it isn't. Also what `mlx_lm.server` asks for.
    """
    return model_info(org, name)


@app.get("/api/models/{org}/{name}/tree/{rev}")
def model_tree(org: str, name: str, rev: str, recursive: bool = False,
               expand: bool = False):
    """File tree, as `snapshot_download` wants it.

    `model_info` alone is enough for `from_pretrained`, which fetches known
    filenames one at a time. Downloading a whole repo — which is what the
    `kernels` loader does for Talk 2's L2 kernel — goes through this instead.
    """
    p = find(org, name)
    out = []
    for rel in files_in(p):
        f = p / rel
        out.append({"type": "file", "path": rel, "size": f.stat().st_size,
                    "oid": etag_of(f).strip('"')})
    return out


@app.post("/api/upload")
async def upload(body: dict):
    team = body.get("team", "")
    repo = body.get("repo", "")
    if not (TOKEN.match(team) and TOKEN.match(repo)):
        raise HTTPException(400, "team and repo must match [A-Za-z0-9._-]{1,64}")

    decoded: dict[str, bytes] = {}
    total = 0
    for fname, b64 in body.get("files", {}).items():
        if "/" in fname or "\\" in fname or fname.startswith("."):
            raise HTTPException(400, f"bad filename: {fname!r}")
        try:
            blob = base64.b64decode(b64, validate=True)
        except Exception:
            raise HTTPException(400, f"{fname}: not valid base64")
        total += len(blob)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"repo exceeds {MAX_UPLOAD_BYTES // 1048576} MB")
        decoded[fname] = blob

    if not decoded:
        raise HTTPException(400, "no files")

    dest = UPLOADS / team / repo
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for fname, blob in decoded.items():
        (dest / fname).write_bytes(blob)
    _sha_cache.pop(str(dest.resolve()), None)

    return {
        "ok": True,
        "repo": f"{team}/{repo}",
        "url": f"/hub/{team}/{repo}",
        "files": list(decoded),
        "bytes": total,
    }


@app.post("/api/purge/{team}")
def purge(team: str):
    """Remove a team's uploaded repos. Called by the listener on /teardown."""
    if not TOKEN.match(team):
        raise HTTPException(400, "bad team")
    d = (UPLOADS / team).resolve()
    if not d.is_relative_to(UPLOADS) or not d.is_dir():
        return {"ok": True, "removed": 0}
    n = len([p for p in d.glob("*") if p.is_dir()])
    shutil.rmtree(d)
    for k in [k for k in _sha_cache if k.startswith(str(d))]:
        _sha_cache.pop(k, None)
    return {"ok": True, "removed": n}


@app.get("/api/recent")
def recent(limit: int = 20):
    repos = [p for p in UPLOADS.glob("*/*") if p.is_dir()]
    repos.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {"team": p.parent.name, "repo": p.name, "id": f"{p.parent.name}/{p.name}"}
        for p in repos[:limit]
    ]


# --------------------------------------------------------------------------
# The two file endpoints. Greedy — everything above must be declared first.
# --------------------------------------------------------------------------
@app.head("/{org}/{name}/resolve/{rev}/{path:path}")
def head_file(org: str, name: str, rev: str, path: str):
    """Endpoint 2 of 3. Headers only — must stay cheap."""
    repo = find(org, name)
    f = safe_file(repo, path)
    return Response(
        headers={
            "X-Repo-Commit": sha_of(repo),
            "ETag": etag_of(f),
            "Content-Length": str(f.stat().st_size),
            "Accept-Ranges": "bytes",
        }
    )


@app.get("/{org}/{name}/resolve/{rev}/{path:path}")
def get_file(org: str, name: str, rev: str, path: str):
    """Endpoint 3 of 3. The bytes."""
    repo = find(org, name)
    f = safe_file(repo, path)
    return FileResponse(
        f,
        headers={"X-Repo-Commit": sha_of(repo), "ETag": etag_of(f)},
    )


# --------------------------------------------------------------------------
# Cosmetics. The point of Workshop 2 exercise 2 is that a plausible model
# card IS the attack surface, so this page has to look ordinary.
# --------------------------------------------------------------------------
CARD = """<!doctype html>
<meta charset="utf-8"><title>{repo} · Hugging Face</title>
<style>
 body{{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
      margin:0;color:#111;background:#fff}}
 header{{border-bottom:1px solid #e5e7eb;padding:14px 28px;display:flex;
        align-items:center;gap:10px;font-weight:600}}
 .wrap{{max-width:1000px;margin:0 auto;padding:28px}}
 h1{{font-size:24px;margin:0 0 4px;font-weight:600}}
 .meta{{color:#6b7280;font-size:13px;margin-bottom:18px}}
 .badge{{display:inline-block;background:#ecfdf5;color:#065f46;
        border:1px solid #a7f3d0;border-radius:6px;padding:2px 9px;
        font-size:12px;font-weight:600;margin-left:8px}}
 .tabs{{border-bottom:1px solid #e5e7eb;margin:0 0 18px;display:flex;gap:22px}}
 .tabs span{{padding:9px 0;font-size:14px;color:#6b7280}}
 .tabs .on{{color:#111;border-bottom:2px solid #f59e0b;font-weight:600}}
 table{{width:100%;border-collapse:collapse;font-size:14px}}
 td{{padding:9px 6px;border-bottom:1px solid #f3f4f6}}
 td.f{{font-family:ui-monospace,SFMono-Regular,Menlo,monospace}}
 td.s{{color:#6b7280;text-align:right;white-space:nowrap}}
 .stats{{display:flex;gap:26px;color:#6b7280;font-size:13px;margin-bottom:22px}}
 code{{background:#f3f4f6;padding:2px 6px;border-radius:4px;
      font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:13px}}
 pre{{background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;
     padding:14px;overflow-x:auto;font-size:13px}}
</style>
<header>🤗 Hugging Face</header>
<div class="wrap">
  <h1>{repo}<span class="badge">✓ Safe</span></h1>
  <div class="meta">Text Generation · Transformers · Safetensors · llama</div>
  <div class="stats">
    <div><b>{downloads:,}</b> downloads last month</div>
    <div><b>{likes}</b> likes</div>
    <div>commit <code>{sha}</code></div>
  </div>
  <div class="tabs">
    <span class="on">Files and versions</span><span>Model card</span>
    <span>Community</span><span>Settings</span>
  </div>
  <table>{rows}</table>
  <h3 style="margin-top:30px;font-size:16px">Use this model</h3>
  <pre>from transformers import AutoModelForCausalLM

model = AutoModelForCausalLM.from_pretrained(
    "{repo}",
    trust_remote_code=True,
)</pre>
</div>
"""


@app.get("/{org}/{name}", response_class=HTMLResponse)
def model_card(org: str, name: str):
    p = find(org, name)
    rows = "".join(
        "<tr><td class='f'>📄 {}</td><td class='s'>{}</td></tr>".format(
            html.escape(rel), human((p / rel).stat().st_size)
        )
        for rel in files_in(p)
    )
    return CARD.format(
        repo=html.escape(f"{org}/{name}"),
        downloads=84213,
        likes=312,
        sha=sha_of(p)[:7],
        rows=rows,
    )


@app.get("/", response_class=HTMLResponse)
def index():
    staged = [f"{p.parent.name}/{p.name}" for p in sorted(MODELS.glob("*/*")) if p.is_dir()]
    up = [f"{p.parent.name}/{p.name}" for p in sorted(UPLOADS.glob("*/*")) if p.is_dir()]
    li = lambda xs: "".join(
        f'<li><a href="/hub/{html.escape(x)}">{html.escape(x)}</a></li>' for x in xs
    ) or "<li><i>none</i></li>"
    return (
        "<!doctype html><meta charset='utf-8'><title>hub</title>"
        "<style>body{font:15px/1.7 -apple-system,sans-serif;max-width:640px;"
        "margin:40px auto;padding:0 20px}h2{font-size:15px;color:#6b7280;"
        "text-transform:uppercase;letter-spacing:.05em;margin-top:28px}</style>"
        "<h1>🤗 Hub</h1>"
        f"<h2>Staged</h2><ul>{li(staged)}</ul>"
        f"<h2>Uploads</h2><ul>{li(up)}</ul>"
    )
