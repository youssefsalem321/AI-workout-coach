# 🏋️ Smart Workout Coach

An AI workout coach that builds a personalized plan, tracks every set (weight, reps, effort), adapts your weights
session after session, edits the plan when you ask in plain language, and checks your squat form from a video.
English and Arabic UI, kg/lb, runs offline without an API key.

**The key idea:** the LLM never gets to improvise on things that must be correct.
Code decides the structure and the numbers; the LLM makes choices inside strict guardrails; every output is validated.

## Features

| Area | What it does |
|---|---|
| **Plan generation** | Split chosen by code (full body / upper-lower / PPL); LLM picks exercises from an allowed list; Pydantic + rule validation; retry with the exact errors; deterministic fallback |
| **Progressive overload** | Double progression in pure Python. Uses **RPE** (RPE 9.5+ blocks a weight increase; RPE 7 or less takes a bigger step) and your latest **form score** (below 70 blocks an increase) |
| **Auto deload** | If at least two lifts regress within 14 days (estimated 1RM down 3%+, or effort rising with no progress) the app recommends a deload week: ~60% of sets, -10% weight |
| **Plan-editing agent** | "My shoulder hurts, remove overhead presses." The LLM can only emit operations from a 4-tool set; code applies them to a copy, validates, and rejects atomically. You preview and confirm before anything is saved |
| **Exercise swap** | One click, same-muscle alternatives filtered by your equipment and level (works offline) |
| **Squat form check** | Side-view video -> MediaPipe Pose -> knee angle -> rep counting -> depth, torso lean, tempo -> 0-100 score. Geometry, not an LLM, so it is explainable. The score feeds back into progression |
| **Weekly report** | Numbers computed by code; the LLM (optional) only writes the wording |
| **Product** | Rest timer, kg/lb, body-weight log + chart, CSV export, English/Arabic (RTL), mobile-friendly layout |
| **Safety** | Per-session AI call budget, per-user databases, "not medical advice" notes, user text treated as data |

## Architecture

```
Profile ──► split + slots (code) ──► LLM picks exercises ──► schema + rule validator ─ invalid ─► retry w/ errors ─► rule-based fallback
Chat request ──► LLM emits tool calls ──► apply on a copy ──► validate ──► preview ──► you confirm ──► save
Workout log (SQLite: kg, reps, RPE) ──► progression rules (+ form score, + deload) ──► next weights
Squat video ──► MediaPipe landmarks ──► angles/reps/score ──► stored form check ──► gates weight increases
```

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
copy .env.example .env            # macOS/Linux: cp .env.example .env ; then add GROQ_API_KEY (optional)
streamlit run app.py
```

Without a key the app runs in offline mode (rule-based planner; the chat agent needs a key).

**Squat form check (optional, heavy):** `pip install -r requirements-form.txt`. Newer MediaPipe versions download a small
pose model (~5 MB) on first use, so the first analysis needs internet. How to film: side view, phone at hip height,
whole body in frame, 3-8 reps, stand fully between reps.

## Tests and evaluation

```bash
pytest -q                                          # 587 tests
python -m eval.run_eval --mode fallback            # offline baseline over 540 profiles
python -m eval.run_eval --mode llm --limit 60      # needs GROQ_API_KEY; writes eval/table_llm.md
```

Offline baseline (540 profiles): 100% of plans pass every validation rule. Run the `llm` mode with your key, then paste
`eval/table_llm.md` here:

| Metric | Value |
|---|---|
| Plans passing all validation rules | 100% (rule-based) |
| LLM valid on the first try | _run `--mode llm`_ |
| Final plan came from the LLM | _run `--mode llm`_ |
| Average LLM calls per plan | _run `--mode llm`_ |

## Deploy

See [DEPLOY.md](DEPLOY.md): Streamlit Community Cloud, Hugging Face Spaces, Docker, and phone "Add to Home Screen".

## Project layout

```
app.py                  Streamlit UI (Plan · Today · Progress · Adjust plan · Form check)
coach/exercises.py      exercise library (the LLM's allowed vocabulary)
coach/planner.py        split, prompt, validation, retries, fallback
coach/progression.py    overload rules: RPE, form gate, deload mode
coach/deload.py         automatic deload detection
coach/agent.py          swap + plan-editing agent (constrained tool calls)
coach/report.py         weekly facts + report
coach/form_squat.py     pose -> angles -> reps -> score
coach/storage.py        SQLite (plans, sessions, sets+RPE, body weight, form checks, edits)
coach/i18n.py           English / Arabic strings and exercise names
coach/llm.py            Groq wrapper + call budget
eval/run_eval.py        evaluation harness
tests/                  pytest suite
```

## Known limitations

- Squat analysis needs a **side-view** video and a stand-up between reps; it does not judge knee cave (needs a front view).
- Form analysis was developed against synthetic landmark data and a fake pose backend; validate the thresholds on your own videos and tune them in `coach/form_squat.py`.
- SQLite on free hosting is ephemeral (see DEPLOY.md). Single-user local use is the sweet spot.
- Plan-change summaries shown in the chat agent are in English even in Arabic mode.
- Responsive web app, not an installable PWA.

> General training guidance only. Not medical advice or a substitute for a qualified coach.
