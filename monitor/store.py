"""Persistent CSV storage: observation history, audit trail and run log.

Overwrite rules (mandatory data-quality policy):
  * A missing value never replaces a stored value.
  * A lower-priority source (manual < official) never replaces a higher-priority one
    for the same series and observation date.
  * A same-or-higher-priority source may revise a stored value; the revision is
    written to the audit log with the old and new values.
"""
from __future__ import annotations

import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

from .config import AUDIT_LOG_CSV, OBSERVATIONS_CSV, RUN_LOG_CSV, SOURCE_PRIORITY
from .models import Observation

OBS_FIELDS = ["series_id", "obs_date", "value", "source", "source_url", "source_type",
              "publication_date", "retrieved_at", "notes"]
AUDIT_FIELDS = ["run_id", "series_id", "obs_date", "action", "value", "previous_value",
                "source", "source_url", "message"]
RUN_FIELDS = ["run_id", "report_date", "started_at", "finished_at", "status",
              "inserted", "revised", "failures", "failure_detail"]


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _append(path: Path, fields: list[str], rows: list[dict]) -> None:
    new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if new:
            w.writeheader()
        w.writerows(rows)


def row_to_obs(r: dict) -> Observation:
    return Observation(
        series_id=r["series_id"], obs_date=date.fromisoformat(r["obs_date"]),
        value=float(r["value"]) if r.get("value") not in (None, "") else None,
        source=r.get("source", ""), source_url=r.get("source_url", ""),
        source_type=r.get("source_type") or "official",
        publication_date=date.fromisoformat(r["publication_date"]) if r.get("publication_date") else None,
        retrieved_at=r.get("retrieved_at", ""), notes=r.get("notes", ""))


class Store:
    def __init__(self, path: Path = OBSERVATIONS_CSV, audit_path: Path = AUDIT_LOG_CSV,
                 run_log_path: Path = RUN_LOG_CSV):
        self.path, self.audit_path, self.run_log_path = path, audit_path, run_log_path
        self.rows: dict[tuple[str, str], dict] = {}
        for r in _read(path):
            self.rows[(r["series_id"], r["obs_date"])] = r
        self.audit: list[dict] = []       # pending write to the audit log
        self.all_audit: list[dict] = []   # everything logged during this run
        self.counts = defaultdict(int)

    # -- writes -----------------------------------------------------------
    def upsert(self, ob: Observation, run_id: str) -> str:
        if ob.value is None:
            self._log(run_id, ob, "skipped_missing", "", "No value supplied; stored history untouched")
            return "skipped_missing"
        key = (ob.series_id, ob.obs_date.isoformat())
        new = ob.to_row()
        old = self.rows.get(key)
        if old is None:
            self.rows[key] = new
            self._log(run_id, ob, "inserted", "")
            return "inserted"
        if old["value"] == new["value"]:
            # keep original row (and its retrieval stamp); fill publication date if newly known
            if not old.get("publication_date") and new["publication_date"]:
                old["publication_date"] = new["publication_date"]
            self.counts["unchanged"] += 1
            return "unchanged"
        old_rank = SOURCE_PRIORITY.get(old.get("source_type") or "official", 9)
        new_rank = SOURCE_PRIORITY.get(ob.source_type, 9)
        if new_rank > old_rank:
            self._log(run_id, ob, "kept_existing", old["value"],
                      f"Lower-priority {ob.source_type} value not applied over {old.get('source_type')}")
            return "kept_existing"
        self.rows[key] = new
        self._log(run_id, ob, "revised", old["value"], f"Revised from {old.get('source')}")
        return "revised"

    def _log(self, run_id: str, ob: Observation, action: str, prev: str, msg: str = "") -> None:
        self.counts[action] += 1
        entry = {"run_id": run_id, "series_id": ob.series_id, "obs_date": ob.obs_date.isoformat(),
                           "action": action, "value": "" if ob.value is None else ob.value,
                           "previous_value": prev, "source": ob.source, "source_url": ob.source_url,
                           "message": msg}
        self.audit.append(entry)
        self.all_audit.append(entry)

    def log_failure(self, run_id: str, message: str) -> None:
        self.counts["failed"] += 1
        self.audit.append({"run_id": run_id, "series_id": "", "obs_date": "", "action": "fetch_failed",
                           "value": "", "previous_value": "", "source": "", "source_url": "",
                           "message": message})

    def save(self) -> None:
        rows = sorted(self.rows.values(), key=lambda r: (r["series_id"], r["obs_date"]))
        _write(self.path, OBS_FIELDS, rows)
        _append(self.audit_path, AUDIT_FIELDS, self.audit)
        self.audit = []

    def log_run(self, row: dict) -> None:
        _append(self.run_log_path, RUN_FIELDS, [row])

    # -- reads ------------------------------------------------------------
    def history(self, series_id: str, up_to: date | None = None, consistent: bool = True,
                fresh_days: int = 7) -> list[Observation]:
        """Observation history for one series.

        With consistent=True (the default), if official data exists within `fresh_days`
        of the latest observation, lower-priority points (manual/secondary quotes of a
        possibly different instrument) are dropped, so that movements compare like with
        like. Otherwise every point is returned and the report flags mixed sources."""
        out = [row_to_obs(r) for (sid, _), r in self.rows.items() if sid == series_id and r.get("value")]
        if up_to:
            out = [o for o in out if o.obs_date <= up_to]
        out.sort(key=lambda o: o.obs_date)
        if consistent and out:
            official = [o for o in out if o.source_type == "official"]
            if official and (out[-1].obs_date - official[-1].obs_date).days <= fresh_days:
                return official
        return out

    def discrepancies(self, since: date, threshold_bp: float = 3.0) -> list[dict]:
        """Lower-priority values that disagree with the stored (higher-priority) value."""
        out = []
        for a in self.all_audit:
            if a["action"] != "kept_existing" or not a["obs_date"] or date.fromisoformat(a["obs_date"]) < since:
                continue
            kept = self.rows.get((a["series_id"], a["obs_date"]))
            if not kept or not kept.get("value"):
                continue
            diff = (float(a["value"]) - float(kept["value"])) * 100
            if abs(diff) >= threshold_bp:
                out.append({"series_id": a["series_id"], "obs_date": a["obs_date"], "kept": float(kept["value"]),
                            "kept_source": kept["source"], "other": float(a["value"]), "other_source": a["source"],
                            "other_url": a["source_url"], "diff_bp": round(diff, 1)})
        return out


def load_manual(path: Path) -> list[Observation]:
    """Manually verified observations. Every row must carry a source URL."""
    obs = []
    for r in _read(path):
        if not r.get("value") or not r.get("source_url"):
            continue
        r = dict(r)
        r["source_type"] = r.get("source_type") or "manual"
        obs.append(row_to_obs(r))
    return obs
