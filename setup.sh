#!/usr/bin/env bash
# ===========================================================================
# One command from a fresh clone to a working lab.
#
#   ./setup.sh                 build, start, verify
#   ./setup.sh --canned        skip Ollama; Workshop 1 runs scripted replies
#   ./setup.sh --port 9090     override the host port
#
# Everything is built on THIS machine. Nothing is pulled from a registry
# except nginx and mailpit, both pinned by digest.
#
# Every failure prints FAIL then FIX with the exact command to run. The
# verification at the end is the project's own gates, not a new check.
# ===========================================================================
set -uo pipefail
cd "$(dirname "$0")"

# Same visual grammar as scripts/smoke.sh, deliberately.
ok()  { printf "  \033[32mPASS\033[0m  %s\n" "$*"; }
bad() { printf "  \033[31mFAIL\033[0m  %s\n" "$*"; }
fix() { printf "  \033[33mFIX \033[0m  %s\n" "$*"; }
say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
die() { bad "$1"; shift; for l in "$@"; do fix "$l"; done; exit 1; }

CANNED=0; PORT=""; NO_OLLAMA=0
while [ $# -gt 0 ]; do
  case "$1" in
    --canned)     CANNED=1; NO_OLLAMA=1 ;;
    --no-ollama)  NO_OLLAMA=1 ;;
    --build)      ;;  # accepted and ignored: building is the only mode
    --port)       PORT="$2"; shift ;;
    -h|--help)    sed -n '2,12p' "$0"; exit 0 ;;
    *)            die "unknown option: $1" "./setup.sh --help" ;;
  esac
  shift
done

# --- 1. Docker --------------------------------------------------------------
say "Docker"
command -v docker >/dev/null 2>&1 || die "docker not found" \
  "macOS:  brew install --cask docker    (or https://docker.com/products/docker-desktop)" \
  "Linux:  https://docs.docker.com/engine/install/"
docker info >/dev/null 2>&1 || die "the Docker daemon is not running" \
  "macOS:  open -a Docker, wait for the whale to settle" \
  "Linux:  sudo systemctl start docker   (and: sudo usermod -aG docker \$USER, then log out and back in)"
docker compose version >/dev/null 2>&1 || die "docker compose v2 not found" \
  "You may have the old docker-compose v1. Install the Compose plugin:" \
  "  https://docs.docker.com/compose/install/"
ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null)"

# --- 2. platform ------------------------------------------------------------
say "Platform"
OS="$(uname -s)"; ARCH="$(uname -m)"
ok "$OS/$ARCH"
if [ "$OS" = "Darwin" ] && [ "$ARCH" = "x86_64" ]; then
  printf "  \033[33mNOTE\033[0m  Intel Mac: exercise 8's optional appendix cannot be built here.\n"
  printf "        MLX publishes no macOS-x86_64 wheel at any version. Exercises 1-7\n"
  printf "        are unaffected. See sleeper/README.md.\n"
fi

# --- 3. memory --------------------------------------------------------------
say "Resources"
MEM=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo 0)
MEMGB=$(( MEM / 1024 / 1024 / 1024 ))
if [ "$MEMGB" -lt 6 ] && [ "$MEM" -gt 0 ]; then
  die "Docker has only ${MEMGB} GiB of memory; this lab needs 6 GiB" \
    "Colima:          colima stop && colima start --cpu 4 --memory 8 --disk 60" \
    "Docker Desktop:  Settings -> Resources -> Memory -> 8 GB -> Apply & restart"
fi
ok "${MEMGB} GiB available to Docker"

# --- 4. host port -----------------------------------------------------------
say "Port"
port_free() { ! (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }
if [ -n "$PORT" ]; then
  port_free "$PORT" || die "port $PORT is already in use" "./setup.sh --port 9090"
else
  PORT=""
  for p in 8080 8081 8090 9090 9900; do port_free "$p" && { PORT="$p"; break; }; done
  [ -n "$PORT" ] || die "no free port found" "./setup.sh --port <something free>"
fi
ok "using port $PORT"

# --- 5. directories the bind mounts need ------------------------------------
# Docker creates missing bind-mount sources as ROOT on Linux, after which
# `make reset` and `make nuke` fail with EPERM. Create them as us, first.
say "Directories"
mkdir -p state/uploads state/tenants models
ok "state/ and models/ exist and are owned by $(id -un)"

# --- 6. .env ----------------------------------------------------------------
say "Configuration"
[ -f .env ] || cp .env.example .env
set_env() {
  if grep -q "^$1=" .env; then
    python3 - "$1" "$2" <<'PY' 2>/dev/null || sed -i.bak "s|^$1=.*|$1=$2|" .env
import pathlib, re, sys
k, v = sys.argv[1], sys.argv[2]
p = pathlib.Path(".env"); s = p.read_text()
p.write_text(re.sub(rf"^{re.escape(k)}=.*$", f"{k}={v}", s, flags=re.M))
PY
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
set_env LAB_PORT "$PORT"
rm -f .env.bak
ok "wrote .env"

# --- 7. Ollama --------------------------------------------------------------
say "Workshop 1's language model"
OLLAMA_OK=0
if [ "$NO_OLLAMA" = "0" ]; then
  if curl -s --max-time 3 http://localhost:11434/api/tags >/dev/null 2>&1; then
    ok "Ollama is running on the host"
    OLLAMA_OK=1
  elif [ "$OS" = "Darwin" ] && command -v ollama >/dev/null 2>&1; then
    ok "starting Ollama"
    (ollama serve >/dev/null 2>&1 &) ; sleep 3
    curl -s --max-time 5 http://localhost:11434/api/tags >/dev/null 2>&1 && OLLAMA_OK=1
  elif [ "$OS" = "Linux" ]; then
    ok "no host Ollama; using the containerised one"
    set_env COMPOSE_PROFILES ollama
    set_env OLLAMA_URL "http://ollama:11434"
    OLLAMA_OK=2
  fi
fi
if [ "$OLLAMA_OK" = "0" ]; then
  printf "  \033[33mNOTE\033[0m  No model. Workshop 1 will use scripted replies.\n"
  printf "        All 7 exercises still score, but only for the intended payloads --\n"
  printf "        improvised attacks get nothing back. Install Ollama and re-run to\n"
  printf "        get the real thing:  https://ollama.com/download\n"
  set_env MAILMATE_BACKEND canned
else
  set_env MAILMATE_BACKEND live
fi

# --- 8. seed the fake hub ---------------------------------------------------
say "Seeding"
if command -v python3 >/dev/null 2>&1; then
  python3 scripts/seed_models.py >/dev/null 2>&1 && ok "fake hub seeded" \
    || printf "  \033[33mNOTE\033[0m  seed_models.py failed; exercises 1-7 do not need it\n"
else
  printf "  \033[33mNOTE\033[0m  no python3 on PATH; skipped (not needed for the web workshops)\n"
fi

# --- 9. images --------------------------------------------------------------
say "Building images"
printf "  this is the slow step the first time -- victim pulls PyTorch.\n"
printf "  Later runs reuse the layer cache and take seconds.\n"
docker compose build || die "build failed" \
  "Re-run with full output to see which service and which line:" \
  "    docker compose build --progress=plain" \
  "Out of disk? Reclaim with:  docker system prune -a"
ok "images built"

# --- 10. start --------------------------------------------------------------
say "Starting"
docker compose up -d || die "compose up failed" "docker compose logs"

if [ "$OLLAMA_OK" = "2" ]; then
  say "Pulling llama3.2:3b (about 2 GB, once)"
  docker compose exec -T ollama ollama pull llama3.2:3b || \
    printf "  \033[33mNOTE\033[0m  pull failed; re-run: docker compose exec ollama ollama pull llama3.2:3b\n"
elif [ "$OLLAMA_OK" = "1" ]; then
  if ! ollama list 2>/dev/null | grep -q "llama3.2:3b"; then
    say "Pulling llama3.2:3b (about 2 GB, once)"
    ollama pull llama3.2:3b || printf "  \033[33mNOTE\033[0m  pull failed; run: ollama pull llama3.2:3b\n"
  fi
fi

# --- 11. wait for health ----------------------------------------------------
say "Waiting for services"
BASE="http://localhost:$PORT"
for i in $(seq 1 120); do
  [ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "$BASE/health" 2>/dev/null)" = "200" ] && break
  [ "$i" = "120" ] && die "services did not come up within 240s" \
    "docker compose ps" "docker compose logs victim   # torch is the slow one"
  sleep 2
done
ok "lab is answering on $BASE"

# --- 12. verify, with the project's own gates -------------------------------
say "Verifying (gate 1)"
bash scripts/smoke.sh "$BASE" || die "gate 1 failed" "docker compose logs"

say "Verifying (gate 3 — Workshop 2 end to end)"
bash scripts/gate3_workshop2.sh "$BASE" || die "gate 3 failed" "docker compose logs victim"

printf "\n\033[1;32m================================================\033[0m\n"
printf "\033[1;32m  Ready.  %s/start\033[0m\n" "$BASE"
printf "\033[1;32m================================================\033[0m\n\n"
printf "  Pick a team name, then work through Workshop 1 or 2.\n"
printf "  Scoreboard: %s/\n" "$BASE"
printf "  Stop with:  make down      Re-check with: make check\n\n"
