"""Persistent SQLite history: runs, agent coverage, raw listings, stable
property IDs, per-run snapshots and detected changes."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id INTEGER PRIMARY KEY AUTOINCREMENT, started_at TEXT, finished_at TEXT,
  workbook TEXT, dated_workbook TEXT, read_brochures INTEGER, notes TEXT);
CREATE TABLE IF NOT EXISTS agent_runs (
  run_id INTEGER, agent TEXT, website TEXT, status TEXT, method TEXT, search_urls TEXT,
  scanned INTEGER, candidates INTEGER, included INTEGER, excluded INTEGER, errors TEXT,
  brochures_read INTEGER, brochure_errors INTEGER, duration_s REAL, message TEXT);
CREATE TABLE IF NOT EXISTS listings (
  run_id INTEGER, agent TEXT, url TEXT, property_id TEXT, included INTEGER,
  excluded_reason TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS listing_map (url TEXT PRIMARY KEY, property_id TEXT);
CREATE TABLE IF NOT EXISTS properties (
  property_id TEXT PRIMARY KEY, first_seen_run INTEGER, first_seen TEXT, last_seen_run INTEGER,
  last_seen TEXT, active INTEGER, removed_on TEXT, fingerprint TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS property_snapshots (
  run_id INTEGER, property_id TEXT, fingerprint TEXT, data TEXT);
CREATE TABLE IF NOT EXISTS changes (
  run_id INTEGER, property_id TEXT, change_type TEXT, details TEXT, property_name TEXT);
CREATE TABLE IF NOT EXISTS duplicate_reviews (
  run_id INTEGER, property_id_a TEXT, url_a TEXT, property_id_b TEXT, url_b TEXT,
  decision TEXT, score REAL, reason TEXT);
CREATE INDEX IF NOT EXISTS ix_snap ON property_snapshots(run_id, property_id);
CREATE INDEX IF NOT EXISTS ix_list ON listings(run_id);
"""

TRACKED = {
    "max_sqft": "Max available (sq ft)", "min_sqft": "Min divisible (sq ft)",
    "availability_status": "Availability status", "marketing_status": "Marketing status",
    "availability_date": "Availability date", "rent_psf": "Rent £psf", "rent_text": "Quoted rent",
    "price_text": "Price", "agents": "Marketing agents", "eaves_m": "Eaves (m)", "epc": "EPC",
    "tenure": "Tenure",
}


def fingerprint(rec: dict) -> str:
    key = {k: (sorted(rec.get(k) or []) if k == "agents" else rec.get(k)) for k in TRACKED}
    return hashlib.sha1(json.dumps(key, sort_keys=True, default=str).encode()).hexdigest()


class HistoryDB:
    def __init__(self, path):
        self.conn = sqlite3.connect(str(path))
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def start_run(self, read_brochures: bool) -> int:
        cur = self.conn.execute("INSERT INTO runs(started_at, read_brochures) VALUES (?,?)",
                                (datetime.now().isoformat(timespec="seconds"), int(read_brochures)))
        self.conn.commit()
        return cur.lastrowid

    def previous_run_id(self, run_id: int) -> int | None:
        row = self.conn.execute("SELECT MAX(run_id) FROM runs WHERE run_id < ? AND finished_at IS NOT NULL",
                                (run_id,)).fetchone()
        return row[0] if row and row[0] else None

    def finish_run(self, run_id: int, workbook: str, dated: str, notes: str = ""):
        self.conn.execute("UPDATE runs SET finished_at=?, workbook=?, dated_workbook=?, notes=? WHERE run_id=?",
                          (datetime.now().isoformat(timespec="seconds"), workbook, dated, notes, run_id))
        self.conn.commit()

    def save_agent_result(self, run_id: int, r):
        self.conn.execute(
            "INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (run_id, r.agent, r.website, r.status, r.method, json.dumps(r.search_urls), r.listings_scanned,
             r.candidates, len(r.included), len(r.excluded), json.dumps(r.errors[:50]), r.brochures_read,
             r.brochure_errors, r.duration_s, r.message))
        for l in r.included + r.excluded:
            self.conn.execute("INSERT INTO listings VALUES (?,?,?,?,?,?,?)",
                              (run_id, l.agent, l.url, None, int(not l.excluded_reason), l.excluded_reason,
                               json.dumps(l.to_dict(), default=str)))
        self.conn.commit()

    # ----------------------------------------------------------- IDs
    def assign_ids(self, records: list[dict]) -> None:
        """Give every master record a stable property_id, reusing IDs from
        earlier runs when any of its listing URLs was seen before."""
        used: set[str] = set()
        row = self.conn.execute("SELECT property_id FROM properties ORDER BY property_id DESC LIMIT 1").fetchone()
        seq = int(row[0].split("-")[1]) if row else 0
        # deterministic order: records with the most URLs claim previous IDs first
        for rec in sorted(records, key=lambda r: (-len(r["listing_urls"]), r["listing_urls"][0])):
            prev = []
            for u in rec["listing_urls"]:
                r0 = self.conn.execute("SELECT property_id FROM listing_map WHERE url=?", (u,)).fetchone()
                if r0 and r0[0] not in prev:
                    prev.append(r0[0])
            pid = next((p for p in sorted(prev) if p not in used), None)
            if pid is None:
                seq += 1
                pid = f"NW-{seq:05d}"
            if len(prev) > 1:
                rec.setdefault("notes", []).append("Previously recorded as separate properties: " + ", ".join(prev))
            used.add(pid)
            rec["property_id"] = pid
            for u in rec["listing_urls"]:
                self.conn.execute("INSERT OR REPLACE INTO listing_map VALUES (?,?)", (u, pid))
                self.conn.execute("UPDATE listings SET property_id=? WHERE url=? AND property_id IS NULL", (pid, u))
        self.conn.commit()

    # ----------------------------------------------------------- changes
    def record(self, run_id: int, records: list[dict], failed_agents: set[str]) -> list[dict]:
        """Store snapshots, update the property register and return change rows."""
        now = datetime.now().date().isoformat()
        prev_run = self.previous_run_id(run_id)
        prev: dict[str, dict] = {}
        if prev_run:
            for r in self.conn.execute("SELECT property_id, data FROM property_snapshots WHERE run_id=?", (prev_run,)):
                prev[r["property_id"]] = json.loads(r["data"])
        changes = []
        current_ids = set()
        for rec in records:
            pid = rec["property_id"]
            current_ids.add(pid)
            fp = fingerprint(rec)
            rec["fingerprint"] = fp
            self.conn.execute("INSERT INTO property_snapshots VALUES (?,?,?,?)",
                              (run_id, pid, fp, json.dumps(rec, default=str)))
            existing = self.conn.execute("SELECT * FROM properties WHERE property_id=?", (pid,)).fetchone()
            if existing is None:
                self.conn.execute("INSERT INTO properties VALUES (?,?,?,?,?,?,?,?,?)",
                                  (pid, run_id, now, run_id, now, 1, None, fp, json.dumps(rec, default=str)))
                rec["first_seen"] = now
            else:
                rec["first_seen"] = existing["first_seen"]
                self.conn.execute("UPDATE properties SET last_seen_run=?, last_seen=?, active=1, removed_on=NULL, "
                                  "fingerprint=?, data=? WHERE property_id=?",
                                  (run_id, now, fp, json.dumps(rec, default=str), pid))
            if prev_run is None:
                rec["change_flag"] = "Baseline (first run)"
                continue
            old = prev.get(pid)
            if old is None:
                was = existing is not None
                rec["change_flag"] = "Re-listed" if was else "New"
                changes.append({"change_type": rec["change_flag"], "property_id": pid,
                                "details": "Returned to advertising" if was else "New advertisement since previous search"})
            elif old.get("fingerprint") != fp:
                diffs = []
                for k, label in TRACKED.items():
                    a, b = old.get(k), rec.get(k)
                    if k == "agents":
                        a, b = sorted(a or []), sorted(b or [])
                    if (a or None) != (b or None):
                        diffs.append(f"{label}: {a if a not in (None, '', []) else '—'} → {b if b not in (None, '', []) else '—'}")
                rec["change_flag"] = "Changed"
                changes.append({"change_type": "Changed", "property_id": pid, "details": "; ".join(diffs) or "minor change"})
            else:
                rec["change_flag"] = "Unchanged"
        # removals (or merges into another property record)
        url_to_pid = {u: r["property_id"] for r in records for u in r.get("listing_urls", [])}
        for pid, old in prev.items():
            if pid in current_ids:
                continue
            merged_into = sorted({url_to_pid[u] for u in old.get("listing_urls", []) if u in url_to_pid})
            if merged_into:
                self.conn.execute("UPDATE properties SET active=0, removed_on=? WHERE property_id=?", (now, pid))
                changes.append({"change_type": "Merged", "property_id": pid,
                                "details": "Still advertised – now combined with " + ", ".join(merged_into)
                                           + " (identified as the same property across agents)", "record": old})
                continue
            agents = set(old.get("agents") or [])
            if agents and agents <= failed_agents:
                old_rec = dict(old)
                old_rec["change_flag"] = "Not re-checked (agent website unavailable)"
                changes.append({"change_type": "Not re-checked", "property_id": pid,
                                "details": "Marketing agent(s) could not be searched this run: " + ", ".join(sorted(agents)),
                                "record": old_rec})
                continue
            self.conn.execute("UPDATE properties SET active=0, removed_on=? WHERE property_id=?", (now, pid))
            changes.append({"change_type": "Removed", "property_id": pid,
                            "details": "No longer advertised by " + ", ".join(sorted(agents)) + " (let, sold, withdrawn or delisted)",
                            "record": old})
        names = {r["property_id"]: r.get("property_name") or r.get("title") for r in records}
        for c in changes:
            nm = names.get(c["property_id"]) or (c.get("record") or {}).get("property_name", "")
            c["property_name"] = nm
            self.conn.execute("INSERT INTO changes VALUES (?,?,?,?,?)",
                              (run_id, c["property_id"], c["change_type"], c["details"], nm))
        self.conn.commit()
        return changes

    def save_pairs(self, run_id: int, rows: list[dict]):
        for r in rows:
            self.conn.execute("INSERT INTO duplicate_reviews VALUES (?,?,?,?,?,?,?,?)",
                              (run_id, r["property_id_a"], r["url_a"], r["property_id_b"], r["url_b"],
                               r["decision"], r["score"], r["reason"]))
        self.conn.commit()

    def history_summary(self) -> list[dict]:
        rows = self.conn.execute("""
            SELECT r.run_id, r.started_at, COUNT(s.property_id) AS properties
            FROM runs r LEFT JOIN property_snapshots s ON s.run_id = r.run_id
            WHERE r.finished_at IS NOT NULL GROUP BY r.run_id ORDER BY r.run_id""").fetchall()
        return [dict(r) for r in rows]
