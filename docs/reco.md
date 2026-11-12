# Reco layer: expert picks and continuous learning

Optional layer on top of the core pipeline (`reco/`). Everything is behind flags in `config/reco_flags.json`
(copy `config/reco_flags.example.json`), so each experiment can be switched off in one edit.

## What it adds
| Phase | Module | What it does |
|---|---|---|
| P0 measure | `reco_log.py`, `scorecard.py` | Logs every card shown (surface, slot, title, score, why, model, lane, where-to-watch status) and every reaction (up/down, Next, Watched, interview answers); weekly scorecard: acceptance, down/skip rate, hit rate, by model and lane |
| P1 quality + breadth | `quality.py`, `pool.py`, `history_ingest.py` | Bayesian weighted rating `WR = v/(v+m)·R + m/(v+m)·C` from TMDB (plus the local IMDb ratings file if present) with a vote-count floor; candidate pool from TMDB discover (genre × era), recommendations/similar of liked titles, optional person search; provider history import as already-seen exclusion + weak implicit signal |
| P2 collaborative | `ml_build.py`, `precompute.py` | Item embeddings from MovieLens 32M (positives = rating ≥ 4, truncated SVD, k=96), mapped to TMDB via `links.csv`; similarity to liked / disliked / implicitly watched titles as ranking features and as a candidate source |
| P3 learning | `ranker.py`, `personal_model.py`, `explore.py` | Blend ranker (content score + CF + quality + popularity); personal logistic regression on logged reactions (used only after ≥ 50 labels, blend weights are the fallback); Thompson-sampling lanes for ~10% discovery |
| Eval | `evaluate.py` | Leave-one-out over liked titles (+ optional implicit-history holdout): HR@10, NDCG@10, HR@50, MRR; `--grid` picks blend weights; a new ranker replaces the current one only if it wins |

The content score in `content.py` / `tp_adapter.py` is a generic stand-in. An instance with its own taste model replaces `tp_adapter.py` (same function names).

## Data and licenses (never commit data)
- **MovieLens 32M** (GroupLens, University of Minnesota): research use, no commercial or revenue-bearing use without permission, no endorsement implied; cite the dataset in publications. Download to `$MOVIEBOT_ML_DIR/ml-32m/` yourself. Neither the data nor derived factors are committed (`.gitignore`).
- **IMDb non-commercial datasets** (`title.ratings.tsv.gz`): personal and non-commercial use. Local only.
- **TMDB API**: per TMDB terms, with attribution; key in the environment (`TMDB_API_KEY`), never in files.
- Personal data (votes, history, interview answers, learned weights) stays in the instance database.

## Run
```bash
pip install numpy scipy          # only for ml_build.py / precompute.py / personal_model.py / evaluate.py
python3 reco/pool.py && python3 reco/quality.py
python3 reco/ml_build.py && python3 reco/precompute.py
python3 reco/evaluate.py reco/eval-$(date +%Y%m%d).json --grid
python3 reco/scorecard.py
```
`reco/refresh_all.sh` runs the weekly sequence (preview only; it never publishes to a display).

## Card rules still apply
Cards never show runtime; where-to-watch is required; In Theaters lists first-rate theaters only.
