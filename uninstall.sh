#!/usr/bin/env bash
# ===========================================================================
# Remove everything this lab put on your machine.
#
#   ./uninstall.sh              containers, networks, images built here, state
#   ./uninstall.sh --all        ...plus the pinned third-party images and the
#                               Docker build cache
#   ./uninstall.sh --model      ...also remove the Ollama model it pulled
#   ./uninstall.sh --dry-run    show what would go, touch nothing
#   ./uninstall.sh --yes        skip the confirmation
#
# Everything is scoped to this compose project. Nothing outside it is touched
# unless you ask with --all or --model, and both say so before acting.
# ===========================================================================
set -uo pipefail
cd "$(dirname "$0")"

ok()  { printf "  \033[32mgone\033[0m  %s\n" "$*"; }
skip(){ printf "  \033[2mkept\033[0m  %s\n" "$*"; }
say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }
warn(){ printf "  \033[33m!\033[0m     %s\n" "$*"; }

ALL=0; MODEL=0; DRY=0; YES=0
while [ $# -gt 0 ]; do
  case "$1" in
    --all)     ALL=1 ;;
    --model)   MODEL=1 ;;
    --dry-run) DRY=1 ;;
    --yes|-y)  YES=1 ;;
    -h|--help) sed -n '2,14p' "$0"; exit 0 ;;
    *) echo "unknown option: $1"; exit 1 ;;
  esac
  shift
done

PROJECT="$(grep -m1 '^name:' docker-compose.yml | awk '{print $2}')"
PROJECT="${PROJECT:-modellab}"
run() { if [ "$DRY" = "1" ]; then printf "  \033[2mwould run:\033[0m %s\n" "$*"; else "$@" >/dev/null 2>&1; fi; }

# ---- what is actually here -------------------------------------------------
say "What this will remove"
cn=$(docker ps -aq --filter "label=com.docker.compose.project=$PROJECT" 2>/dev/null | wc -l | tr -d ' ')
im=$(docker images -q "${PROJECT}-*" 2>/dev/null | wc -l | tr -d ' ')
printf "  project        %s\n" "$PROJECT"
printf "  containers     %s\n" "$cn"
printf "  images built   %s\n" "$im"
for d in state models ollama-models; do
  [ -d "$d" ] && printf "  directory      %-14s %s\n" "$d" "$(du -sh "$d" 2>/dev/null | cut -f1)"
done
[ -f .env ] && printf "  file           .env\n"
if [ "$ALL" = "1" ]; then
  printf "  \033[33malso\033[0m           nginx + mailpit images, and the Docker BUILD CACHE\n"
  printf "                 (the build cache is shared with your other projects)\n"
fi
if [ "$MODEL" = "1" ]; then
  printf "  \033[33malso\033[0m           ollama model llama3.2:3b (~2 GB, shared with anything\n"
  printf "                 else on this machine that uses it)\n"
fi

if [ "$DRY" = "0" ] && [ "$YES" = "0" ]; then
  printf "\n  Proceed? [y/N] "
  read -r a; case "$a" in y|Y|yes) ;; *) echo "  cancelled"; exit 0 ;; esac
fi

# ---- containers, networks, volumes, locally built images -------------------
say "Docker"
if [ "$ALL" = "1" ]; then
  run docker compose --profile ollama down --rmi all -v --remove-orphans
  ok "containers, networks, and all images including nginx and mailpit"
else
  # --rmi local removes only images compose BUILT (no custom image: name),
  # which is exactly the seven services. Pinned third-party images stay.
  run docker compose --profile ollama down --rmi local -v --remove-orphans
  ok "containers, networks, and the images built here"
  skip "nginx and mailpit (pinned third-party; --all removes them)"
fi

if [ "$ALL" = "1" ]; then
  run docker builder prune -af
  ok "Docker build cache"
fi

# ---- host directories ------------------------------------------------------
say "Files"
for d in state models ollama-models; do
  [ -d "$d" ] || continue
  if [ "$DRY" = "1" ]; then
    printf "  \033[2mwould remove:\033[0m %s\n" "$d"
  elif rm -rf "$d" 2>/dev/null && [ ! -d "$d" ]; then
    ok "$d"
  else
    # On Linux, containers run as root and leave root-owned files behind.
    # Delete them from inside a container rather than asking for sudo.
    if docker run --rm -v "$PWD:/w" alpine sh -c "rm -rf /w/$d" >/dev/null 2>&1 && [ ! -d "$d" ]; then
      ok "$d (root-owned; removed from a container)"
    else
      warn "$d could not be removed — try: sudo rm -rf $d"
    fi
  fi
done
if [ -f .env ]; then
  run rm -f .env
  ok ".env"
fi

# ---- the model (opt-in; it is outside this repo) ---------------------------
if [ "$MODEL" = "1" ]; then
  say "Ollama model"
  if command -v ollama >/dev/null 2>&1; then
    run ollama rm llama3.2:3b
    ok "llama3.2:3b"
  else
    skip "no ollama on PATH (a containerised one went with its directory)"
  fi
fi

say "Done"
if [ "$DRY" = "1" ]; then
  printf "  Dry run — nothing was changed.\n\n"
else
  printf "  The repo itself is still here. Delete the directory to finish,\n"
  printf "  or run ./setup.sh to start over.\n\n"
  [ "$ALL" = "0" ] && printf "  Still on disk: nginx and mailpit images, and the Docker build\n  cache. Use --all to remove those too.\n\n"
fi
