"""SQLite persistence (one database file per user code; see app.py)."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .models import UserProfile, WorkoutPlan
from .progression import SetLog

SCHEMA = """
CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    profile_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    day_index INTEGER NOT NULL,
    performed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS set_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES sessions(id),
    exercise_id TEXT NOT NULL,
    set_number INTEGER NOT NULL,
    weight REAL NOT NULL,          -- always stored in kg
    reps INTEGER NOT NULL,
    rpe REAL                       -- optional, 1-10
);
CREATE INDEX IF NOT EXISTS idx_set_logs_ex ON set_logs(exercise_id);
CREATE TABLE IF NOT EXISTS body_weights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    logged_at TEXT NOT NULL,
    weight_kg REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS form_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    exercise_id TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    score REAL NOT NULL,
    reps INTEGER NOT NULL,
    issues_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS plan_edits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id INTEGER NOT NULL REFERENCES plans(id),
    edited_at TEXT NOT NULL,
    request TEXT NOT NULL,
    summary TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: str = "data/coach.db"):
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Databases created by v1 have no `rpe` column."""
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(set_logs)")}
        if "rpe" not in cols:
            with self.conn:
                self.conn.execute("ALTER TABLE set_logs ADD COLUMN rpe REAL")

    # ------------------------------------------------------------------ plans
    def save_plan(self, profile: UserProfile, plan: WorkoutPlan) -> int:
        with self.conn:
            self.conn.execute("UPDATE plans SET active = 0")
            cur = self.conn.execute(
                "INSERT INTO plans (created_at, profile_json, plan_json, active) VALUES (?, ?, ?, 1)",
                (_now(), profile.model_dump_json(), plan.model_dump_json()),
            )
        return cur.lastrowid

    def update_plan(self, plan_id: int, plan: WorkoutPlan, request: str = "", summary: str = "") -> None:
        with self.conn:
            self.conn.execute("UPDATE plans SET plan_json = ? WHERE id = ?", (plan.model_dump_json(), plan_id))
            if request or summary:
                self.conn.execute(
                    "INSERT INTO plan_edits (plan_id, edited_at, request, summary) VALUES (?, ?, ?, ?)",
                    (plan_id, _now(), request, summary),
                )

    def plan_edits(self, plan_id: int, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT edited_at, request, summary FROM plan_edits WHERE plan_id = ? ORDER BY id DESC LIMIT ?",
            (plan_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def active_plan(self) -> tuple[int, UserProfile, WorkoutPlan] | None:
        row = self.conn.execute("SELECT * FROM plans WHERE active = 1 ORDER BY id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        return (
            row["id"],
            UserProfile.model_validate_json(row["profile_json"]),
            WorkoutPlan.model_validate_json(row["plan_json"]),
        )

    # --------------------------------------------------------------- sessions
    def session_count(self, plan_id: int) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM sessions WHERE plan_id = ?", (plan_id,)).fetchone()[0]

    def log_session(self, plan_id: int, day_index: int, entries: list[dict]) -> int:
        """entries: [{exercise_id, set_number, weight (kg), reps, rpe (optional)}, ...]"""
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO sessions (plan_id, day_index, performed_at) VALUES (?, ?, ?)",
                (plan_id, day_index, _now()),
            )
            sid = cur.lastrowid
            self.conn.executemany(
                "INSERT INTO set_logs (session_id, exercise_id, set_number, weight, reps, rpe) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (sid, e["exercise_id"], e["set_number"], float(e["weight"]), int(e["reps"]),
                     None if e.get("rpe") is None else float(e["rpe"]))
                    for e in entries
                ],
            )
        return sid

    def _sets_of(self, session_id: int, exercise_id: str) -> list[SetLog]:
        rows = self.conn.execute(
            "SELECT weight, reps, rpe FROM set_logs WHERE session_id = ? AND exercise_id = ? ORDER BY set_number",
            (session_id, exercise_id),
        ).fetchall()
        return [SetLog(r["weight"], r["reps"], r["rpe"]) for r in rows]

    def exercise_history(self, exercise_id: str, limit: int = 5) -> list[list[SetLog]]:
        """Previous sessions for one exercise, most recent first."""
        sessions = self.conn.execute(
            """SELECT DISTINCT s.id FROM sessions s JOIN set_logs l ON l.session_id = s.id
               WHERE l.exercise_id = ? ORDER BY s.id DESC LIMIT ?""",
            (exercise_id, limit),
        ).fetchall()
        return [self._sets_of(s["id"], exercise_id) for s in sessions]

    def exercise_sessions(self, exercise_id: str, days: int = 14, limit: int = 10) -> list[tuple[datetime, list[SetLog]]]:
        """Sessions in the last `days` days, most recent first, with their timestamps."""
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        rows = self.conn.execute(
            """SELECT DISTINCT s.id, s.performed_at FROM sessions s JOIN set_logs l ON l.session_id = s.id
               WHERE l.exercise_id = ? AND s.performed_at >= ? ORDER BY s.id DESC LIMIT ?""",
            (exercise_id, since, limit),
        ).fetchall()
        return [(datetime.fromisoformat(r["performed_at"]), self._sets_of(r["id"], exercise_id)) for r in rows]

    def all_sets(self) -> list[dict]:
        rows = self.conn.execute(
            """SELECT s.id AS session_id, s.performed_at, s.day_index, l.exercise_id,
                      l.set_number, l.weight, l.reps, l.rpe
               FROM set_logs l JOIN sessions s ON s.id = l.session_id ORDER BY s.id, l.set_number"""
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------- body weight
    def add_body_weight(self, weight_kg: float) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO body_weights (logged_at, weight_kg) VALUES (?, ?)", (_now(), float(weight_kg)))

    def body_weights(self) -> list[dict]:
        rows = self.conn.execute("SELECT logged_at, weight_kg FROM body_weights ORDER BY id").fetchall()
        return [dict(r) for r in rows]

    # ---------------------------------------------------------------- settings
    def get_setting(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    # -------------------------------------------------------------- form checks
    def add_form_check(self, exercise_id: str, score: float, reps: int, issues: list[dict]) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT INTO form_checks (exercise_id, checked_at, score, reps, issues_json) VALUES (?, ?, ?, ?, ?)",
                (exercise_id, _now(), float(score), int(reps), json.dumps(issues)),
            )

    def latest_form_score(self, exercise_id: str, days: int = 21) -> float | None:
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")
        row = self.conn.execute(
            "SELECT score FROM form_checks WHERE exercise_id = ? AND checked_at >= ? ORDER BY id DESC LIMIT 1",
            (exercise_id, since),
        ).fetchone()
        return row["score"] if row else None
