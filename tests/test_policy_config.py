"""Owner taste data comes only from config, never from code."""
import json, os, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
res = []
def check(n, c):
    res.append(bool(c)); print(("PASS " if c else "FAIL ") + n)
def load(cfg_path):
    code = "import sys,json; sys.path.insert(0,'pipeline'); import policy as p; print(json.dumps([sorted(p.QUESTIONNAIRE_GENRES), sorted(p.HARD_EXCLUDE), sorted(p.REPORTED_SUBSCRIPTIONS)]))"
    env = dict(os.environ, MOVIEBOT_CONFIG=cfg_path, PYTHONDONTWRITEBYTECODE="1")
    return json.loads(subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True, check=True).stdout)
src = open(os.path.join(ROOT, "pipeline", "policy.py")).read()
check("policy.py holds no hard-coded title ids", not any(ch.isdigit() for line in src.splitlines() if "= {" in line and "#" not in line.split("=")[0] for ch in line.split("=", 1)[1].split("#")[0]))
check("missing config -> empty policy", load("/nonexistent/local.json") == [[], [], []])
with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
    json.dump({"onboarding": {"genres": ["Comedy"], "seed_nope": {"11": "Demo A"}, "seed_familiar": {"12": "Demo B"}},
               "reported_subscriptions": {"Example Streamer": ["Example Streamer"]}}, f)
check("config values load", load(f.name) == [["Comedy"], [11, 12], ["Example Streamer"]])
ex = json.load(open(os.path.join(ROOT, "config", "local.example.json")))
check("example config has empty seed ratings", not ex["onboarding"]["seed_nope"] and not ex["onboarding"]["seed_familiar"])
check("example Unsubscribed: top 10, YouTube TV excluded", ex["unsubscribed"]["top_n_per_service"] == 10 and "YouTube TV" in ex["unsubscribed"]["excluded_services"])
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
