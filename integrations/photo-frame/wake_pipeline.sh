#!/usr/bin/env bash
# Optional photo-frame wake helper. MovieBot core runs without this file.
# After copying votes/actions/picks snapshots from the display host to the agent host, enrich a publish plan.
# Usage: wake_pipeline.sh VOTES_SNAPSHOT ACTIONS_SNAPSHOT PICKS_SNAPSHOT
# NEVER calls the publisher; no frame-host writes from this script.
# Env: LEASE_TOKEN, FRAME_VOTES_DIR, FRAME_MACHINE_ID, RAW_DB, MOVIEBOT_DB, RECS, ...
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CORE="$(cd "$HERE/../../pipeline" && pwd)"
cd "$CORE"
V=$1; A=$2; P=$3
M=${FRAME_MACHINE_ID:-frame-host}
D=${FRAME_VOTES_DIR:-./frame-votes}
RAW_DB=${RAW_DB:-./raw_votes.db}
MOVIEBOT_DB=${MOVIEBOT_DB:-./moviebot.db}
RECS=${RECS:-./recommendations.json}
NEWCANDS=${NEWCANDS:-./new_releases_candidates.json}
SNAPSHOTS=${SNAPSHOTS:-./snapshots}
OUT_DIR=${OUT_DIR:-./out}
FETCH=${FETCH:-1}
export MOVIEBOT_BACKUP_DIR=${MOVIEBOT_BACKUP_DIR:-./backups}
if [ -z "${LEASE_TOKEN:-}" ]; then
  LEASE_TOKEN=$(python3 lease.py claim --db "$RAW_DB" --note "wake_pipeline" | python3 -c "import sys,json;print(json.load(sys.stdin).get('token',''))")
  [ -z "$LEASE_TOKEN" ] && { echo '{"ok":false,"error":"lease_busy"}'; exit 75; }
  trap 'python3 lease.py release --db "$RAW_DB" --token "$LEASE_TOKEN" >/dev/null' EXIT
fi
LT=(--lease-token "$LEASE_TOKEN")
FA=(--moviebot-db "$MOVIEBOT_DB" --rawdb "$RAW_DB" --recs "$RECS" --newcands "$NEWCANDS" --snapshots "$SNAPSHOTS" --picks "$P" "${LT[@]}")
[ "$FETCH" = 1 ] && FA+=(--fetch)
HD=(); [ -n "${JW_HTML_DIR:-}" ] && HD=(--html-dir "$JW_HTML_DIR")
mkdir -p "$OUT_DIR" "$SNAPSHOTS" "$MOVIEBOT_BACKUP_DIR"
python3 intake.py import "$V" --db "$RAW_DB" --source-path "$D/votes.jsonl" --machine "$M" >&2
python3 movie_night.py import-actions "$A" --source-path "$D/actions.jsonl" --machine "$M" --db "$RAW_DB" "${LT[@]}" >&2
python3 feedback_apply.py run "${FA[@]}" >&2
OUT="$OUT_DIR/plan.$(date +%Y%m%d-%H%M%S-%N).json"
python3 movie_night.py plan --picks "$P" --db "$RAW_DB" --recs "$RECS" --moviebot-db "$MOVIEBOT_DB" --current-pool-only "${LT[@]}" > "$OUT"
python3 where_to_watch.py enrich-plan "$OUT" --db "$RAW_DB" "${LT[@]}" --out "${OUT%.json}.enriched.json" "${HD[@]}"
cat "${OUT%.json}.enriched.json"
# Optional genre stage
if [ -f "$CORE/genre_flow.py" ] && [ -f "$HERE/../../tools/build.py" ]; then
  GPOOL="$OUT_DIR/genre_pool.$(date +%Y%m%d-%H%M%S-%N).json"; GOUT="${OUT%.json}.genre.json"
  MOVIEBOT_DB="$MOVIEBOT_DB" STAGING_DB="${STAGING_DB:-./staging.db}" POOL_OUT="$GPOOL" python3 "$HERE/../../tools/build.py" >&2 || true
  python3 genre_flow.py plan --picks "$P" --db "$RAW_DB" --moviebot-db "$MOVIEBOT_DB" --pool "$GPOOL" "${LT[@]}" > "$GOUT"
  PF=(); [ -n "${POSTER_FIXTURE:-}" ] && PF=(--poster-fixture "$POSTER_FIXTURE")
  python3 genre_flow.py enrich "$GOUT" --db "$RAW_DB" "${LT[@]}" --out "${GOUT%.json}.enriched.json" "${HD[@]}" "${PF[@]}"
  echo; echo "GENRE_ENRICHED=${GOUT%.json}.enriched.json"
fi
