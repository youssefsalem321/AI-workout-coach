from coach.exercises import get_exercise
from coach.models import PlannedExercise
from coach.progression import SetLog, recommend

PE = PlannedExercise(exercise_id="bench_press", sets=3, rep_min=6, rep_max=10, rest_seconds=120)
BENCH = get_exercise("bench_press")


def sets(w, *reps):
    return [SetLog(w, r) for r in reps]


def test_first_time_is_start():
    r = recommend([], PE, BENCH)
    assert r.action == "start" and r.next_weight is None


def test_increase_when_all_sets_hit_top():
    r = recommend([sets(60, 10, 10, 10)], PE, BENCH)
    assert r.action == "increase" and r.next_weight == 62.5 and r.target_reps == 6


def test_lower_body_gets_bigger_jump():
    pe = PlannedExercise(exercise_id="back_squat", sets=3, rep_min=6, rep_max=10, rest_seconds=120)
    r = recommend([sets(100, 10, 10, 10)], pe, get_exercise("back_squat"))
    assert r.next_weight == 105


def test_hold_and_add_a_rep():
    r = recommend([sets(60, 8, 7, 7)], PE, BENCH)
    assert r.action == "hold" and r.next_weight == 60 and r.target_reps == 8


def test_missed_sets_do_not_count_as_progress():
    r = recommend([sets(60, 10, 10)], PE, BENCH)  # only 2 of 3 sets done
    assert r.action != "increase"


def test_single_failure_holds_weight():
    r = recommend([sets(60, 5, 5, 4)], PE, BENCH)
    assert r.action == "hold" and r.next_weight == 60


def test_two_failures_in_a_row_deload():
    r = recommend([sets(60, 5, 4, 4), sets(60, 5, 5, 4)], PE, BENCH)
    assert r.action == "decrease" and r.next_weight == 54


def test_bodyweight_progression_has_no_weight():
    pe = PlannedExercise(exercise_id="push_up", sets=3, rep_min=8, rep_max=12, rest_seconds=60)
    r = recommend([sets(0, 12, 12, 12)], pe, get_exercise("push_up"))
    assert r.action == "increase" and r.next_weight is None
