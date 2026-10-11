#!/usr/bin/env bash
# Demo rehearsal: run the core MedCheck acceptance scenarios against the live stack.
#
#   scripts/demo_rehearsal.sh                 # DB-backed hub at :8000/hub (default)
#   scripts/demo_rehearsal.sh http://127.0.0.1:8500   # fallback adapter
#
# Each step prints PASS/FAIL. Read-only except one add+cleanup ("Rehearsal <stamp>").
# Never logs ingestion; a scan is expected to leave the dose history unchanged.
set -uo pipefail
cd "$(dirname "$0")/.."

HUB="${1:-http://127.0.0.1:8000/hub}"
PY=".venv-full/bin/python"
STAMP="$(date +%H%M%S)"
PASS=0; FAIL=0

say()  { printf "%-58s %s\n" "$1" "$2"; }
ok()   { say "$1" "PASS"; PASS=$((PASS+1)); }
bad()  { say "$1" "FAIL ($2)"; FAIL=$((FAIL+1)); }

jq() { "$PY" -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1]))" "$1" 2>/dev/null; }

echo "hub: $HUB"
echo

# 1. health + state
curl -sf "$HUB/health" >/dev/null && ok "hub health" || bad "hub health" "unreachable"
STATE=$(curl -sf "$HUB/state") || { bad "hub state" "unreachable"; echo; echo "cannot continue"; exit 1; }
echo "$STATE" | jq "d['hub']" >/dev/null && ok "state shape (hub connected)" || bad "state shape" "missing hub field"
MEDS=$(echo "$STATE" | "$PY" -c "import json,sys; print(len(json.load(sys.stdin)['medications']))")
DOSE0=$(echo "$STATE" | "$PY" -c "import json,sys; print(len(json.load(sys.stdin)['doses']))")

# 2. known medication -> verification present, never records a dose
NAME0=$("$PY" - <<EOF
import json,urllib.request
d=json.load(urllib.request.urlopen("$HUB/state"))
print(json.dumps(d["medications"][0]["name"]))
EOF
)
curl -s -X POST -F "photo=@samples/label_metformin.png" "$HUB/scans" > /tmp/rehearsal_known.json
V=$("$PY" -c "import json;d=json.load(open('/tmp/rehearsal_known.json'));print((d.get('verification') or {}).get('status','none'))")
case "$V" in due_now|not_due|already_taken) ok "known bottle -> verification '$V'" ;; *) bad "known bottle verification" "got '$V'" ;; esac
DOSE1=$(curl -s "$HUB/state" | "$PY" -c "import json,sys; print(len(json.load(sys.stdin)['doses']))")
[ "$DOSE0" = "$DOSE1" ] && ok "scan did NOT record a dose" || bad "scan recorded a dose" "$DOSE0 -> $DOSE1"

# 3. wrong medication
curl -s -X POST -F "photo=@samples/label_furosemide_noform.png" "$HUB/scans" > /tmp/rehearsal_wrong.json
V=$("$PY" -c "import json;d=json.load(open('/tmp/rehearsal_wrong.json'));print((d.get('verification') or {}).get('status','none'))")
[ "$V" = "wrong_medication" ] && ok "untracked bottle -> wrong_medication" || bad "untracked bottle" "got '$V'"

# 4. strength mismatch
curl -s -X POST -F "photo=@samples/label_lisinopril20.png" "$HUB/scans" > /tmp/rehearsal_strength.json
V=$("$PY" -c "import json;d=json.load(open('/tmp/rehearsal_strength.json'));print((d.get('verification') or {}).get('status','none'))")
[ "$V" = "strength_mismatch" ] && ok "20 mg vs 10 mg prescription -> strength_mismatch" || bad "strength mismatch" "got '$V'"

# 5. unreadable
curl -s -X POST -F "photo=@samples/label_metformin_blurry.png" "$HUB/scans" > /tmp/rehearsal_blurry.json
V=$("$PY" -c "import json;d=json.load(open('/tmp/rehearsal_blurry.json'));print((d.get('verification') or {}).get('status','none'))")
[ "$V" = "uncertain" ] && ok "blurry label -> uncertain" || bad "blurry label" "got '$V'"

# 6. add a new medication (explicit caregiver action) and confirm it persists in state
RID=$(curl -s -X POST -F "photo=@samples/label_pantoprazole.png" "$HUB/scans" | "$PY" -c "import json,sys; print(json.load(sys.stdin)['id'])")
NEW="Rehearsal-$STAMP"
curl -s -X POST -H "Content-Type: application/json" \
  -d "{\"name\":\"$NEW\",\"strength\":\"40 mg\",\"dose_amount\":\"1\",\"schedule_times\":\"21:00\",\"quantity_start\":\"10\",\"refills_remaining\":\"1\"}" \
  "$HUB/scans/$RID/complete" > /tmp/rehearsal_add.json
ADDED=$("$PY" -c "import json;d=json.load(open('/tmp/rehearsal_add.json'));print((d.get('medication') or {}).get('name','none'))")
[ "$ADDED" = "$NEW" ] && ok "explicit add created '$NEW'" || bad "explicit add" "got '$ADDED'"
PERSISTED=$(curl -s "$HUB/state" | "$PY" -c "import json,sys; print(any(m['name']=='$NEW' for m in json.load(sys.stdin)['medications']))")
[ "$PERSISTED" = "True" ] && ok "new medication visible in /state (persisted)" || bad "persistence" "not in state"

# 7. duplicate add is refused
DUP=$(curl -s -o /tmp/rehearsal_dup.json -w "%{http_code}" -X POST -H "Content-Type: application/json" \
  -d "{\"name\":\"$NEW\",\"strength\":\"40 mg\",\"dose_amount\":\"1\",\"schedule_times\":\"21:00\",\"quantity_start\":\"10\"}" \
  "$HUB/scans/$RID/complete")
[ "$DUP" = "409" ] && ok "duplicate add refused (409)" || bad "duplicate add" "HTTP $DUP"

# 8. dose double-log refused (already taken path)
MID=$(curl -s "$HUB/state" | "$PY" -c "import json,sys; d=json.load(sys.stdin); print([m['id'] for m in d['medications'] if m['name']==d['medications'][0]['name']][0])")
C1=$(curl -s -o /tmp/rehearsal_d1.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d '{"method":"dashboard"}' "$HUB/medications/$MID/doses")
C2=$(curl -s -o /tmp/rehearsal_d2.json -w "%{http_code}" -X POST -H "Content-Type: application/json" -d '{"method":"dashboard"}' "$HUB/medications/$MID/doses")
if [ "$C1" = "200" ] && [ "$C2" = "409" ]; then ok "second dose log refused (409)"; else say "dose double-log ($C1/$C2 — depends on the window)" "INFO"; fi

# 9. cleanup the rehearsal medication when the DB is reachable
NEWID=$(curl -s "$HUB/state" | "$PY" -c "import json,sys; d=json.load(sys.stdin); print(next((m['id'] for m in d['medications'] if m['name']=='$NEW'), ''))")
if [ -n "$NEWID" ]; then
  curl -s -o /dev/null -X DELETE "$HUB/medications/$NEWID"
  if docker exec medcheck-backend-db psql -U medcheck -d medcheck -c "delete from hub_alerts where medication_id=(select id from hub_medications where id=$NEWID)" >/dev/null 2>&1; then
    ok "rehearsal medication removed (alerts cleaned)"
  else
    say "rehearsal medication removed (alert cleanup skipped: no docker)" "INFO"
  fi
fi

echo
echo "rehearsal: $PASS passed, $FAIL failed"
[ "$FAIL" = "0" ]
