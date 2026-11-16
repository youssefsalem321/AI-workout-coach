"""Smart Workout Coach - Streamlit app.  Run: streamlit run app.py"""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from coach.agent import alternatives, propose_edit, swap_exercise
from coach.deload import detect_deload
from coach.exercises import available_exercises, get_exercise
from coach.form_squat import FormAnalysisError, analyze_video
from coach.i18n import EN as EN_STRINGS
from coach.i18n import day_label, ex_name, make_t, muscle_name
from coach.llm import DEFAULT_MODEL, BudgetedLLM, get_llm
from coach.models import UserProfile, WorkoutPlan
from coach.planner import FALLBACK_NOTE, generate_plan
from coach.progression import deload_sets, llm_summary, recommend
from coach.report import KG_TO_LB, llm_report, template_report, weekly_facts
from coach.storage import Storage
from coach.ui_components import rest_timer_html

st.set_page_config(page_title="Smart Workout Coach", page_icon="🏋️", layout="wide", initial_sidebar_state="collapsed")

LANGS = {"en": "English", "ar": "العربية"}
SQUATS = ["bodyweight_squat", "goblet_squat", "back_squat", "front_squat"]


def show_html(html: str, height: int) -> None:
    """Static, trusted HTML (our own timer). st.iframe on new Streamlit, components.html on older ones."""
    if hasattr(st, "iframe"):
        st.iframe(html, height=height)
    else:
        components.html(html, height=height)


def _secret(name: str):
    try:
        return st.secrets.get(name)
    except Exception:
        return None


@st.cache_resource
def get_storage(path: str) -> Storage:
    return Storage(path)


# ----------------------------------------------------------------------------- sidebar
qp = st.query_params
with st.sidebar:
    lang_default = qp.get("lang", "en") if qp.get("lang", "en") in LANGS else "en"
    lang = st.selectbox("Language / اللغة", list(LANGS), index=list(LANGS).index(lang_default), format_func=LANGS.get)
    t = make_t(lang)
    unit_default = qp.get("unit", "kg") if qp.get("unit", "kg") in ("kg", "lb") else "kg"
    unit = st.radio(t("unit"), ["kg", "lb"], index=["kg", "lb"].index(unit_default), horizontal=True)
    qp["lang"], qp["unit"] = lang, unit

    code = st.text_input(t("private_code"), help=t("private_code_help")).strip()
    typed_key = st.text_input(t("api_key"), type="password")
    model = st.text_input(t("model"), value=os.getenv("GROQ_MODEL", DEFAULT_MODEL))

# per-user database: empty code = the default local database
if os.getenv("REQUIRE_USER_CODE", "").lower() in {"1", "true", "yes"} and not code:
    st.info(t("code_required"))
    st.stop()
db_path = "data/coach.db" if not code else f"data/users/{hashlib.sha256(code.encode()).hexdigest()[:16]}.db"
storage = get_storage(db_path)

base_llm = get_llm(typed_key or _secret("GROQ_API_KEY") or None, model or None)
llm = base_llm
max_calls = int(os.getenv("MAX_LLM_CALLS_PER_SESSION", "0") or 0)   # 0 = unlimited (local use)
if base_llm and max_calls > 0 and not typed_key:
    box = st.session_state.setdefault("llm_budget", {"left": max_calls})
    llm = BudgetedLLM(base_llm, box)

with st.sidebar:
    st.success(t("llm_on")) if llm else st.info(t("llm_off"))
    if base_llm and max_calls > 0 and not typed_key:
        st.caption(t("llm_budget", n=st.session_state["llm_budget"]["left"]))
    st.caption(t("disclaimer"))

st.markdown("""<style>
@media (max-width: 640px){
  .block-container{padding:1rem .6rem 5rem !important}
  .stButton button,.stDownloadButton button{min-height:3rem;width:100%}
}</style>""", unsafe_allow_html=True)
if lang == "ar":
    st.markdown("<style>[data-testid='stMarkdownContainer'],[data-testid='stCaptionContainer'],"
                "[data-testid='stAlert'],label{direction:rtl;text-align:right}</style>", unsafe_allow_html=True)

st.title("🏋️ " + t("app_title"))

# ----------------------------------------------------------------------------- helpers
KF = KG_TO_LB if unit == "lb" else 1.0


def to_display(kg):
    return None if kg is None else round(kg * KF * 2) / 2


def to_kg(value: float) -> float:
    return value / KF


def nm(ex_id: str) -> str:
    ex = get_exercise(ex_id)
    return ex_name(ex, lang) if ex else ex_id


def reason_text(rec) -> str:
    if not rec.code:
        return rec.reason
    p = dict(rec.params)
    for key in ("weight", "new_w", "inc"):
        if key in p:
            p[key] = to_display(p[key])
    return t(f"rec.{rec.code}", unit=unit, **p)


def plan_table(day) -> pd.DataFrame:
    rows = []
    for pe in day.exercises:
        ex = get_exercise(pe.exercise_id)
        rows.append({
            t("col_exercise"): nm(pe.exercise_id),
            t("col_muscle"): muscle_name(ex.muscle, lang) if ex else "?",
            t("col_setsreps"): f"{pe.sets} x {pe.rep_min}-{pe.rep_max}",
            t("col_rest"): f"{pe.rest_seconds}s",
        })
    return pd.DataFrame(rows)


def render_plan(plan: WorkoutPlan, profile: UserProfile) -> None:
    st.subheader(t("plan_title", days=len(plan.days), goal=t(f"goal.{profile.goal}")))
    note = t("fallback_note") if plan.notes == FALLBACK_NOTE else plan.notes
    if note:
        st.caption(note)
    for i, day in enumerate(plan.days, start=1):
        with st.expander(t("day_n", n=i, name=day_label(day.name, lang)), expanded=(i == 1)):
            st.dataframe(plan_table(day), hide_index=True, width="stretch")


def local_summary(recs) -> str:
    up = [nm(r.exercise_id) for r in recs if r.action == "increase"]
    down = [nm(r.exercise_id) for r in recs if r.action in ("decrease", "deload")]
    parts = [t("sum.saved")]
    if up:
        parts.append(t("sum.up", names=", ".join(up)))
    if down:
        parts.append(t("sum.down", names=", ".join(down)))
    if not up and not down:
        parts.append(t("sum.stay"))
    return " ".join(parts)


tab_plan, tab_today, tab_progress, tab_adjust, tab_form = st.tabs(
    ["🗓 " + t("tab_plan"), "🏋 " + t("tab_today"), "📈 " + t("tab_progress"), "✏️ " + t("tab_adjust"), "🎥 " + t("tab_form")])

active = storage.active_plan()

# ----------------------------------------------------------------------------- tab: plan
with tab_plan:
    st.header(t("build_plan"))
    with st.form("profile_form"):
        c1, c2 = st.columns(2)
        goal = c1.selectbox(t("goal"), ["muscle_gain", "fat_loss", "strength", "general_fitness"], format_func=lambda x: t(f"goal.{x}"))
        level = c2.selectbox(t("level"), ["beginner", "intermediate", "advanced"], format_func=lambda x: t(f"level.{x}"))
        days = c1.slider(t("days"), 2, 6, 4)
        equipment = c2.selectbox(t("equipment"), ["bodyweight", "dumbbells", "full_gym"], format_func=lambda x: t(f"eq.{x}"))
        minutes = st.slider(t("minutes"), 30, 120, 60, step=5)
        submitted = st.form_submit_button(t("generate"), type="primary")

    if submitted:
        profile = UserProfile(goal=goal, level=level, days_per_week=days, equipment=equipment, session_minutes=minutes)
        with st.spinner(t("generating")):
            st.session_state["preview"] = (profile, generate_plan(profile, llm, lang=lang))

    if "preview" in st.session_state:
        profile, result = st.session_state["preview"]
        st.caption(f"{t('source')}: **{result.source}**" + (f" ({t('attempts')}: {result.attempts})" if result.attempts else ""))
        for w in result.warnings:
            st.warning(w)
        render_plan(result.plan, profile)
        if st.button(t("save_plan"), type="primary"):
            storage.save_plan(profile, result.plan)
            storage.set_setting("deload_active", "0")
            del st.session_state["preview"]
            st.success(t("saved"))
            st.rerun()
    elif active:
        st.divider()
        st.caption(t("current_plan"))
        render_plan(active[2], active[1])

# ----------------------------------------------------------------------------- tab: today
with tab_today:
    if not active:
        st.info(t("no_plan"))
    else:
        plan_id, profile, plan = active
        deload_on = storage.get_setting("deload_active", "0") == "1"
        if deload_on:
            st.info(t("deload_active"))
            if st.button(t("end_deload")):
                storage.set_setting("deload_active", "0")
                st.rerun()
        else:
            ids = {pe.exercise_id for d in plan.days for pe in d.exercises}
            sug = detect_deload({i: storage.exercise_sessions(i, days=14) for i in ids})
            if sug.should_deload:
                lines = [f"- {nm(tr.exercise_id)}: {t('reason.' + tr.reason, v=tr.detail)}" for tr in sug.trends]
                st.warning(t("deload_suggest") + "\n\n" + "\n".join(lines))
                if st.button(t("start_deload")):
                    storage.set_setting("deload_active", "1")
                    st.rerun()

        show_html(rest_timer_html(t("rest_timer")), height=80)

        next_day = storage.session_count(plan_id) % len(plan.days)
        day_idx = st.selectbox(t("day"), list(range(len(plan.days))), index=next_day,
                               format_func=lambda i: t("day_n", n=i + 1, name=day_label(plan.days[i].name, lang)))
        day = plan.days[day_idx]

        with st.form(f"session_form_{plan_id}_{day_idx}_{int(deload_on)}"):
            frames: dict[str, pd.DataFrame] = {}
            for pe in day.exercises:
                ex = get_exercise(pe.exercise_id)
                rec = recommend(storage.exercise_history(ex.id, 3), pe, ex,
                                form_score=storage.latest_form_score(ex.id), deload=deload_on)
                n_sets = deload_sets(pe.sets) if deload_on else pe.sets
                st.markdown(f"**{nm(ex.id)}** - {n_sets} x {pe.rep_min}-{pe.rep_max}, {t('col_rest')} {pe.rest_seconds}s")
                st.caption(f"{t('coach_says')}: {reason_text(rec)}")
                start_w = to_display(rec.next_weight) or 0.0
                df = pd.DataFrame({
                    "set": list(range(1, n_sets + 1)),
                    "weight": [float(start_w)] * n_sets,
                    "reps": [0] * n_sets,
                    "rpe": pd.Series([None] * n_sets, dtype="float64"),
                })
                frames[ex.id] = st.data_editor(
                    df, key=f"ed_{plan_id}_{day_idx}_{ex.id}_{int(deload_on)}", hide_index=True, disabled=["set"],
                    column_config={
                        "set": st.column_config.NumberColumn(t("set")),
                        "weight": st.column_config.NumberColumn(t("weight_col", unit=unit), min_value=0.0, max_value=1500.0, step=0.5),
                        "reps": st.column_config.NumberColumn(t("reps"), min_value=0, max_value=100, step=1),
                        "rpe": st.column_config.NumberColumn(t("rpe"), min_value=1.0, max_value=10.0, step=0.5, help=t("rpe_help")),
                    },
                    width="stretch",
                )
            finished = st.form_submit_button(t("finish"), type="primary")

        if finished:
            entries = []
            for ex_id, df in frames.items():
                for _, row in df.iterrows():
                    if int(row["reps"]) > 0:
                        entries.append({"exercise_id": ex_id, "set_number": int(row["set"]),
                                        "weight": to_kg(float(row["weight"])), "reps": int(row["reps"]),
                                        "rpe": None if pd.isna(row["rpe"]) else float(row["rpe"])})
            if not entries:
                st.warning(t("enter_reps"))
            else:
                storage.log_session(plan_id, day_idx, entries)
                logged = {e["exercise_id"] for e in entries}
                recs = [recommend(storage.exercise_history(pe.exercise_id, 3), pe, get_exercise(pe.exercise_id),
                                  form_score=storage.latest_form_score(pe.exercise_id), deload=deload_on)
                        for pe in day.exercises if pe.exercise_id in logged]
                names = {r.exercise_id: nm(r.exercise_id) for r in recs}
                st.success(llm_summary(llm, recs, names, lang) if llm else local_summary(recs))
                st.markdown("**" + t("next_time") + "**")
                st.dataframe(pd.DataFrame([{
                    t("col_exercise"): names[r.exercise_id], t("col_action"): t(f"action.{r.action}"),
                    t("col_weight", unit=unit): to_display(r.next_weight) if r.next_weight is not None else "-",
                    t("col_target"): r.target_reps,
                } for r in recs]), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- tab: progress
with tab_progress:
    rows = storage.all_sets()
    if not rows:
        st.info(t("log_to_see"))
    else:
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["performed_at"])
        df["w"] = df["weight"] * KF
        df["volume"] = df["w"] * df["reps"]
        df["e1rm"] = df["w"] * (1 + df["reps"] / 30)  # Epley estimate
        df["name"] = df["exercise_id"].map(nm)

        m1, m2, m3 = st.columns(3)
        m1.metric(t("sessions"), df["session_id"].nunique())
        m2.metric(t("sets_logged"), len(df))
        m3.metric(t("total_volume", unit=unit), f"{df['volume'].sum():,.0f}")

        choice = st.selectbox(t("exercise"), sorted(df["name"].unique()))
        sub = df[df["name"] == choice]
        if sub["w"].max() > 0:
            best = sub.groupby("session_id").agg(date=("date", "first"), e1rm=("e1rm", "max"), top_weight=("w", "max"))
            st.markdown("**" + t("chart_1rm", unit=unit) + "**")
            st.line_chart(best.set_index("date")[["e1rm", "top_weight"]])
        else:  # bodyweight exercise: chart best reps
            best = sub.groupby("session_id").agg(date=("date", "first"), reps=("reps", "max"))
            st.markdown("**" + t("reps") + "**")
            st.line_chart(best.set_index("date")[["reps"]])

        st.markdown("**" + t("chart_volume", unit=unit) + "**")
        st.bar_chart(df.set_index("date")["volume"].resample("W").sum())

        if df["rpe"].notna().any():
            st.markdown("**" + t("chart_rpe") + "**")
            st.line_chart(df.groupby("session_id").agg(date=("date", "first"), rpe=("rpe", "mean")).set_index("date"))

    st.divider()
    st.subheader(t("body_weight"))
    bws = storage.body_weights()
    last_bw = to_display(bws[-1]["weight_kg"]) if bws else 70.0 * KF
    c1, c2 = st.columns([2, 1])
    new_bw = c1.number_input(t("bw_input", unit=unit), min_value=20.0, max_value=500.0, value=float(last_bw), step=0.1)
    if c2.button(t("bw_log")):
        storage.add_body_weight(to_kg(new_bw))
        st.rerun()
    if bws:
        bdf = pd.DataFrame(bws)
        bdf["date"] = pd.to_datetime(bdf["logged_at"])
        bdf[unit] = bdf["weight_kg"] * KF
        st.line_chart(bdf.set_index("date")[[unit]])
    else:
        st.caption(t("bw_none"))

    st.divider()
    st.subheader(t("weekly_report"))
    if st.button(t("gen_report")):
        facts = weekly_facts(rows, len(active[2].days) if active else 0, bws, unit=unit)
        names = {i: nm(i) for i in {r["exercise_id"] for r in rows}}
        st.session_state["report"] = llm_report(llm, facts, names, lang) if llm else template_report(facts, names, lang)
    if st.session_state.get("report"):
        st.markdown(st.session_state["report"])

    st.divider()
    st.subheader(t("export"))
    if rows:
        out = pd.DataFrame(rows)
        out["exercise"] = out["exercise_id"].map(lambda i: get_exercise(i).name if get_exercise(i) else i)
        out["weight_kg"] = out["weight"].round(2)
        out[f"weight_{unit}"] = (out["weight"] * KF).round(1)
        out = out[["performed_at", "session_id", "day_index", "exercise", "set_number", "weight_kg", f"weight_{unit}", "reps", "rpe"]]
        st.download_button(t("dl_training"), out.to_csv(index=False).encode("utf-8-sig"), "training_log.csv", "text/csv")
    if bws:
        st.download_button(t("dl_bw"), pd.DataFrame(bws).to_csv(index=False).encode("utf-8-sig"), "body_weight.csv", "text/csv")

# ----------------------------------------------------------------------------- tab: adjust plan
with tab_adjust:
    if not active:
        st.info(t("no_plan"))
    else:
        plan_id, profile, plan = active
        st.subheader(t("swap_header"))
        c1, c2, c3 = st.columns(3)
        d = c1.selectbox(t("swap_day"), list(range(len(plan.days))), key="swap_day",
                         format_func=lambda i: t("day_n", n=i + 1, name=day_label(plan.days[i].name, lang)))
        old = c2.selectbox(t("swap_exercise"), [pe.exercise_id for pe in plan.days[d].exercises], format_func=nm, key=f"swap_old_{d}")
        alts = alternatives(plan, profile, d, old)
        if not alts:
            c3.caption(t("no_alt"))
        else:
            new = c3.selectbox(t("swap_with"), [a.id for a in alts], format_func=nm, key=f"swap_new_{d}_{old}")
            if st.button(t("swap_btn")):
                storage.update_plan(plan_id, swap_exercise(plan, profile, d, old, new),
                                    request=f"swap {old} -> {new} (day {d + 1})", summary="manual swap")
                st.toast(t("swapped"))
                st.rerun()

        st.divider()
        st.subheader(t("chat_header"))
        st.caption(t("chat_hint"))
        request = st.text_area(t("chat_header"), key="edit_request", label_visibility="collapsed", max_chars=500)
        if llm is None:
            st.info(t("chat_needs_llm"))
        elif st.button(t("chat_btn")) and request.strip():
            with st.spinner("..."):
                st.session_state["edit_proposal"] = (plan_id, request.strip(), propose_edit(llm, plan, profile, request, lang))

        prop = st.session_state.get("edit_proposal")
        if prop and prop[0] == plan_id:
            _, req_text, res = prop
            if res.message:
                st.write(res.message)
            if res.errors:
                st.error(t("edit_failed"))
                for e in res.errors:
                    st.write("- " + e)
            elif not res.applied:
                st.info(t("no_changes"))
            else:
                st.markdown("**" + t("proposal") + "**")
                for a in res.applied:
                    st.write("- " + a)
                render_plan(res.plan, profile)
                b1, b2 = st.columns(2)
                if b1.button(t("apply"), type="primary"):
                    storage.update_plan(plan_id, res.plan, request=req_text, summary="; ".join(res.applied))
                    del st.session_state["edit_proposal"]
                    st.toast(t("applied_ok"))
                    st.rerun()
                if b2.button(t("discard")):
                    del st.session_state["edit_proposal"]
                    st.rerun()

        edits = storage.plan_edits(plan_id)
        if edits:
            with st.expander(t("history")):
                for e in edits:
                    st.caption(f"{e['edited_at'][:16]} - {e['request']}")

# ----------------------------------------------------------------------------- tab: form check
with tab_form:
    st.subheader(t("form_header"))
    st.caption(t("form_tips"))
    options = SQUATS
    if active:
        allowed = {e.id for e in available_exercises(active[1].equipment, active[1].level)}
        options = [s for s in SQUATS if s in allowed] or SQUATS
    ex_id = st.selectbox(t("form_exercise"), options, format_func=nm)
    video = st.file_uploader(t("upload"), type=["mp4", "mov", "m4v", "avi"])
    if video is not None and st.button(t("analyze"), type="primary"):
        suffix = Path(video.name).suffix or ".mp4"
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(video.getvalue())
            tmp_path = tmp.name
        try:
            with st.spinner(t("analyzing")):
                report = analyze_video(tmp_path)
            if report.rep_count == 0:
                st.error(t("err.no_reps"))
            else:
                c1, c2 = st.columns(2)
                c1.metric(t("form_score"), f"{report.score:.0f}/100")
                c2.metric(t("reps_detected"), report.rep_count)
                for issue in report.issues:
                    (st.success if issue["code"] == "clean" else st.warning)(t(f"issue.{issue['code']}", n=issue["count"]))
                adf = pd.DataFrame(report.angle_series, columns=["t", "angle"]).set_index("t")
                st.markdown("**" + t("chart_knee") + "**")
                st.line_chart(adf)
                storage.add_form_check(ex_id, report.score, report.rep_count, report.issues)
                st.caption(t("form_saved"))
        except FormAnalysisError as exc:
            key = str(exc).split(":")[0]
            st.error(t(f"err.{key}") if f"err.{key}" in EN_STRINGS else str(exc))
        finally:
            Path(tmp_path).unlink(missing_ok=True)
