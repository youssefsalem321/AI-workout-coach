from coach.models import UserProfile
from coach.planner import fallback_plan
from coach.storage import Storage


def test_plan_and_history_roundtrip():
    s = Storage(":memory:")
    p = UserProfile(goal="strength", level="beginner", days_per_week=3, equipment="full_gym", session_minutes=60)
    plan, _ = fallback_plan(p)
    pid = s.save_plan(p, plan)
    got = s.active_plan()
    assert got[0] == pid and got[2].title == plan.title

    s.log_session(pid, 0, [{"exercise_id": "bench_press", "set_number": 1, "weight": 60, "reps": 8},
                           {"exercise_id": "bench_press", "set_number": 2, "weight": 60, "reps": 7}])
    s.log_session(pid, 1, [{"exercise_id": "bench_press", "set_number": 1, "weight": 62.5, "reps": 6}])
    hist = s.exercise_history("bench_press")
    assert len(hist) == 2 and hist[0][0].weight == 62.5   # most recent first
    assert s.session_count(pid) == 2


def test_new_plan_deactivates_old():
    s = Storage(":memory:")
    p = UserProfile(goal="strength", level="beginner", days_per_week=3, equipment="full_gym", session_minutes=60)
    plan, _ = fallback_plan(p)
    s.save_plan(p, plan)
    second = s.save_plan(p, plan)
    assert s.active_plan()[0] == second
