"""Evaluate plan quality over a grid of user profiles.

    python -m eval.run_eval --mode fallback        # offline baseline
    python -m eval.run_eval --mode llm --limit 40  # needs GROQ_API_KEY

Metrics (all computed independently of the generator, with the same validator the app uses):
  schema_valid        plan parsed into the Pydantic models
  rule_valid          zero validation problems (real ids, equipment/level ok, no duplicates, right muscles)
  llm_first_try       (llm mode) valid on the first attempt, no retries
  llm_used            (llm mode) final plan came from the LLM, not the fallback
  major_coverage      share of 6 major muscle groups trained at least once per week
  avg_attempts        (llm mode) mean number of LLM calls per plan
"""
from __future__ import annotations

import argparse
import itertools
import json
import random
from pathlib import Path

from coach.exercises import get_exercise
from coach.llm import get_llm
from coach.models import UserProfile
from coach.planner import generate_plan, validate_plan

MAJOR = {"chest", "back", "shoulders", "quads", "hamstrings", "glutes"}


def grid() -> list[UserProfile]:
    combos = itertools.product(
        ["muscle_gain", "fat_loss", "strength", "general_fitness"],
        ["beginner", "intermediate", "advanced"],
        [2, 3, 4, 5, 6],
        ["bodyweight", "dumbbells", "full_gym"],
        [45, 60, 90],
    )
    return [UserProfile(goal=g, level=l, days_per_week=d, equipment=e, session_minutes=m) for g, l, d, e, m in combos]


def coverage(plan) -> float:
    hit = {get_exercise(pe.exercise_id).muscle for d in plan.days for pe in d.exercises if get_exercise(pe.exercise_id)}
    return len(hit & MAJOR) / len(MAJOR)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["fallback", "llm"], default="fallback")
    ap.add_argument("--limit", type=int, default=0, help="random subset size (useful for llm mode)")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    profiles = grid()
    if args.limit:
        random.Random(args.seed).shuffle(profiles)
        profiles = profiles[: args.limit]
    llm = get_llm() if args.mode == "llm" else None
    if args.mode == "llm" and llm is None:
        raise SystemExit("No GROQ_API_KEY found.")

    rows = []
    for p in profiles:
        res = generate_plan(p, llm)
        problems = validate_plan(res.plan, p)
        rows.append({
            "profile": p.model_dump(),
            "source": res.source,
            "attempts": res.attempts,
            "rule_valid": not problems,
            "problems": problems,
            "coverage": coverage(res.plan),
        })

    n = len(rows)
    pct = lambda k: f"{100 * sum(k) / n:.1f}%"
    print(f"\nProfiles evaluated: {n}   mode: {args.mode}")
    print(f"rule_valid:        {pct(r['rule_valid'] for r in rows)}")
    print(f"major_coverage:    {100 * sum(r['coverage'] for r in rows) / n:.1f}%")
    if args.mode == "llm":
        print(f"llm_used:          {pct(r['source'] == 'llm' for r in rows)}")
        print(f"llm_first_try:     {pct(r['source'] == 'llm' and r['attempts'] == 1 for r in rows)}")
        print(f"avg_attempts:      {sum(r['attempts'] for r in rows) / n:.2f}")

    table = ["| Metric | Value |", "|---|---|", f"| Profiles evaluated | {n} |",
             f"| Plans passing all validation rules | {pct(r['rule_valid'] for r in rows)} |",
             f"| Major muscle-group coverage | {100 * sum(r['coverage'] for r in rows) / n:.1f}% |"]
    if args.mode == "llm":
        table += [f"| Final plan came from the LLM | {pct(r['source'] == 'llm' for r in rows)} |",
                  f"| LLM valid on the first try | {pct(r['source'] == 'llm' and r['attempts'] == 1 for r in rows)} |",
                  f"| Average LLM calls per plan | {sum(r['attempts'] for r in rows) / n:.2f} |"]
    Path("eval").joinpath(f"table_{args.mode}.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print(f"Markdown table saved to eval/table_{args.mode}.md")

    out = Path("eval") / f"results_{args.mode}.json"
    out.write_text(json.dumps(rows, indent=2))
    print(f"\nDetails saved to {out}")


if __name__ == "__main__":
    main()
