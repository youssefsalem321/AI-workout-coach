"""Automatic deload detection.

Idea: a deload is suggested when performance dropped on at least two exercises
within the last two weeks (estimated 1RM down, or effort rising without
progress). Pure functions, no LLM involved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .progression import SetLog


@dataclass
class ExerciseTrend:
    exercise_id: str
    reason: str      # "e1rm_drop" | "rpe_up"
    detail: float    # % drop for e1rm_drop, RPE increase for rpe_up


@dataclass
class DeloadSuggestion:
    should_deload: bool
    trends: list[ExerciseTrend] = field(default_factory=list)
    tracked: int = 0


def session_performance(sets: list[SetLog]) -> float:
    """Epley estimated 1RM; for bodyweight work (weight 0) the best rep count."""
    done = [s for s in sets if s.reps > 0]
    if not done:
        return 0.0
    if max(s.weight for s in done) == 0:
        return float(max(s.reps for s in done))
    return max(s.weight * (1 + s.reps / 30) for s in done)


def _avg_rpe(sets: list[SetLog]) -> float | None:
    vals = [s.rpe for s in sets if s.rpe is not None]
    return sum(vals) / len(vals) if vals else None


def detect_deload(
    sessions_by_exercise: dict[str, list[tuple[datetime, list[SetLog]]]],
    now: datetime | None = None,
    window_days: int = 14,
    min_flagged: int = 2,
    drop_pct: float = 0.03,
    rpe_rise: float = 1.5,
) -> DeloadSuggestion:
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    trends: list[ExerciseTrend] = []
    tracked = 0

    for ex_id, sessions in sessions_by_exercise.items():
        recent = sorted((s for s in sessions if s[0] >= since), key=lambda s: s[0], reverse=True)
        if len(recent) < 2:
            continue
        tracked += 1
        latest_perf = session_performance(recent[0][1])
        best_prev = max(session_performance(s[1]) for s in recent[1:])
        if best_prev > 0 and latest_perf <= best_prev * (1 - drop_pct):
            trends.append(ExerciseTrend(ex_id, "e1rm_drop", round(100 * (1 - latest_perf / best_prev), 1)))
            continue
        first_rpe, last_rpe = _avg_rpe(recent[-1][1]), _avg_rpe(recent[0][1])
        if first_rpe is not None and last_rpe is not None and last_rpe - first_rpe >= rpe_rise and latest_perf <= best_prev:
            trends.append(ExerciseTrend(ex_id, "rpe_up", round(last_rpe - first_rpe, 1)))

    return DeloadSuggestion(should_deload=len(trends) >= min_flagged, trends=trends, tracked=tracked)
