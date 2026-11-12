#!/usr/bin/env python3
"""On-demand raw Movie Night vote intake (agent host only). No network, no Mac writes, no schedules.
Reads a COPIED snapshot of votes.jsonl; full re-scan + dedupe on event_id.
Never writes viewing_events, recommendations or preferences; no vote->taste mapping.
Usage: intake.py import SNAPSHOT [--db PATH] [--source-path P] [--machine M] [--test-db]
       intake.py report [--db PATH]"""
import argparse, hashlib, json, sqlite3, sys, uuid, datetime
REAL_DB = "./feedback-intake/raw_votes.db"
TEST_DB = "./feedback-intake/raw_votes_test.db"
REQ = ("event_id", "title", "media_type", "vote", "origin")
SCHEMA = """
CREATE TABLE IF NOT EXISTS raw_votes(event_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,
 raw_json TEXT NOT NULL, title TEXT, tmdb_id INTEGER, media_type TEXT, vote TEXT CHECK(vote IN ('up','down')),
 event_timestamp TEXT, origin TEXT, idempotency_key TEXT, supersedes TEXT,
 first_receipt_id TEXT NOT NULL, ingested_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS conflicts(id INTEGER PRIMARY KEY, receipt_id TEXT, event_id TEXT,
 existing_sha256 TEXT, incoming_sha256 TEXT, incoming_raw TEXT, line_no INTEGER, seen_at TEXT);
CREATE TABLE IF NOT EXISTS rejects(id INTEGER PRIMARY KEY, receipt_id TEXT, line_no INTEGER,
 reason TEXT, raw_line TEXT, seen_at TEXT);
CREATE TABLE IF NOT EXISTS excluded_test(receipt_id TEXT, line_no INTEGER, event_id TEXT, raw_line TEXT,
 PRIMARY KEY(receipt_id,line_no));
CREATE TABLE IF NOT EXISTS receipts(receipt_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
 snapshot_path TEXT, source_path TEXT, source_machine TEXT, snapshot_bytes INTEGER, snapshot_sha256 TEXT,
 complete_bytes INTEGER, partial_tail_bytes INTEGER, lines INTEGER, new INTEGER, duplicate INTEGER,
 test_excluded INTEGER, conflict INTEGER, rejected INTEGER);
"""
def canon(o): return json.dumps(o, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
def now(): return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
def is_test(o): return o.get("test") is True or str(o.get("event_id","")).startswith("test") or str(o.get("idempotency_key","")).startswith("test:")
def do_import(a):
    db = a.db or (TEST_DB if a.test_db else REAL_DB)
    data = open(a.snapshot, "rb").read()
    cut = data.rfind(b"\n") + 1  # bytes after last newline = possibly partial line; recorded, not parsed
    if cut == 0 and data and data.strip():
        try: json.loads(data); cut = len(data)  # single complete line without newline
        except Exception: pass
    body, tail = data[:cut], data[cut:]
    c = sqlite3.connect(db); c.executescript(SCHEMA)
    rid = str(uuid.uuid4()); n = dict(lines=0,new=0,duplicate=0,test_excluded=0,conflict=0,rejected=0)
    with c:  # single transaction: data + receipt commit together
        for i, line in enumerate(body.decode("utf-8", "replace").splitlines(), 1):
            if not line.strip(): continue
            n["lines"] += 1
            try: o = json.loads(line); assert isinstance(o, dict)
            except Exception:
                n["rejected"] += 1; c.execute("INSERT INTO rejects VALUES(NULL,?,?,?,?,?)",(rid,i,"malformed_json",line,now())); continue
            if is_test(o):
                n["test_excluded"] += 1; c.execute("INSERT INTO excluded_test VALUES(?,?,?,?)",(rid,i,o.get("event_id"),line)); continue
            miss = [k for k in REQ if not o.get(k)] + ([] if o.get("timestamp") or o.get("ts_utc") else ["timestamp"])
            bad = miss or o.get("vote") not in ("up","down") or not (o.get("tmdb_id") is None or isinstance(o.get("tmdb_id"), int))
            if bad:
                n["rejected"] += 1; c.execute("INSERT INTO rejects VALUES(NULL,?,?,?,?,?)",(rid,i,"schema:"+",".join(miss or ["vote/tmdb_id"]),line,now())); continue
            h = hashlib.sha256(canon(o).encode()).hexdigest()
            r = c.execute("SELECT payload_sha256 FROM raw_votes WHERE event_id=?",(o["event_id"],)).fetchone()
            if r is None:
                c.execute("INSERT INTO raw_votes VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",(o["event_id"],h,line,o["title"],o.get("tmdb_id"),o["media_type"],o["vote"],o.get("timestamp") or o.get("ts_utc"),o["origin"],o.get("idempotency_key"),o.get("supersedes"),rid,now())); n["new"] += 1
            elif r[0] == h: n["duplicate"] += 1
            else:
                n["conflict"] += 1; c.execute("INSERT INTO conflicts VALUES(NULL,?,?,?,?,?,?,?)",(rid,o["event_id"],r[0],h,line,i,now()))
        c.execute("INSERT INTO receipts VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(rid,now(),now(),a.snapshot,a.source_path,a.machine,len(data),hashlib.sha256(data).hexdigest(),cut,len(tail),n["lines"],n["new"],n["duplicate"],n["test_excluded"],n["conflict"],n["rejected"]))
    print(json.dumps(dict(db=db, receipt_id=rid, partial_tail_bytes=len(tail), **n)))
def report(a):
    c = sqlite3.connect(a.db or REAL_DB); c.executescript(SCHEMA)
    for t in ("raw_votes","conflicts","rejects","excluded_test","receipts"): print(t, c.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
p = argparse.ArgumentParser(); s = p.add_subparsers(dest="cmd", required=True)
i = s.add_parser("import"); i.add_argument("snapshot"); i.add_argument("--db"); i.add_argument("--test-db", action="store_true")
i.add_argument("--source-path", default=None); i.add_argument("--machine", default=None); i.set_defaults(f=do_import)
r = s.add_parser("report"); r.add_argument("--db"); r.set_defaults(f=report)
a = p.parse_args(); a.f(a)
