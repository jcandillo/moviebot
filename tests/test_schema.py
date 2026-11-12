"""docs/schema.sql builds cleanly and stays compatible with the DDL the pipeline creates itself."""
import os, re, sqlite3, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
res = []
def check(n, c):
    res.append(bool(c)); print(("PASS " if c else "FAIL ") + n)
c = sqlite3.connect(":memory:")
c.executescript(open(os.path.join(ROOT, "docs", "schema.sql")).read())
names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
need = {"services", "connectors", "viewing_events", "watchlist_items", "titles", "title_matches", "title_availability",
        "taste_signals", "taste_latest", "feedback_history_receipts", "feedback_apply_receipts", "watch_availability",
        "service_subscriptions", "preferences", "history_confirmations", "title_metadata", "title_metadata_failures"}
check("schema defines every table/view the code and spec use", need <= names)
mig = re.search(r'MIGRATION = """(.*?)"""', open(os.path.join(ROOT, "pipeline", "feedback_apply.py")).read(), re.S).group(1)
c.executescript(mig)
check("feedback_apply MIGRATION is idempotent on top of schema.sql", True)
sch = re.search(r'SCHEMA = """(.*?)"""', open(os.path.join(ROOT, "pipeline", "where_to_watch.py")).read(), re.S).group(1)
c.execute(sch)
check("where_to_watch SCHEMA is idempotent on top of schema.sql", True)
print(f"{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
