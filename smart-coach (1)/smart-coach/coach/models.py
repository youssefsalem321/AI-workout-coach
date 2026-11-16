"""Pydantic models: every LLM output is validated against these."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Goal = Literal["muscle_gain", "fat_loss", "strength", "general_fitness"]
Level = Literal["beginner", "intermediate", "advanced"]
EquipmentProfile = Literal["bodyweight", "dumbbells", "full_gym"]


class UserProfile(BaseModel):
    goal: Goal
    level: Level
    days_per_week: int = Field(ge=2, le=6)
    equipment: EquipmentProfile
    session_minutes: int = Field(ge=30, le=120)


class PlannedExercise(BaseModel):
    exercise_id: str
    sets: int = Field(ge=1, le=6)
    rep_min: int = Field(ge=1, le=30)
    rep_max: int = Field(ge=1, le=30)
    rest_seconds: int = Field(ge=30, le=300)

    @model_validator(mode="after")
    def _range_ok(self):
        if self.rep_max < self.rep_min:
            raise ValueError("rep_max must be >= rep_min")
        return self


class PlanDay(BaseModel):
    name: str
    exercises: list[PlannedExercise] = Field(min_length=3, max_length=9)


class WorkoutPlan(BaseModel):
    title: str
    days: list[PlanDay] = Field(min_length=1, max_length=7)
    notes: str = ""
