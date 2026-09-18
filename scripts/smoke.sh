#!/usr/bin/env bash
# ===========================================================================
# GATE 1 — the one that gates everything else.
#
#   "curl http://northwind.local/pwned?team=TEST&level=1 from another device puts
#    TEST on the scoreboard. Until that works, build nothing else."
#
# Run it against localhost while building, and against http://northwind.local FROM A
# SECOND DEVICE before you trust it. Those are different tests: the second one
# also proves DNS, the router, and the firewall.
#
# Usage:  bash scripts/smoke.sh [base-url]      default: http://localhost
# ===========================================================================
set -uo pipefail

BASE="${1:-http://localhost}"
TEAM="SMOKE-$(date +%H%M%S)"
pass=0; fail=0

ok()  { printf "  \033[32mPASS\033[0m  %s\n" "$*"; pass=$((pass+1)); }
bad() { printf "  \033[31mFAIL\033[0m  %s\n" "$*"; fail=$((fail+1)); }
say() { printf "\n\033[1;36m==> %s\033[0m\n" "$*"; }

code() { curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$1"; }
body() { curl -s --max-time 6 "$1"; }

say "Target: $BASE   team: $TEAM"

# --- 1. the proxy itself ---------------------------------------------------
say "Entry point"
[ "$(code "$BASE/health")" = "200" ] && ok "nginx /health" || bad "nginx /health unreachable"

# --- 2. services that should exist now -------------------------------------
say "Built services (Gates 0-3)"
[ "$(code "$BASE/hub/health")"     = "200" ] && ok "hub"        || bad "hub ($(code "$BASE/hub/health"))"
[ "$(code "$BASE/feed")"           = "200" ] && ok "listener"   || bad "listener ($(code "$BASE/feed"))"
[ "$(code "$BASE/")"               = "200" ] && ok "scoreboard" || bad "scoreboard ($(code "$BASE/"))"
[ "$(code "$BASE/scoreboard")"     = "200" ] && ok "scoreboard /scoreboard alias (all 14 notebooks use it)" \
                                             || bad "/scoreboard ($(code "$BASE/scoreboard"))"
[ "$(code "$BASE/scan/health")"    = "200" ] && ok "scanner"    || bad "scanner ($(code "$BASE/scan/health"))"

# --- 3. Workshop 1 surfaces -------------------------------------------------
say "Workshop 1 (mailmate + mail sink)"
for r in /api/health /mail/; do
  c=$(code "$BASE$r")
  [ "$c" = "200" ] && ok "$r -> 200" || bad "$r -> $c"
done

# --- 4. THE GATE -----------------------------------------------------------
say "Gate 1: beacon -> scoreboard"

before=$(body "$BASE/feed" | grep -c "$TEAM" || true)
[ "$(code "$BASE/pwned?team=$TEAM&level=1")" = "200" ] \
  && ok "beacon accepted" || bad "beacon rejected"

curl -s --max-time 6 "$BASE/pwned?team=$TEAM&level=3" >/dev/null

sleep 0.5
if body "$BASE/feed" | grep -q "$TEAM"; then
  ok "beacon is in the listener feed"
else
  bad "beacon NOT in the feed"
fi

if body "$BASE/scores" | grep -q "$TEAM"; then
  ok "team is on the scoreboard"
else
  bad "team NOT on the scoreboard (scoreboard cannot reach listener?)"
fi

lvl=$(body "$BASE/scores" | tr ',' '\n' | grep -A0 'top_level' | head -1)
printf "  \033[2m%s\033[0m\n" "scores row: $(body "$BASE/scores" | tr '{' '\n' | grep "$TEAM" | head -1)"

# --- 5. Workshop 1 exfil route ---------------------------------------------
say "Workshop 1 exfil route"
ct=$(curl -s -o /dev/null -w '%{content_type}' --max-time 6 "$BASE/img/SMOKETEST123.png")
[ "$ct" = "image/png" ] && ok "/img/<data>.png returns a PNG" || bad "/img returned $ct"
body "$BASE/feed" | grep -q "SMOKETEST123" \
  && ok "exfil recorded (as UNKNOWN — no flags.json until MailMate exists)" \
  || bad "exfil not recorded"

# --- verdict ---------------------------------------------------------------
echo
printf -- "----------------------------------------------\n"
if [ $fail -eq 0 ]; then
  printf "\033[1;32m  GATE 1 PASSED  —  %d checks\033[0m\n" "$pass"
  printf "  Open %s on the projector.\n" "$BASE"
  printf "\n  \033[1mNow run this again from a SECOND DEVICE:\033[0m\n"
  printf "    bash scripts/smoke.sh http://northwind.local\n"
  printf "  That version also tests DNS, the router and the firewall.\n"
else
  printf "\033[1;31m  GATE 1 FAILED  —  %d passed, %d failed\033[0m\n" "$pass" "$fail"
  printf "  Build nothing else until this is green.\n"
fi
printf -- "----------------------------------------------\n"
exit $((fail > 0))
