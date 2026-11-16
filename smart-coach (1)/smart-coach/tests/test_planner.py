import itertools

import pytest

from coach.exercises import available_exercises
from coach.models import UserProfile
from coach.planner import fallback_plan, generate_plan, validate_plan

GRID = list(itertools.product(
    ["muscle_gain", "fat_loss", "strength", "general_fitness"],
    ["beginner", "intermediate", "advanced"],
    [2, 3, 4, 5, 6],
    ["bodyweight", "dumbbells", "full_gym"],
    [30, 60, 90],
))


def prof(goal="muscle_gain", level="beginner", days=4, eq="full_gym", mins=60):
    return UserProfile(goal=goal, level=level, days_per_week=days, equipment=eq, session_minutes=mins)


@pytest.mark.parametrize("goal,level,days,eq,mins", GRID)
def test_fallback_plan_is_always_valid(goal, level, days, eq, mins):
    p = prof(goal, level, days, eq, mins)
    plan, _ = fallback_plan(p)
    assert len(plan.days) == days
    problems = validate_plan(plan, p)
    assert problems == [], problems


class FakeLLM:
    """Returns queued responses; an Exception instance is raised instead."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = 0

    def chat_json(self, messages, temperature=0.3):
        self.calls += 1
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def good_json(p):
    plan, _ = fallback_plan(p)
    return plan.model_dump()


def test_llm_valid_first_try():
    p = prof()
    llm = FakeLLM(good_json(p))
    res = generate_plan(p, llm)
    assert res.source == "llm" and res.attempts == 1 and llm.calls == 1


def test_llm_hallucinated_exercise_is_retried_then_accepted():
    p = prof()
    bad = good_json(p)
    bad["days"][0]["exercises"][0]["exercise_id"] = "quantum_curl"
    llm = FakeLLM(bad, good_json(p))
    res = generate_plan(p, llm)
    assert res.source == "llm" and res.attempts == 2
    assert validate_plan(res.plan, p) == []


def test_llm_always_bad_falls_back():
    p = prof()
    llm = FakeLLM({"nonsense": True}, {"nonsense": True}, {"nonsense": True})
    res = generate_plan(p, llm)
    assert res.source == "fallback" and validate_plan(res.plan, p) == []


def test_llm_api_error_falls_back_without_retry_storm():
    p = prof()
    llm = FakeLLM(RuntimeError("network down"))
    res = generate_plan(p, llm)
    assert res.source == "fallback" and llm.calls == 1


def test_wrong_equipment_is_rejected():
    p = prof(eq="bodyweight")
    full = good_json(prof(eq="full_gym"))
    plan = type(fallback_plan(p)[0]).model_validate(full)
    plan.days = plan.days[: p.days_per_week]
    assert any("not in the allowed list" in e for e in validate_plan(plan, p))


def test_level_filter_hides_advanced_moves():
    ids = {e.id for e in available_exercises("full_gym", "beginner")}
    assert "deadlift" not in ids and "pull_up" not in ids
