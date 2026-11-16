"""Weekly report. All numbers are computed here; the LLM (optional) only writes the wording."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .exercises import get_exercise

KG_TO_LB = 2.20462


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def _e1rm(weight: float, reps: int) -> float:
    return weight * (1 + reps / 30) if weight > 0 else float(reps)


def weekly_facts(rows: list[dict], planned_days: int, body_weights: list[dict] | None = None,
                 now: datetime | None = None, unit: str = "kg") -> dict:
    """rows = Storage.all_sets(). Returns a plain dict of facts for the last 7 days vs the 7 before."""
    now = now or datetime.now(timezone.utc)
    start, prev_start = now - timedelta(days=7), now - timedelta(days=14)
    k = KG_TO_LB if unit == "lb" else 1.0

    cur = [r for r in rows if _dt(r["performed_at"]) >= start]
    prev = [r for r in rows if prev_start <= _dt(r["performed_at"]) < start]
    older = [r for r in rows if _dt(r["performed_at"]) < start]

    def volume(rs):
        return sum(r["weight"] * r["reps"] for r in rs) * k

    def avg_rpe(rs):
        v = [r["rpe"] for r in rs if r.get("rpe") is not None]
        return round(sum(v) / len(v), 1) if v else None

    def best(rs):
        out: dict[str, float] = {}
        for r in rs:
            out[r["exercise_id"]] = max(out.get(r["exercise_id"], 0.0), _e1rm(r["weight"], r["reps"]))
        return out

    best_cur, best_prev, best_older = best(cur), best(prev), best(older)
    changes, prs = [], []
    for ex_id, val in best_cur.items():
        if ex_id in best_prev and best_prev[ex_id] > 0:
            changes.append({"exercise_id": ex_id, "change_pct": round(100 * (val / best_prev[ex_id] - 1), 1),
                            "now": round(val * k, 1)})
        if ex_id in best_older and val > best_older[ex_id] * 1.001:
            prs.append({"exercise_id": ex_id, "e1rm": round(val * k, 1)})
    changes.sort(key=lambda c: c["change_pct"], reverse=True)

    bw = None
    if body_weights:
        latest = body_weights[-1]
        older_bw = [b for b in body_weights if _dt(b["logged_at"]) <= now - timedelta(days=6)]
        bw = {"latest": round(latest["weight_kg"] * k, 1),
              "change": round((latest["weight_kg"] - older_bw[-1]["weight_kg"]) * k, 1) if older_bw else None}

    return {
        "unit": unit,
        "sessions": len({r["session_id"] for r in cur}),
        "planned_days": planned_days,
        "sets": len(cur),
        "volume": round(volume(cur)),
        "volume_prev": round(volume(prev)),
        "avg_rpe": avg_rpe(cur),
        "improved": [c for c in changes if c["change_pct"] > 0][:3],
        "declined": [c for c in changes if c["change_pct"] < 0][-2:],
        "prs": prs[:5],
        "body_weight": bw,
    }


def _name(ex_id: str, names: dict[str, str]) -> str:
    if ex_id in names:
        return names[ex_id]
    e = get_exercise(ex_id)
    return e.name if e else ex_id


def template_report(facts: dict, names: dict[str, str], lang: str = "en") -> str:
    u = facts["unit"]
    ar = lang == "ar"
    if facts["sessions"] == 0:
        return "ما فيش تمارين متسجلة الأسبوع ده. ابدأ بجلسة واحدة وهنتابع من هنا." if ar else \
               "No workouts logged this week. Log one session and the report will start tracking from there."
    lines = []
    if ar:
        lines.append(f"خلّصت {facts['sessions']} جلسة من {facts['planned_days']} مخططين، و{facts['sets']} set، بحجم تدريب {facts['volume']:,} {u}.")
        if facts["volume_prev"]:
            d = 100 * (facts["volume"] / facts["volume_prev"] - 1)
            lines.append(f"الحجم {'زاد' if d >= 0 else 'قل'} {abs(d):.0f}% عن الأسبوع اللي فات.")
        if facts["avg_rpe"] is not None:
            lines.append(f"متوسط الصعوبة (RPE): {facts['avg_rpe']}.")
        for c in facts["improved"]:
            lines.append(f"تحسّن: {_name(c['exercise_id'], names)} (+{c['change_pct']}%).")
        for p in facts["prs"]:
            lines.append(f"رقم قياسي جديد: {_name(p['exercise_id'], names)} (1RM مقدّر {p['e1rm']} {u}).")
        for c in facts["declined"]:
            lines.append(f"نزول: {_name(c['exercise_id'], names)} ({c['change_pct']}%).")
        if facts["body_weight"]:
            b = facts["body_weight"]
            lines.append(f"وزن الجسم: {b['latest']} {u}" + (f" ({b['change']:+} عن الأسبوع الماضي)." if b["change"] is not None else "."))
    else:
        lines.append(f"You completed {facts['sessions']} of {facts['planned_days']} planned sessions: {facts['sets']} sets, {facts['volume']:,} {u} of volume.")
        if facts["volume_prev"]:
            d = 100 * (facts["volume"] / facts["volume_prev"] - 1)
            lines.append(f"Volume is {'up' if d >= 0 else 'down'} {abs(d):.0f}% vs last week.")
        if facts["avg_rpe"] is not None:
            lines.append(f"Average effort (RPE): {facts['avg_rpe']}.")
        for c in facts["improved"]:
            lines.append(f"Improved: {_name(c['exercise_id'], names)} (+{c['change_pct']}%).")
        for p in facts["prs"]:
            lines.append(f"New PR: {_name(p['exercise_id'], names)} (est. 1RM {p['e1rm']} {u}).")
        for c in facts["declined"]:
            lines.append(f"Dropped: {_name(c['exercise_id'], names)} ({c['change_pct']}%).")
        if facts["body_weight"]:
            b = facts["body_weight"]
            lines.append(f"Body weight: {b['latest']} {u}" + (f" ({b['change']:+} vs last week)." if b["change"] is not None else "."))
    return "\n\n".join(lines)


def llm_report(llm, facts: dict, names: dict[str, str], lang: str = "en") -> str:
    readable = dict(facts)
    for key in ("improved", "declined", "prs"):
        readable[key] = [{**x, "exercise": _name(x["exercise_id"], names)} for x in facts[key]]
    messages = [
        {"role": "system", "content": "You are a supportive strength coach writing a short weekly review (max 120 words). "
         "Use ONLY the numbers in the JSON; never invent or change a number, no medical advice. Give one concrete focus for "
         "next week." + (" Write in Arabic." if lang == "ar" else "")},
        {"role": "user", "content": json.dumps(readable, ensure_ascii=False)},
    ]
    try:
        return llm.chat_text(messages)
    except Exception:
        return template_report(facts, names, lang)
