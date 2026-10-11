#!/usr/bin/env bash
# MedCheck demo rehearsal — SAFE for existing patient data by default.
#
#   scripts/demo_rehearsal.sh [HUB_URL] [--with-writes]
#
# Uses .venv-full/bin/python when present, else python3 (stdlib only); override
# with MEDCHECK_PY=/path/to/python.
#
# Default run (read-only for patient data):
#   hub health, state shape, verification statuses for the known / wrong /
#   strength-mismatch / blurry samples, and the guarantee that a scan never
#   records a dose. Scans themselves are created (scan rows are expected and
#   harmless); no medication, dose or alert is written, changed or deleted.
#
# --with-writes additionally rehearses the write path with one DISPOSABLE
#   fixture medication named Rehearsal-<HHMMSS> (never an existing med):
#     create via scan -> complete, duplicate add -> 409,
#     first fixture dose log -> 200, second -> 409,
#     then cleanup (also on failure via an EXIT trap):
#       soft stop DELETE /medications/<id>, verify it leaves /state, and if the
#       docker CLI and the db container are reachable, delete ONLY that fixture
#       row (exact id captured from the add response, guarded by the
#       Rehearsal- name prefix). No other medication, dose, scan or alert is
#       ever touched.
#   Every fixture state change is listed at the end.
#
# The script never calls docker compose down/recreate and never deletes
# volumes. Set MEDCHECK_DB_CONTAINER to override the db container name
# (default: medcheck-backend-db).
set -uo pipefail
cd "$(dirname "$0")/.."

HUB="http://127.0.0.1:8000/hub"
WRITES=0
for arg in "$@"; do
  case "$arg" in
    --with-writes) WRITES=1 ;;
    http://*|https://*) HUB="${arg%/}" ;;
    *) echo "unknown argument: $arg (usage: $0 [HUB_URL] [--with-writes])" >&2; exit 2 ;;
  esac
done

PY="${MEDCHECK_PY:-}"
if [ -z "$PY" ]; then
  if [ -x ".venv-full/bin/python" ]; then
    PY=".venv-full/bin/python"
  elif command -v python3 >/dev/null 2>&1; then
    PY="python3"
  else
    echo "python3 not found (set MEDCHECK_PY)" >&2
    exit 2
  fi
fi
"$PY" -c "import json,urllib.request" 2>/dev/null || { echo "$PY cannot run the rehearsal helpers (set MEDCHECK_PY)" >&2; exit 2; }
DB_CONTAINER="${MEDCHECK_DB_CONTAINER:-medcheck-backend-db}"
STAMP="$(date +%H%M%S)"
PASS=0; FAIL=0
FIXTURE_HUB_ID=""
FIXTURE_MED_UUID=""
FIXTURE_NAME=""
FIXTURE_CLEANED=0
STATE_CHANGES=()

say()  { printf "%-58s %s\n" "$1" "$2"; }
ok()   { say "$1" "PASS"; PASS=$((PASS+1)); }
bad()  { say "$1" "FAIL ($2)"; FAIL=$((FAIL+1)); }
info() { say "$1" "INFO ($2)"; }
note() { STATE_CHANGES+=("$1"); }

hub_state() { curl -sf -m 20 "$HUB/state"; }

fingerprint() {
  "$PY" - "$HUB" <<'PYEOF'
import json, sys, urllib.request
base = sys.argv[1].rstrip("/")
data = json.load(urllib.request.urlopen(base + "/state", timeout=20))
print(json.dumps({
    "medications": sorted([[m.get("id"), m.get("name")] for m in data.get("medications", [])], key=lambda row: str(row[0])),
    "doses": sorted(d.get("id") for d in data.get("doses", [])),
    "alerts": sorted(a.get("id") for a in data.get("alerts", [])),
}, sort_keys=True))
PYEOF
}

scan_count() {
  hub_state | "$PY" -c "import json,sys; print(len(json.load(sys.stdin).get('scans', [])))"
}

status_for_sample() {
  local sample="$1" out
  out="$(mktemp /tmp/rehearsal_scan.XXXXXX)"
  if ! curl -sf -m 180 -X POST -F "photo=@samples/$sample" "$HUB/scans" > "$out"; then
    rm -f "$out"
    echo "request_failed"
    return
  fi
  "$PY" -c "import json,sys; print((json.load(open(sys.argv[1])).get('verification') or {}).get('status','none'))" "$out"
  rm -f "$out"
}

# Cleanup is scoped to the disposable fixture only; it is safe to call twice.
cleanup_fixture() {
  [ "$WRITES" = "1" ] || return 0
  [ -n "$FIXTURE_HUB_ID" ] || return 0
  local code present out rc

  code=$(curl -s -m 20 -o /tmp/rehearsal_stop.json -w "%{http_code}" -X DELETE "$HUB/medications/$FIXTURE_HUB_ID")
  if [ "$code" = "200" ]; then
    note "cleanup: soft stop DELETE /medications/$FIXTURE_HUB_ID -> 200 ($FIXTURE_NAME)"
  else
    note "cleanup: soft stop DELETE /medications/$FIXTURE_HUB_ID -> HTTP $code ($FIXTURE_NAME)"
  fi

  present=$(hub_state | "$PY" -c "import json,sys; print(any(str(m.get('id'))==sys.argv[1] for m in json.load(sys.stdin).get('medications',[])))" "$FIXTURE_HUB_ID")
  if [ "$present" = "False" ]; then
    ok "fixture no longer in /state after cleanup"
  else
    bad "fixture still in /state after cleanup" "id=$FIXTURE_HUB_ID"
  fi

  if command -v docker >/dev/null 2>&1 && docker exec "$DB_CONTAINER" true >/dev/null 2>&1; then
    out=$(docker exec "$DB_CONTAINER" psql -U medcheck -d medcheck -v ON_ERROR_STOP=1 -tAc \
      "DELETE FROM hub_medications WHERE id = $FIXTURE_HUB_ID AND medication_id IN (SELECT id FROM medications WHERE name LIKE 'Rehearsal-%') RETURNING id" 2>&1)
    rc=$?
    if [ $rc -eq 0 ] && [ -n "${out//[[:space:]]/}" ]; then
      note "cleanup: deleted fixture hub_medications row id=$FIXTURE_HUB_ID (psql, Rehearsal- guarded)"
    elif [ $rc -eq 0 ]; then
      note "cleanup: fixture hub_medications row already absent (id=$FIXTURE_HUB_ID)"
    else
      info "docker row cleanup skipped" "psql: $(printf '%s' "$out" | tail -1)"
    fi
    if [ -n "$FIXTURE_MED_UUID" ]; then
      out=$(docker exec "$DB_CONTAINER" psql -U medcheck -d medcheck -v ON_ERROR_STOP=1 -tAc \
        "DELETE FROM medications WHERE id = '$FIXTURE_MED_UUID'::uuid AND name LIKE 'Rehearsal-%' RETURNING id" 2>&1)
      rc=$?
      if [ $rc -eq 0 ] && [ -n "${out//[[:space:]]/}" ]; then
        note "cleanup: deleted fixture medications row $FIXTURE_MED_UUID (psql, Rehearsal- guarded)"
      else
        info "catalog row kept" "still referenced by fixture history (id=$FIXTURE_MED_UUID); no other rows touched"
      fi
    fi
  else
    info "docker cleanup skipped" "docker or $DB_CONTAINER not reachable"
  fi
  FIXTURE_CLEANED=1
}

finish() {
  trap - EXIT
  local rc=$?
  [ "$FAIL" = "0" ] || rc=1
  if [ "$FIXTURE_CLEANED" = "0" ]; then
    cleanup_fixture
  fi
  echo
  echo "rehearsal: $PASS passed, $FAIL failed"
  if [ ${#STATE_CHANGES[@]} -eq 0 ]; then
    echo "state changes: none (read-only)"
  else
    echo "state changes:"
    for change in "${STATE_CHANGES[@]}"; do
      echo "  - $change"
    done
  fi
  exit "$rc"
}
trap finish EXIT

echo "hub: $HUB"
if [ "$WRITES" = "1" ]; then
  echo "mode: --with-writes (one disposable Rehearsal- fixture, auto-cleanup)"
else
  echo "mode: read-only (existing patient data untouched)"
fi
echo

# 1. health + state shape
if curl -sf -m 10 "$HUB/health" >/dev/null; then
  ok "hub health"
else
  bad "hub health" "unreachable"
  exit 1
fi
STATE=$(hub_state) || { bad "hub state" "unreachable"; exit 1; }
if echo "$STATE" | "$PY" -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if isinstance(d.get('hub'), dict) and isinstance(d.get('medications'), list) else 1)"; then
  ok "state shape (hub + medications)"
else
  bad "state shape" "missing hub/medications"
fi

FP_BEFORE=$(fingerprint)
SCANS_BEFORE=$(scan_count)
MEDS_COUNT=$(echo "$STATE" | "$PY" -c "import json,sys; print(len(json.load(sys.stdin).get('medications', [])))")
DOSE0=$(echo "$STATE" | "$PY" -c "import json,sys; print(len(json.load(sys.stdin).get('doses', [])))")
info "baseline fingerprint" "meds=$MEDS_COUNT doses=$DOSE0 scans=$SCANS_BEFORE"

# 2. verification statuses — scans only, never a dose
V=$(status_for_sample label_metformin.png)
case "$V" in
  due_now|not_due|already_taken) ok "known bottle -> verification '$V'" ;;
  *) bad "known bottle verification" "got '$V'" ;;
esac

V=$(status_for_sample label_furosemide_noform.png)
[ "$V" = "wrong_medication" ] && ok "untracked bottle -> wrong_medication" || bad "untracked bottle" "got '$V'"

V=$(status_for_sample label_lisinopril20.png)
[ "$V" = "strength_mismatch" ] && ok "20 mg vs 10 mg prescription -> strength_mismatch" || bad "strength mismatch" "got '$V'"

V=$(status_for_sample label_metformin_blurry.png)
[ "$V" = "uncertain" ] && ok "blurry label -> uncertain" || bad "blurry label" "got '$V'"

# 3. read-only guarantees
DOSE1=$(hub_state | "$PY" -c "import json,sys; print(len(json.load(sys.stdin).get('doses', [])))")
[ "$DOSE0" = "$DOSE1" ] && ok "scan did NOT record a dose" || bad "scan recorded a dose" "$DOSE0 -> $DOSE1"

FP_AFTER=$(fingerprint)
if [ "$FP_BEFORE" = "$FP_AFTER" ]; then
  ok "no medication/dose/alert data changed (read-only)"
else
  bad "read-only fingerprint" "state differs"
fi
SCANS_AFTER=$(scan_count)
info "scan rows" "$SCANS_BEFORE -> $SCANS_AFTER (created scans are allowed; scans never record doses)"

# 4. write rehearsal — disposable fixture only, behind --with-writes
if [ "$WRITES" = "1" ]; then
  echo
  FIXTURE_NAME="Rehearsal-$STAMP"
  FIXTURE_SLOT="$(date +%H:%M)"
  info "fixture" "$FIXTURE_NAME (slot $FIXTURE_SLOT)"

  SCAN_ID=$(curl -s -m 180 -X POST -F "photo=@samples/label_pantoprazole.png" "$HUB/scans" | "$PY" -c "import json,sys; print(json.load(sys.stdin).get('id',''))")
  [ -n "$SCAN_ID" ] && ok "fixture scan created (scan $SCAN_ID)" || bad "fixture scan" "no scan id"

  BODY="{\"name\":\"$FIXTURE_NAME\",\"strength\":\"40 mg\",\"dosage_form\":\"tablet\",\"dose_amount\":\"1\",\"schedule_times\":\"$FIXTURE_SLOT\",\"quantity_start\":\"10\",\"refills_remaining\":\"1\"}"
  ADD_CODE=$(curl -s -m 60 -o /tmp/rehearsal_add.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$BODY" "$HUB/scans/$SCAN_ID/complete")
  FIXTURE_HUB_ID=$("$PY" -c "import json; m=(json.load(open('/tmp/rehearsal_add.json')).get('medication') or {}); print(m.get('id',''))")
  FIXTURE_MED_UUID=$("$PY" -c "import json; m=(json.load(open('/tmp/rehearsal_add.json')).get('medication') or {}); print(m.get('medication_uuid',''))")
  ADDED_NAME=$("$PY" -c "import json; m=(json.load(open('/tmp/rehearsal_add.json')).get('medication') or {}); print(m.get('name',''))")
  if [ "$ADD_CODE" = "200" ] && [ "$ADDED_NAME" = "$FIXTURE_NAME" ] && [ -n "$FIXTURE_HUB_ID" ]; then
    ok "fixture created '$FIXTURE_NAME' (hub id $FIXTURE_HUB_ID)"
    note "create: scan $SCAN_ID -> medication $FIXTURE_HUB_ID ($FIXTURE_NAME, form tablet, slot $FIXTURE_SLOT)"
  else
    bad "fixture create" "HTTP $ADD_CODE name='$ADDED_NAME'"
  fi

  DUP=$(curl -s -m 60 -o /dev/null -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "$BODY" "$HUB/scans/$SCAN_ID/complete")
  [ "$DUP" = "409" ] && ok "duplicate add refused (409)" || bad "duplicate add" "HTTP $DUP"

  if [ -n "$FIXTURE_HUB_ID" ]; then
    C1=$(curl -s -m 60 -o /tmp/rehearsal_d1.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "{\"method\":\"dashboard\",\"slot\":\"$FIXTURE_SLOT\"}" "$HUB/medications/$FIXTURE_HUB_ID/doses")
    C2=$(curl -s -m 60 -o /tmp/rehearsal_d2.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d "{\"method\":\"dashboard\",\"slot\":\"$FIXTURE_SLOT\"}" "$HUB/medications/$FIXTURE_HUB_ID/doses")
    if [ "$C1" = "200" ]; then
      ok "fixture dose logged once (200)"
      note "dose: logged $FIXTURE_NAME slot $FIXTURE_SLOT (medication $FIXTURE_HUB_ID)"
    else
      bad "fixture dose log" "HTTP $C1 $(head -c 120 /tmp/rehearsal_d1.json 2>/dev/null)"
    fi
    D2=$(cat /tmp/rehearsal_d2.json 2>/dev/null)
    if [ "$C2" = "409" ] && printf '%s' "$D2" | grep -qiE "already logged|nothing due|all of today's"; then
      ok "second dose log refused (409 already logged / nothing due)"
    else
      bad "second dose log" "HTTP $C2 $(printf '%s' "$D2" | head -c 120)"
    fi
  fi

  # Explicit cleanup + post-check; the EXIT trap still covers aborts.
  FIXTURE_ID_FOR_CHECK="$FIXTURE_HUB_ID"
  cleanup_fixture
  if [ -n "$FIXTURE_ID_FOR_CHECK" ]; then
    FP_CLEAN=$(fingerprint)
    if [ "$FP_CLEAN" = "$FP_BEFORE" ]; then
      ok "state restored after fixture cleanup (meds/doses/alerts identical)"
    else
      bad "state not restored after cleanup" "fingerprint differs"
    fi
  fi
  FIXTURE_HUB_ID=""
fi
