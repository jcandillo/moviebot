"""Per-instance owner-preference policy, loaded from config/local.json (gitignored).

Onboarding answers (chosen genres, seed ratings) are personal data and never live in this
repository. Copy config/local.example.json to config/local.json and let your agent fill the
"onboarding" block during taste-only onboarding. Hard excludes apply to every pool, refresh and plan.
"""
import json, os
from pathlib import Path

_CFG = Path(os.environ.get("MOVIEBOT_CONFIG") or Path(__file__).resolve().parent.parent / "config" / "local.json")


def _load():
    try:
        return json.loads(_CFG.read_text()).get("onboarding", {}) or {}
    except (OSError, ValueError):
        return {}


_ob = _load()
QUESTIONNAIRE_GENRES = set(_ob.get("genres", []))                                  # positive only; unchosen genres are neutral
SEED_NOPE = {int(k): v for k, v in (_ob.get("seed_nope") or {}).items()}          # owner rated 'nope' -> never suggest
SEED_FAMILIAR = {int(k): v for k, v in (_ob.get("seed_familiar") or {}).items()}  # rated/already known -> not re-suggested
HARD_EXCLUDE = set(SEED_NOPE) | set(SEED_FAMILIAR)

# Services the owner says they have, with provider-name aliases. Used only to list those services first;
# never an entitlement claim (home eligibility needs verified_active subscription evidence).
_cfg_all = {}
try:
    _cfg_all = json.loads(_CFG.read_text())
except (OSError, ValueError):
    pass
REPORTED_SUBSCRIPTIONS = {k: list(v) for k, v in (_cfg_all.get("reported_subscriptions") or {}).items()}
