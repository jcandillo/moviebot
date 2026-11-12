#!/usr/bin/env bash
# Weekly reco refresh (Thursday ~3 PM CT preview session). Preview-only: writes DB tables, eval + scorecard files; never publishes to the Frame.
set -uo pipefail
cd "$(dirname "$0")/.."; PY=${PY:-python3}; D=$(date +%Y%m%d)
$PY reco/reco_log.py ingest-reactions
$PY reco/pool.py                      # flagged sources (discover, recs/similar, MovieLens, person search) + metadata/providers for new titles
$PY reco/quality.py
$PY reco/precompute.py
$PY reco/personal_model.py            # stored; only used once >= 50 labelled reactions
$PY reco/evaluate.py reco/eval-$D.json --grid > reco/eval-$D.log 2>&1
$PY reco/scorecard.py
