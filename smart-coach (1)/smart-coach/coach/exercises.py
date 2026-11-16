"""Curated exercise library.

The LLM is only allowed to pick exercises from this list (by id), which is what
prevents it from inventing exercises. Extend `_RAW` freely (or load a bigger
dataset such as free-exercise-db) as long as ids stay unique.
"""
from __future__ import annotations

from dataclasses import dataclass

MUSCLES = [
    "chest", "back", "shoulders", "biceps", "triceps",
    "quads", "hamstrings", "glutes", "calves", "core",
]
LOWER_BODY = {"quads", "hamstrings", "glutes", "calves"}

LEVEL_RANK = {"beginner": 1, "intermediate": 2, "advanced": 3}

EQUIPMENT_PROFILES = {
    "bodyweight": {"bodyweight"},
    "dumbbells": {"bodyweight", "dumbbell"},
    "full_gym": {"bodyweight", "dumbbell", "barbell", "machine", "cable"},
}


@dataclass(frozen=True)
class Exercise:
    id: str
    name: str
    muscle: str
    equipment: str  # bodyweight | dumbbell | barbell | machine | cable
    level: int      # 1 beginner, 2 intermediate, 3 advanced
    kind: str       # compound | isolation


# id, name, muscle, equipment, level, kind
_RAW = [
    # chest
    ("push_up", "Push-Up", "chest", "bodyweight", 1, "compound"),
    ("incline_push_up", "Incline Push-Up", "chest", "bodyweight", 1, "compound"),
    ("decline_push_up", "Decline Push-Up", "chest", "bodyweight", 2, "compound"),
    ("bench_press", "Barbell Bench Press", "chest", "barbell", 2, "compound"),
    ("db_bench_press", "Dumbbell Bench Press", "chest", "dumbbell", 1, "compound"),
    ("incline_db_press", "Incline Dumbbell Press", "chest", "dumbbell", 2, "compound"),
    ("machine_chest_press", "Machine Chest Press", "chest", "machine", 1, "compound"),
    ("cable_fly", "Cable Fly", "chest", "cable", 2, "isolation"),
    ("db_fly", "Dumbbell Fly", "chest", "dumbbell", 2, "isolation"),
    # back
    ("inverted_row", "Inverted Row", "back", "bodyweight", 1, "compound"),
    ("pull_up", "Pull-Up", "back", "bodyweight", 3, "compound"),
    ("superman", "Superman Hold-Raise", "back", "bodyweight", 1, "isolation"),
    ("prone_y_raise", "Prone Y Raise", "back", "bodyweight", 1, "isolation"),
    ("reverse_snow_angel", "Reverse Snow Angel", "back", "bodyweight", 1, "isolation"),
    ("one_arm_db_row", "One-Arm Dumbbell Row", "back", "dumbbell", 1, "compound"),
    ("bent_over_row", "Barbell Bent-Over Row", "back", "barbell", 2, "compound"),
    ("deadlift", "Conventional Deadlift", "back", "barbell", 3, "compound"),
    ("lat_pulldown", "Lat Pulldown", "back", "cable", 1, "compound"),
    ("seated_cable_row", "Seated Cable Row", "back", "cable", 1, "compound"),
    ("machine_row", "Machine Row", "back", "machine", 1, "compound"),
    # shoulders
    ("pike_push_up", "Pike Push-Up", "shoulders", "bodyweight", 2, "compound"),
    ("db_shoulder_press", "Dumbbell Shoulder Press", "shoulders", "dumbbell", 1, "compound"),
    ("overhead_press", "Barbell Overhead Press", "shoulders", "barbell", 2, "compound"),
    ("machine_shoulder_press", "Machine Shoulder Press", "shoulders", "machine", 1, "compound"),
    ("lateral_raise", "Dumbbell Lateral Raise", "shoulders", "dumbbell", 1, "isolation"),
    ("cable_lateral_raise", "Cable Lateral Raise", "shoulders", "cable", 2, "isolation"),
    ("face_pull", "Face Pull", "shoulders", "cable", 1, "isolation"),
    ("rear_delt_fly", "Dumbbell Rear Delt Fly", "shoulders", "dumbbell", 2, "isolation"),
    # biceps
    ("chin_up", "Chin-Up", "biceps", "bodyweight", 3, "compound"),
    ("db_curl", "Dumbbell Curl", "biceps", "dumbbell", 1, "isolation"),
    ("hammer_curl", "Hammer Curl", "biceps", "dumbbell", 1, "isolation"),
    ("barbell_curl", "Barbell Curl", "biceps", "barbell", 1, "isolation"),
    ("cable_curl", "Cable Curl", "biceps", "cable", 1, "isolation"),
    # triceps
    ("bench_dip", "Bench Dip", "triceps", "bodyweight", 1, "compound"),
    ("diamond_push_up", "Diamond Push-Up", "triceps", "bodyweight", 2, "compound"),
    ("dips", "Parallel Bar Dips", "triceps", "bodyweight", 3, "compound"),
    ("overhead_db_extension", "Overhead Dumbbell Extension", "triceps", "dumbbell", 1, "isolation"),
    ("close_grip_bench", "Close-Grip Bench Press", "triceps", "barbell", 2, "compound"),
    ("skull_crusher", "Barbell Skull Crusher", "triceps", "barbell", 2, "isolation"),
    ("triceps_pushdown", "Cable Triceps Pushdown", "triceps", "cable", 1, "isolation"),
    # quads
    ("bodyweight_squat", "Bodyweight Squat", "quads", "bodyweight", 1, "compound"),
    ("lunge", "Walking Lunge", "quads", "bodyweight", 1, "compound"),
    ("bulgarian_split_squat", "Bulgarian Split Squat", "quads", "bodyweight", 2, "compound"),
    ("goblet_squat", "Goblet Squat", "quads", "dumbbell", 1, "compound"),
    ("db_lunge", "Dumbbell Lunge", "quads", "dumbbell", 1, "compound"),
    ("back_squat", "Barbell Back Squat", "quads", "barbell", 2, "compound"),
    ("front_squat", "Barbell Front Squat", "quads", "barbell", 3, "compound"),
    ("leg_press", "Leg Press", "quads", "machine", 1, "compound"),
    ("leg_extension", "Leg Extension", "quads", "machine", 1, "isolation"),
    # hamstrings
    ("single_leg_rdl_bw", "Single-Leg Romanian Deadlift (bodyweight)", "hamstrings", "bodyweight", 1, "compound"),
    ("hamstring_walkout", "Hamstring Walkout", "hamstrings", "bodyweight", 2, "isolation"),
    ("db_rdl", "Dumbbell Romanian Deadlift", "hamstrings", "dumbbell", 1, "compound"),
    ("romanian_deadlift", "Barbell Romanian Deadlift", "hamstrings", "barbell", 2, "compound"),
    ("leg_curl", "Seated Leg Curl", "hamstrings", "machine", 1, "isolation"),
    # glutes
    ("glute_bridge", "Glute Bridge", "glutes", "bodyweight", 1, "isolation"),
    ("single_leg_glute_bridge", "Single-Leg Glute Bridge", "glutes", "bodyweight", 2, "isolation"),
    ("step_up", "Step-Up", "glutes", "bodyweight", 1, "compound"),
    ("db_hip_thrust", "Dumbbell Hip Thrust", "glutes", "dumbbell", 1, "compound"),
    ("hip_thrust", "Barbell Hip Thrust", "glutes", "barbell", 2, "compound"),
    ("cable_kickback", "Cable Glute Kickback", "glutes", "cable", 1, "isolation"),
    # calves
    ("bw_calf_raise", "Bodyweight Calf Raise", "calves", "bodyweight", 1, "isolation"),
    ("db_calf_raise", "Dumbbell Calf Raise", "calves", "dumbbell", 1, "isolation"),
    ("machine_calf_raise", "Machine Calf Raise", "calves", "machine", 1, "isolation"),
    # core (all rep-based on purpose, so rep ranges make sense)
    ("crunch", "Crunch", "core", "bodyweight", 1, "isolation"),
    ("dead_bug", "Dead Bug", "core", "bodyweight", 1, "isolation"),
    ("leg_raise", "Lying Leg Raise", "core", "bodyweight", 1, "isolation"),
    ("russian_twist", "Russian Twist", "core", "bodyweight", 1, "isolation"),
    ("hanging_knee_raise", "Hanging Knee Raise", "core", "bodyweight", 2, "isolation"),
    ("cable_crunch", "Cable Crunch", "core", "cable", 1, "isolation"),
]

_BY_ID = {row[0]: Exercise(*row) for row in _RAW}
assert len(_BY_ID) == len(_RAW), "duplicate exercise id"


def get_exercise(exercise_id: str) -> Exercise | None:
    return _BY_ID.get(exercise_id)


def all_exercises() -> list[Exercise]:
    return list(_BY_ID.values())


def available_exercises(equipment_profile: str, level: str) -> list[Exercise]:
    """Exercises usable with this equipment and not above the user's level."""
    allowed_eq = EQUIPMENT_PROFILES[equipment_profile]
    max_level = LEVEL_RANK[level]
    return [e for e in _BY_ID.values() if e.equipment in allowed_eq and e.level <= max_level]
