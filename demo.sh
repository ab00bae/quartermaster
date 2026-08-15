#!/usr/bin/env bash
# Boots the API against a throwaway database and exercises the whole contract
# with curl, asserting on each response. Exits non-zero if any check fails, so
# it doubles as a smoke test.
#
#   ./demo.sh            run against a fresh demo.db on port 8000
#   PORT=9000 ./demo.sh  use a different port

set -uo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
DEMO_DB="demo.db"

if [ -t 1 ]; then
  GREEN=$'\033[32m'; RED=$'\033[31m'; BOLD=$'\033[1m'; DIM=$'\033[2m'; RESET=$'\033[0m'
else
  GREEN=''; RED=''; BOLD=''; DIM=''; RESET=''
fi

# Prefer the project virtualenv, so the demo does not depend on what happens to
# be on PATH. Works for both Windows (Scripts) and POSIX (bin) layouts.
if [ -x ".venv/Scripts/python.exe" ]; then
  PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

command -v curl >/dev/null 2>&1 || { echo "demo.sh needs curl on PATH." >&2; exit 1; }

pass=0
fail=0
SERVER_PID=""

cleanup() {
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  rm -f "$DEMO_DB"
}
trap cleanup EXIT

section() { printf "\n${BOLD}%s${RESET}\n" "$1"; }

record() {
  if [ "$1" = "1" ]; then
    printf "  ${GREEN}PASS${RESET}  %s\n" "$2"
    pass=$((pass + 1))
  else
    printf "  ${RED}FAIL${RESET}  %s\n" "$2"
    [ -n "${3:-}" ] && printf "        ${DIM}%s${RESET}\n" "$3"
    fail=$((fail + 1))
  fi
}

STATUS=""
BODY=""
request() {
  local method="$1" path="$2" data="${3:-}" raw
  if [ -n "$data" ]; then
    raw=$(curl -sS -X "$method" "${BASE}${path}" \
      -H 'Content-Type: application/json' -d "$data" -w $'\n%{http_code}')
  else
    raw=$(curl -sS -X "$method" "${BASE}${path}" -w $'\n%{http_code}')
  fi
  STATUS="${raw##*$'\n'}"
  BODY="${raw%$'\n'*}"
}

# Read a dotted path out of a JSON document without requiring jq.
jget() {
  printf '%s' "$1" | "$PY" -c '
import json, sys
data = json.load(sys.stdin)
for part in sys.argv[1].split("."):
    if part:
        data = data[int(part)] if part.lstrip("-").isdigit() else data[part]
print(data)
' "$2" 2>/dev/null
}

expect_status() {
  if [ "$STATUS" = "$1" ]; then
    record 1 "$2"
  else
    record 0 "$2" "expected HTTP $1, got ${STATUS:-none} — ${BODY}"
  fi
}

expect_eq() {
  if [ "$1" = "$2" ]; then
    record 1 "$3"
  else
    record 0 "$3" "expected '$1', got '$2'"
  fi
}

printf "${BOLD}quartermaster demo${RESET}\n"
printf "${DIM}python: %s${RESET}\n" "$PY"

rm -f "$DEMO_DB"
export DATABASE_URL="sqlite:///./${DEMO_DB}"

printf "${DIM}applying migrations...${RESET}\n"
if ! "$PY" -m alembic upgrade head >/dev/null 2>&1; then
  echo "Migrations failed. Run '$PY -m alembic upgrade head' to see why." >&2
  exit 1
fi

printf "${DIM}starting api on port %s...${RESET}\n" "$PORT"
"$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT" --log-level warning &
SERVER_PID=$!

ready=0
for _ in $(seq 1 60); do
  if curl -sS -o /dev/null "${BASE}/health" >/dev/null 2>&1; then
    ready=1
    break
  fi
  # The server died during startup; no point waiting out the timeout.
  kill -0 "$SERVER_PID" >/dev/null 2>&1 || break
  sleep 0.5
done

if [ "$ready" != "1" ]; then
  echo "API failed to come up on ${BASE}." >&2
  exit 1
fi

# ---------------------------------------------------------------------------

section "Service health"
request GET /health
expect_status 200 "GET /health returns 200"
expect_eq "ok" "$(jget "$BODY" status)" "reports status ok"

section "Creating stock"
request POST /items '{"sku":"anchor-001","name":"Danforth Anchor 8kg","quantity":10,"location":"HOLD-A","reorder_threshold":3}'
expect_status 201 "POST /items creates an item"
ITEM_ID=$(jget "$BODY" id)
expect_eq "ANCHOR-001" "$(jget "$BODY" sku)" "lowercase sku is normalised to uppercase"
expect_eq "False" "$(jget "$BODY" low_stock)" "10 units against a threshold of 3 is not low"

request POST /items '{"sku":"ANCHOR-001","name":"Duplicate","location":"HOLD-A"}'
expect_status 409 "duplicate sku is rejected"
expect_eq "DUPLICATE_SKU" "$(jget "$BODY" error.code)" "error code is DUPLICATE_SKU"

request POST /items '{"sku":"BAD-1","name":"Bad","location":"HOLD-A","quantity":-5}'
expect_status 422 "negative opening quantity is rejected"
expect_eq "VALIDATION_ERROR" "$(jget "$BODY" error.code)" "error code is VALIDATION_ERROR"

section "Moving stock"
request POST "/items/${ITEM_ID}/movements" '{"delta":5,"reason":"receipt","note":"spring resupply"}'
expect_status 201 "a receipt of +5 is accepted"
expect_eq "15" "$(jget "$BODY" quantity_after)" "quantity rises to 15"

request POST "/items/${ITEM_ID}/movements" '{"delta":-12,"reason":"sale","note":"outfitting slip 14"}'
expect_status 201 "a sale of -12 is accepted"
expect_eq "3" "$(jget "$BODY" quantity_after)" "quantity falls to 3"

request GET "/items/${ITEM_ID}"
expect_eq "True" "$(jget "$BODY" low_stock)" "at the reorder threshold the item flags as low"

request GET "/items?low_stock=true"
expect_eq "ANCHOR-001" "$(jget "$BODY" 0.sku)" "the low-stock filter surfaces it"

section "The business rule: stock cannot go negative"
request POST "/items/${ITEM_ID}/movements" '{"delta":-99,"reason":"sale"}'
expect_status 409 "a sale larger than stock on hand is rejected"
expect_eq "INSUFFICIENT_STOCK" "$(jget "$BODY" error.code)" "error code is INSUFFICIENT_STOCK"
expect_eq "3" "$(jget "$BODY" error.details.available)" "the error reports what was actually available"

request GET "/items/${ITEM_ID}"
expect_eq "3" "$(jget "$BODY" quantity)" "the rejected movement left stock untouched"

request GET "/items/${ITEM_ID}/movements"
expect_eq "3" "$(jget "$BODY" 0.quantity_after)" "and wrote no audit entry"

request POST "/items/${ITEM_ID}/movements" '{"delta":-3,"reason":"sale"}'
expect_status 201 "drawing down to exactly zero is allowed"
expect_eq "0" "$(jget "$BODY" quantity_after)" "quantity reaches 0"

request POST "/items/${ITEM_ID}/movements" '{"delta":0,"reason":"adjustment"}'
expect_status 422 "a zero-delta movement is rejected"

section "Audit log"
request GET "/items/${ITEM_ID}/movements"
expect_status 200 "GET /items/{id}/movements returns the log"
expect_eq "4" "$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)))')" "four movements recorded"
expect_eq "-3" "$(jget "$BODY" 0.delta)" "newest entry first"
expect_eq "opening balance" "$(jget "$BODY" 3.note)" "oldest entry is the opening balance"
expect_eq "0" "$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(sum(m["delta"] for m in json.load(sys.stdin)))')" "replaying the log reproduces the current quantity"

section "Updates and removal"
request PATCH "/items/${ITEM_ID}" '{"location":"LOCKER-1"}'
expect_status 200 "PATCH updates the location"
expect_eq "LOCKER-1" "$(jget "$BODY" location)" "location is changed"

request GET /items/99999
expect_status 404 "an unknown item returns 404"
expect_eq "ITEM_NOT_FOUND" "$(jget "$BODY" error.code)" "error code is ITEM_NOT_FOUND"

request DELETE "/items/${ITEM_ID}"
expect_status 204 "DELETE removes the item"

request GET "/items/${ITEM_ID}"
expect_status 404 "the item is gone"

request GET /movements
expect_eq "0" "$(printf '%s' "$BODY" | "$PY" -c 'import json,sys; print(len(json.load(sys.stdin)))')" "its audit entries were cascaded away"

# ---------------------------------------------------------------------------

total=$((pass + fail))
printf "\n${BOLD}%s${RESET}\n" "Summary"
printf "  %d/%d checks passed\n" "$pass" "$total"

if [ "$fail" -gt 0 ]; then
  printf "  ${RED}%d failed${RESET}\n\n" "$fail"
  exit 1
fi

printf "  ${GREEN}all checks passed${RESET}\n\n"
