"""Plan generation.

Design rule: code decides the *structure* (split, slots per day, allowed
exercises); the LLM only fills in the choices; everything it returns is
validated, retried with feedback, and finally replaced by a deterministic
fallback if it still fails.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import dataclass, field

from pydantic import ValidationError

from .exercises import Exercise, available_exercises, get_exercise
from .models import PlanDay, PlannedExercise, UserProfile, WorkoutPlan

FALLBACK_NOTE = "Rule-based plan. Start light, keep 1-2 reps in reserve, and progress gradually."
MUSCLE_ANY = ["chest", "back", "shoulders", "biceps", "triceps", "quads", "hamstrings", "glutes", "calves", "core"]
BIG_MUSCLES = {"chest", "back", "quads", "hamstrings", "glutes", "shoulders"}

FULL = ["quads", "chest", "back", "hamstrings", "shoulders", "core", "glutes", "biceps", "triceps"]
UPPER = ["chest", "back", "shoulders", "back", "triceps", "biceps", "chest", "shoulders"]
LOWER = ["quads", "hamstrings", "glutes", "quads", "calves", "core", "hamstrings", "glutes"]
PUSH = ["chest", "shoulders", "chest", "triceps", "shoulders", "triceps", "chest", "triceps"]
PULL = ["back", "back", "biceps", "back", "biceps", "core", "back", "biceps"]
LEGS = ["quads", "hamstrings", "glutes", "quads", "calves", "hamstrings", "glutes", "core"]

SPLITS: dict[int, list[tuple[str, list[str]]]] = {
    2: [("Full Body A", FULL), ("Full Body B", FULL)],
    3: [("Full Body A", FULL), ("Full Body B", FULL), ("Full Body C", FULL)],
    4: [("Upper A", UPPER), ("Lower A", LOWER), ("Upper B", UPPER), ("Lower B", LOWER)],
    5: [("Push", PUSH), ("Pull", PULL), ("Legs", LEGS), ("Upper", UPPER), ("Lower", LOWER)],
    6: [("Push A", PUSH), ("Pull A", PULL), ("Legs A", LEGS),
        ("Push B", PUSH), ("Pull B", PULL), ("Legs B", LEGS)],
}


@dataclass
class PlanResult:
    plan: WorkoutPlan
    source: str                  # "llm" | "fallback"
    attempts: int = 0            # LLM attempts used
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- structure
def exercises_per_day(profile: UserProfile) -> int:
    return max(4, min(8, profile.session_minutes // 10))


def build_slots(profile: UserProfile) -> list[tuple[str, list[str]]]:
    """[(day name, [muscle slot, ...]), ...] — one slot per exercise."""
    n = exercises_per_day(profile)
    return [(name, muscles[:n]) for name, muscles in SPLITS[profile.days_per_week]]


def prescribe(goal: str, level: str, kind: str) -> tuple[int, int, int, int]:
    """(sets, rep_min, rep_max, rest_seconds) for the deterministic fallback."""
    compound = kind == "compound"
    table = {
        "strength": ((4, 3, 6, 180), (3, 8, 12, 90)),
        "muscle_gain": ((3, 6, 10, 120), (3, 10, 15, 75)),
        "fat_loss": ((3, 10, 15, 60), (3, 12, 20, 45)),
        "general_fitness": ((3, 8, 12, 90), (3, 12, 15, 60)),
    }[goal]
    sets, lo, hi, rest = table[0] if compound else table[1]
    if level == "beginner":
        sets = min(sets, 3)
        if goal == "strength" and compound:
            lo, hi = 5, 8
    return sets, lo, hi, rest


# --------------------------------------------------------------------------- validation
def validate_plan(plan: WorkoutPlan, profile: UserProfile, strict: bool = True) -> list[str]:
    """Return a list of human-readable problems (empty list == valid).

    strict=True checks the generated-plan template (slots, counts, coverage).
    strict=False only checks hard safety rules (real ids, equipment/level, no duplicates);
    it is used after the user or the edit agent customised the plan.
    """
    errors: list[str] = []
    pool = {e.id: e for e in available_exercises(profile.equipment, profile.level)}
    slots = build_slots(profile)
    n = exercises_per_day(profile)

    if strict and len(plan.days) != len(slots):
        errors.append(f"Plan must have exactly {len(slots)} days, got {len(plan.days)}.")
        return errors
    if not strict:
        slots = [(d.name, MUSCLE_ANY) for d in plan.days]

    for i, (day, (day_name, day_slots)) in enumerate(zip(plan.days, slots), start=1):
        allowed_muscles = set(day_slots)
        seen: set[str] = set()
        muscles_hit: set[str] = set()
        supply = sum(1 for e in pool.values() if e.muscle in allowed_muscles)
        lo = min(n - 1, supply)
        if strict and not (lo <= len(day.exercises) <= n + 1):
            errors.append(f"Day {i} ({day_name}) needs about {n} exercises, got {len(day.exercises)}.")
        for pe in day.exercises:
            ex = pool.get(pe.exercise_id)
            if ex is None:
                errors.append(
                    f"Day {i}: exercise_id '{pe.exercise_id}' is not in the allowed list "
                    f"for equipment={profile.equipment}, level={profile.level}."
                )
                continue
            if pe.exercise_id in seen:
                errors.append(f"Day {i}: '{pe.exercise_id}' appears twice.")
            seen.add(pe.exercise_id)
            muscles_hit.add(ex.muscle)
            if strict and ex.muscle not in allowed_muscles:
                errors.append(
                    f"Day {i} ({day_name}) should only train {sorted(allowed_muscles)}, "
                    f"but '{ex.id}' trains {ex.muscle}."
                )
        # every muscle that has at least one available exercise must be covered
        for m in (allowed_muscles if strict else ()):
            has_options = any(e.muscle == m for e in pool.values())
            if has_options and m not in muscles_hit:
                errors.append(f"Day {i} ({day_name}) is missing a {m} exercise.")
    return errors


def normalize_plan(plan: WorkoutPlan) -> WorkoutPlan:
    """Compounds first inside each day (stable), as a coach would order them."""
    days = []
    for d in plan.days:
        ordered = sorted(
            d.exercises,
            key=lambda pe: 0 if (get_exercise(pe.exercise_id) and get_exercise(pe.exercise_id).kind == "compound") else 1,
        )
        days.append(PlanDay(name=d.name, exercises=ordered))
    return WorkoutPlan(title=plan.title, days=days, notes=plan.notes)


# --------------------------------------------------------------------------- fallback
def _pick(pool: list[Exercise], muscle: str, want_kind: str, used: set[str], usage: Counter) -> Exercise | None:
    cands = [e for e in pool if e.muscle == muscle and e.id not in used]
    if not cands:
        return None
    preferred = [e for e in cands if e.kind == want_kind] or cands
    return min(preferred, key=lambda e: (usage[e.id], e.name))  # rotate, deterministic


def fallback_plan(profile: UserProfile) -> tuple[WorkoutPlan, list[str]]:
    pool = available_exercises(profile.equipment, profile.level)
    usage: Counter = Counter()
    warnings: list[str] = []
    days: list[PlanDay] = []

    for day_name, slots in build_slots(profile):
        used: set[str] = set()
        seen_muscles: set[str] = set()
        chosen: list[PlannedExercise] = []
        for muscle in slots:
            first = muscle not in seen_muscles
            # first slot of a big muscle -> compound; repeats -> isolation, except back (its isolation
            # options are weak, a second row/pulldown variation is better)
            want = "compound" if ((first and muscle in BIG_MUSCLES) or muscle == "back") else "isolation"
            ex = _pick(pool, muscle, want, used, usage)
            seen_muscles.add(muscle)
            if ex is None:
                continue
            used.add(ex.id)
            usage[ex.id] += 1
            sets, lo, hi, rest = prescribe(profile.goal, profile.level, ex.kind)
            chosen.append(PlannedExercise(exercise_id=ex.id, sets=sets, rep_min=lo, rep_max=hi, rest_seconds=rest))
        target = len(slots)
        order = list(dict.fromkeys(slots))
        while len(chosen) < target:  # slots without options (thin pools): fill from the day's other muscles
            added = False
            for muscle in order:
                ex = _pick(pool, muscle, "compound", used, usage)
                if ex and len(chosen) < target:
                    used.add(ex.id)
                    usage[ex.id] += 1
                    sets, lo, hi, rest = prescribe(profile.goal, profile.level, ex.kind)
                    chosen.append(PlannedExercise(exercise_id=ex.id, sets=sets, rep_min=lo, rep_max=hi, rest_seconds=rest))
                    added = True
            if not added:
                break
        missing = [m for m in dict.fromkeys(slots) if not any(e.muscle == m for e in pool)]
        if missing:
            warnings.append(f"{day_name}: no {', '.join(missing)} exercise available for your equipment/level.")
        days.append(PlanDay(name=day_name, exercises=chosen))

    plan = WorkoutPlan(
        title=f"{profile.days_per_week}-day {profile.goal.replace('_', ' ')} plan",
        days=days,
        notes=FALLBACK_NOTE,
    )
    return normalize_plan(plan), warnings


# --------------------------------------------------------------------------- LLM
SYSTEM_PROMPT = """You are an experienced strength & conditioning coach.
You build weekly workout plans as strict JSON.

HARD RULES
- Use ONLY exercise_id values from the provided allowed list. Never invent exercises.
- Each day has the slots given to you (one exercise per slot). An exercise's muscle must be one of the day's slot muscles, and every slot muscle should be covered.
- No exercise may appear twice in the same day. Put compound exercises before isolation ones.
- Rep ranges: strength 3-6 (compounds), muscle_gain 6-12, fat_loss 10-15, general_fitness 8-12. Isolation work can go 2-5 reps higher.
- Beginners: max 3 sets per exercise. Rest 45-90s for isolation, 90-180s for heavy compounds.

OUTPUT JSON SCHEMA (nothing else, no markdown):
{"title": str, "notes": str,
 "days": [{"name": str,
           "exercises": [{"exercise_id": str, "sets": int, "rep_min": int, "rep_max": int, "rest_seconds": int}]}]}
"""


def build_messages(profile: UserProfile, lang: str = "en") -> list[dict]:
    pool = available_exercises(profile.equipment, profile.level)
    allowed = "\n".join(f"{e.id} | {e.name} | {e.muscle} | {e.kind}" for e in pool)
    day_lines = "\n".join(
        f"Day {i}: {name} -> slots (muscles): {', '.join(slots)}"
        for i, (name, slots) in enumerate(build_slots(profile), start=1)
    )
    user = (
        f"User profile: goal={profile.goal}, level={profile.level}, "
        f"days_per_week={profile.days_per_week}, equipment={profile.equipment}, "
        f"session_minutes={profile.session_minutes}.\n\n"
        f"Days and slots:\n{day_lines}\n\n"
        f"ALLOWED EXERCISES (id | name | muscle | kind):\n{allowed}\n\n"
        "Return the plan JSON now. Use the same day names as above."
        + (" Write 'title' and 'notes' in Arabic (keep exercise_id values and day names exactly as given)." if lang == "ar" else "")
    )
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def generate_plan(profile: UserProfile, llm=None, max_attempts: int = 3, lang: str = "en") -> PlanResult:
    """LLM plan with validation + retry-with-feedback, then deterministic fallback."""
    warnings: list[str] = []
    attempts = 0

    if llm is not None:
        messages = build_messages(profile, lang)
        for attempt in range(1, max_attempts + 1):
            attempts = attempt
            raw = None
            try:
                raw = llm.chat_json(messages)
                plan = WorkoutPlan.model_validate(raw)
                problems = validate_plan(plan, profile)
            except (ValidationError, json.JSONDecodeError, ValueError) as exc:
                problems = [f"Output was not valid against the schema: {str(exc)[:400]}"]
            except Exception as exc:  # network / API / auth errors: don't hammer the API
                warnings.append(f"LLM call failed ({type(exc).__name__}); used the rule-based planner.")
                break
            if not problems:
                return PlanResult(normalize_plan(plan), "llm", attempt, warnings)
            warnings.append(f"Attempt {attempt}: {len(problems)} problem(s) found, retrying.")
            messages = messages + [
                {"role": "assistant", "content": json.dumps(raw) if raw is not None else "{}"},
                {"role": "user", "content": "Fix these problems and return the full corrected JSON:\n- "
                 + "\n- ".join(problems[:10])},
            ]
        else:
            warnings.append("LLM output never passed validation; used the rule-based planner.")

    plan, fb_warnings = fallback_plan(profile)
    return PlanResult(plan, "fallback", attempts, warnings + fb_warnings)
