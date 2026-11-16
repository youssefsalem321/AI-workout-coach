"""Progressive overload: the numbers come from rules, the LLM only phrases them.

Double progression: stay at a weight until every set reaches the top of the
rep range, then add weight and drop back to the bottom of the range. Two failed
sessions in a row at the same weight -> small deload.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .exercises import LOWER_BODY, Exercise
from .models import PlannedExercise

# (equipment, is_lower_body) -> kg increment
INCREMENTS = {
    ("barbell", False): 2.5, ("barbell", True): 5.0,
    ("dumbbell", False): 2.0, ("dumbbell", True): 2.0,
    ("machine", False): 2.5, ("machine", True): 5.0,
    ("cable", False): 2.5, ("cable", True): 2.5,
}


FORM_MIN = 70.0  # below this form score we do not add weight


@dataclass
class SetLog:
    weight: float
    reps: int
    rpe: float | None = None   # 1-10, optional


@dataclass
class Recommendation:
    exercise_id: str
    action: str                 # start | increase | hold | decrease | deload
    next_weight: float | None   # None for bodyweight or first time
    target_reps: int
    reason: str                                   # English text (kg)
    code: str = ""                                # key into REASONS_EN / i18n "rec.<code>"
    params: dict = field(default_factory=dict)    # values for the template (weights in kg)



REASONS_EN = {
    "first_time": "First time: pick a weight you can lift for the target reps with 1-2 reps left in the tank.",
    "form_gate": "You earned a progression, but your last form check scored {form_score:.0f}/100: clean up technique at {weight:g} {unit} before adding weight.",
    "rpe_gate": "You hit the top of the range, but it felt maximal (RPE {rpe:.1f}): repeat this weight once more before adding load.",
    "bw_increase": "You hit the top of the range on every set: make it harder (slower tempo, pause reps, a harder variation or added weight).",
    "increase": "All sets hit {rep_max} reps at {weight:g} {unit}: add {inc:g} {unit} and restart at {rep_min} reps.",
    "increase_easy": "All sets hit {rep_max} reps at {weight:g} {unit} and it felt easy (RPE {rpe:.1f}): take a bigger step, add {inc:g} {unit}, and restart at {rep_min} reps.",
    "struggle_deload": "Below {rep_min} reps two sessions in a row: deload to {new_w:g} {unit} and rebuild.",
    "struggle_hold": "Some sets fell below {rep_min} reps: keep {weight:g} {unit} and aim for clean reps.",
    "hold_add_rep": "Keep {weight:g} {unit} and try for {target} reps on every set.",
    "hold_add_rep_bw": "Aim for {target} reps on every set.",
    "deload_bw": "Deload week: easy reps, stop well before failure.",
    "deload_weight": "Deload week: use about {new_w:g} {unit} (-10%) for fewer sets and keep it smooth.",
}


def _make(ex_id: str, action: str, next_weight: float | None, target_reps: int, code: str, **params) -> Recommendation:
    return Recommendation(ex_id, action, next_weight, target_reps,
                          REASONS_EN[code].format(unit="kg", **params), code, params)


def _round_half(x: float) -> float:
    return round(x * 2) / 2


def _working_weight(session: list[SetLog]) -> float:
    return max(s.weight for s in session)


def deload_sets(sets: int) -> int:
    """Deload week: about 60% of the usual volume (never below 2 sets)."""
    return max(2, round(sets * 0.6))


def _avg_rpe(session: list[SetLog]) -> float | None:
    vals = [s.rpe for s in session if s.rpe is not None]
    return sum(vals) / len(vals) if vals else None


def recommend(history: list[list[SetLog]], planned: PlannedExercise, ex: Exercise,
              form_score: float | None = None, deload: bool = False) -> Recommendation:
    """`history` = previous sessions of this exercise, most recent first."""
    history = [h for h in history if h]
    if not history:
        return _make(ex.id, "start", None, planned.rep_min, "first_time")

    last = history[0]
    weight = _working_weight(last)
    reps = [s.reps for s in last]
    completed_all_sets = len(last) >= planned.sets
    bodyweight = ex.equipment == "bodyweight"
    avg_rpe = _avg_rpe(last)
    keep = None if bodyweight else weight

    # 0) deload week: lighter weight, fewer sets
    if deload:
        if bodyweight:
            return _make(ex.id, "deload", None, planned.rep_min, "deload_bw")
        new_w = _round_half(weight * 0.9)
        return _make(ex.id, "deload", new_w, planned.rep_min, "deload_weight", new_w=new_w)

    # 1) every set at the top of the range -> progress (unless form / effort say no)
    if completed_all_sets and min(reps) >= planned.rep_max:
        if form_score is not None and form_score < FORM_MIN:
            return _make(ex.id, "hold", keep, planned.rep_max, "form_gate", form_score=form_score, weight=weight)
        if avg_rpe is not None and avg_rpe >= 9.5:
            return _make(ex.id, "hold", keep, planned.rep_max, "rpe_gate", rpe=avg_rpe)
        if bodyweight:
            return _make(ex.id, "increase", None, planned.rep_min, "bw_increase")
        inc = INCREMENTS.get((ex.equipment, ex.muscle in LOWER_BODY), 2.5)
        easy = avg_rpe is not None and avg_rpe <= 7
        if easy:
            inc *= 2
        return _make(ex.id, "increase", _round_half(weight + inc), planned.rep_min,
                     "increase_easy" if easy else "increase",
                     rep_max=planned.rep_max, weight=weight, inc=inc, rep_min=planned.rep_min,
                     **({"rpe": avg_rpe} if easy else {}))

    # 2) struggling -> hold, or deload after two failed sessions in a row
    if min(reps) < planned.rep_min:
        previous_failed = False
        if len(history) > 1:
            prev = history[1]
            previous_failed = _working_weight(prev) == weight and min(s.reps for s in prev) < planned.rep_min
        if previous_failed and not bodyweight:
            new_w = _round_half(weight * 0.9)
            return _make(ex.id, "decrease", new_w, planned.rep_max, "struggle_deload", rep_min=planned.rep_min, new_w=new_w)
        return _make(ex.id, "hold", keep, planned.rep_min, "struggle_hold", rep_min=planned.rep_min, weight=weight)

    # 3) inside the range -> hold the weight, add a rep
    target = min(planned.rep_max, min(reps) + 1)
    if bodyweight:
        return _make(ex.id, "hold", None, target, "hold_add_rep_bw", target=target)
    return _make(ex.id, "hold", weight, target, "hold_add_rep", weight=weight, target=target)


def template_summary(recs: list[Recommendation], names: dict[str, str]) -> str:
    """Plain-text summary used when no LLM is available."""
    inc = [names[r.exercise_id] for r in recs if r.action == "increase"]
    dec = [names[r.exercise_id] for r in recs if r.action == "decrease"]
    parts = ["Session saved."]
    if inc:
        parts.append("Progressing next time: " + ", ".join(inc) + ".")
    if dec:
        parts.append("Deloading: " + ", ".join(dec) + " (it is normal, you will come back stronger).")
    if not inc and not dec:
        parts.append("Stay consistent: add a rep or two before adding weight.")
    return " ".join(parts)


def llm_summary(llm, recs: list[Recommendation], names: dict[str, str], lang: str = "en") -> str:
    """Short coach-style message. The LLM must not change any number."""
    facts = "\n".join(
        f"- {names[r.exercise_id]}: {r.action}, next weight={r.next_weight}, target reps={r.target_reps}. {r.reason}"
        for r in recs
    )
    messages = [
        {"role": "system", "content": "You are a supportive strength coach. In 3-4 short sentences, summarise the "
         "session and what to do next time. Use ONLY the facts given; never invent or change numbers, and do not "
         "give medical advice." + (" Reply in Arabic." if lang == "ar" else "")},
        {"role": "user", "content": facts},
    ]
    try:
        return llm.chat_text(messages)
    except Exception:
        return template_summary(recs, names)
