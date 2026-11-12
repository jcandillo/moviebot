"""Reco layer on a synthetic demo DB (stdlib only; numpy/MovieLens parts are skipped when numpy is absent)."""
import json, os, random, sqlite3, subprocess, sys, tempfile
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
T = tempfile.mkdtemp(prefix="reco-demo-"); DB = os.path.join(T, "moviebot.db"); FL = os.path.join(T, "flags.json")
os.environ.update(MOVIEBOT_DB=DB, RECO_FLAGS=FL, MOVIEBOT_RAW_DB=os.path.join(T, "raw.db"), MOVIEBOT_SESSIONS_DIR=os.path.join(T, "sessions"), MOVIEBOT_ML_DIR=os.path.join(T, "ml"))
json.dump(dict(json.load(open(os.path.join(ROOT, "config", "reco_flags.example.json"))), live_ranker="reco_v1"), open(FL, "w"))
sys.path.insert(0, os.path.join(ROOT, "reco"))
res = []
def check(n, c): res.append(bool(c)); print(("PASS " if c else "FAIL ") + n)
c = sqlite3.connect(DB); c.executescript(open(os.path.join(ROOT, "docs", "schema.sql")).read())
import common; common.ensure_schema(c)
G = [["Action", "Thriller"], ["Comedy"], ["Drama"], ["Science Fiction", "Action"], ["Comedy", "Romance"]]
rnd = random.Random(1)
for i in range(1, 301):   # synthetic catalogue: Demo Film N, fake people, fake votes
    g = G[i % 5]; y = 1975 + i % 50; va = round(5 + rnd.random() * 3.5, 1); vc = rnd.choice([20, 80, 400, 3000])
    c.execute("INSERT INTO reco_meta(tmdb_id,title,year,original_language,genres_json,directors_json,writers_json,cast_json,keywords_json,overview,vote_average,vote_count,status,fetched_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (i, f"Demo Film {i}", y, "en", json.dumps(g), json.dumps([f"Director {i % 17}"]), json.dumps([f"Writer {i % 23}"]),
              json.dumps([f"Actor {i % 31}", f"Actor {i % 13}"]), json.dumps([f"kw{i % 7}"]), "A demo overview.", va, vc, "Released", "2026-01-01"))
    c.execute("INSERT INTO reco_candidates VALUES(?,?,?,?)", (i, "tmdb_discover", "demo", "2026-01-01"))
for k, (tid, sig) in enumerate([(5, "up"), (22, "up"), (39, "up"), (8, "down")]):
    c.execute("INSERT INTO taste_signals VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (f"e{k}", tid, "movie", sig, "frame_vote", f"Demo Film {tid}", None, None, f"2026-01-0{k+1}T00:00:00", None, "x", "{}", "now", "r"))
c.commit()
import quality; q = quality.compute(c)
check("quality floor computed for every title", q["n"] == 300)
check("low-vote titles fail the floor", c.execute("SELECT COUNT(*) FROM reco_quality q JOIN reco_meta m USING(tmdb_id) WHERE m.vote_count < 40 AND passes_floor=1").fetchone()[0] == 0)
import ranker, tp_adapter as TP
S = TP.seeds(c); D = TP.downs(c); ctx = ranker.Ctx(c, S, D, {"Action"}, use_table=True)
pool = ranker.load_pool(c); check("pool respects the quality floor", 0 < len(pool) < 300)
ranked = sorted(pool, key=lambda m: -ctx.score(m)[0]); check("ranker scores every candidate", all(isinstance(ctx.score(m)[0], float) for m in pool[:20]))
import explore
pools = {f"genre:demo{i}:new": [dict(m, rating=m.get("tmdb_user_score_pct")) for m in ranked[:30]] for i in range(100)}
p, ch = explore.apply(c, pools); check("explore promotes ~10% of pools", 3 <= len(ch) <= 20)
pk = os.path.join(T, "picks-demo-readback.json")
json.dump({"revision": 1, "updated_at": "2026-01-05T00:00:00", "genres": [{"genre_id": "demo", "new": dict(slot_id="genre:demo:new", tmdb_id=ranked[0]["tmdb_id"], title=ranked[0]["title"],
           why="Demo why.", watch_availability={"status": "verified_offers"})}]}, open(pk, "w"))
r1 = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, "reco", "reco_log.py"), "log-picks", pk], capture_output=True, text=True).stdout)
r2 = json.loads(subprocess.run([sys.executable, os.path.join(ROOT, "reco", "reco_log.py"), "log-picks", pk], capture_output=True, text=True).stdout)
check("impression log writes once and is idempotent", r1["impressions_new"] == 1 and r2["impressions_new"] == 0)
out = subprocess.run([sys.executable, os.path.join(ROOT, "reco", "scorecard.py")], capture_output=True, text=True)
check("scorecard runs", out.returncode == 0 and "scorecard" in out.stdout)
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
