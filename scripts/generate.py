#!/usr/bin/env python3
"""Regenerate the OpsLedger dashboard pages from Cowork's local JSON logs.

Reads ~/Documents/Cowork/{time_log,estimate_log}.json, computes the reporting
aggregates fresh (relative to today), fills the four page templates, and
writes time-stats.html / time-detail.html / time-kantata.html / tasks.html
into the repo root. Pure data plumbing, no LLM calls -- meant to run headless
from a nightly launchd job (see scripts/publish.sh).
"""
import json
import datetime
import collections
import pathlib
import re

COWORK_DIR = pathlib.Path.home() / "Documents" / "Cowork"
REPO_DIR = pathlib.Path(__file__).resolve().parent.parent
TEMPLATES_DIR = REPO_DIR / "templates"

TODAY = datetime.date.today()
NOW = datetime.datetime.now()


def load_json(name):
    return json.loads((COWORK_DIR / name).read_text(encoding="utf-8"))


def iso_week_start(d):
    return d - datetime.timedelta(days=d.weekday())


def fmt_month_day(d):
    return d.strftime("%b ") + str(d.day)


def trim_num(x, decimals=2):
    s = f"{x:.{decimals}f}"
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


def dumps(obj):
    # ensure_ascii=True (default) escapes every non-ASCII char as \uXXXX,
    # which keeps the embedded JSON safe regardless of how the file gets
    # served -- see the mojibake issue we hit with literal em-dashes earlier.
    return json.dumps(obj)


def generated_label():
    return f"Synced {fmt_month_day(TODAY)}, {TODAY.year} &middot; {NOW.strftime('%-I:%M%p').lower()}"


def render_template(name, replacements, out_name=None):
    tpl_path = TEMPLATES_DIR / f"{name}.template.html"
    out_path = REPO_DIR / (out_name or f"{name}.html")
    text = tpl_path.read_text(encoding="utf-8")
    for key, value in replacements.items():
        placeholder = f"__{key}__"
        if placeholder not in text:
            raise ValueError(f"{tpl_path.name}: placeholder {placeholder} not found")
        text = text.replace(placeholder, value)
    leftover = set(re.findall(r"__[A-Z][A-Z_]*__", text))
    if leftover:
        raise ValueError(f"{tpl_path.name}: unfilled placeholder(s) {sorted(leftover)}")
    out_path.write_text(text, encoding="utf-8")
    return out_path


# --------------------------------------------------------------------------
# Shared: slim time_log entries + project map (used by Detail and Kantata)
# --------------------------------------------------------------------------

def load_time_log():
    data = load_json("time_log.json")
    entries = data["entries"]
    pmap = data["project_map"]
    slim = [
        {
            "date": e["date"],
            "client": e["client"],
            "project": e["project"],
            "kantata_id": e["kantata_id"],
            "activity": e["activity"],
            "hours": e["hours"],
            "notes": e.get("notes", ""),
            "billable": e["billable"],
        }
        for e in entries
    ]
    return entries, slim, pmap


# --------------------------------------------------------------------------
# Time -- Stats
# --------------------------------------------------------------------------

NAME_COLOR = {"Meetings": "--p-blue", "Planning": "--p-aqua"}
FALLBACK_COLORS = ["--p-orange", "--p-blue", "--p-aqua"]


def assign_pie_colors(pie):
    used = set()
    for s in pie["slices"]:
        if s["label"] == "Other":
            s["color"] = "--ink-muted-2"
            continue
        color = NAME_COLOR.get(s["label"])
        if color is None or color in used:
            color = next((c for c in FALLBACK_COLORS if c not in used), "--p-orange")
        s["color"] = color
        used.add(color)
    return pie


def activity_mix(recent, billable_flag):
    acts = collections.Counter()
    for e in recent:
        if e["billable"] != billable_flag:
            continue
        a = e["activity"]
        if a == "Meeting":
            a = "Meetings"
        acts[a] += e["hours"]
    total = sum(acts.values())
    top = acts.most_common(3)
    other = total - sum(h for _, h in top)
    slices = [{"label": a, "hours": round(h, 2)} for a, h in top]
    if other > 0.01:
        slices.append({"label": "Other", "hours": round(other, 2)})
    pie = {"title": "Billable" if billable_flag else "Non-billable", "total": round(total, 2), "slices": slices}
    return assign_pie_colors(pie)


def build_time_stats(entries):
    this_week_start = iso_week_start(TODAY)
    week_starts = [this_week_start - datetime.timedelta(weeks=i) for i in range(9, -1, -1)]
    cutoff = week_starts[0]

    weekly = []
    for ws in week_starts:
        we = ws + datetime.timedelta(days=6)
        billable = nonbillable = 0.0
        for e in entries:
            d = datetime.date.fromisoformat(e["date"])
            if ws <= d <= we:
                if e["billable"]:
                    billable += e["hours"]
                else:
                    nonbillable += e["hours"]
        weekly.append(
            {
                "label": fmt_month_day(ws),
                "full": "Week of " + fmt_month_day(ws),
                "billable": round(billable, 2),
                "nonbillable": round(nonbillable, 2),
                "partial": we > TODAY,
            }
        )

    recent = [e for e in entries if datetime.date.fromisoformat(e["date"]) >= cutoff]
    total_hours = sum(e["hours"] for e in recent)
    billable_hours = sum(e["hours"] for e in recent if e["billable"])
    nonbillable_hours = total_hours - billable_hours
    pct_billable = (billable_hours / total_hours * 100) if total_hours else 0.0
    num_clients = len({e["client"] for e in recent})

    proj = collections.defaultdict(lambda: {"hours": 0.0, "billable": True})
    for e in recent:
        key = (e["client"], e["project"])
        proj[key]["hours"] += e["hours"]
        proj[key]["billable"] = e["billable"]
    ranked = sorted(proj.items(), key=lambda kv: -kv[1]["hours"])[:8]
    projects_out = [
        {"name": f"{c} / {p}", "hours": round(v["hours"], 2), "billable": v["billable"]} for (c, p), v in ranked
    ]

    pie_billable = activity_mix(recent, True)
    pie_nonbillable = activity_mix(recent, False)

    render_template(
        "time-stats",
        {
            "GENERATED_LABEL": generated_label(),
            "PCT_BILLABLE": trim_num(pct_billable, 1),
            "TOTAL_HRS": trim_num(total_hours, 1),
            "BILLABLE_HRS": trim_num(billable_hours, 1),
            "NONBILLABLE_HRS": trim_num(nonbillable_hours, 1),
            "NUM_CLIENTS": str(num_clients),
            "WEEKLY_JSON": dumps(weekly),
            "PROJECTS_JSON": dumps(projects_out),
            "PIE_BILLABLE_JSON": dumps(pie_billable),
            "PIE_NONBILLABLE_JSON": dumps(pie_nonbillable),
        },
    )


# --------------------------------------------------------------------------
# Time -- Detail & Kantata (share the same raw data)
# --------------------------------------------------------------------------

def build_time_detail(slim_entries, pmap):
    render_template(
        "time-detail",
        {
            "GENERATED_LABEL": generated_label(),
            "ALL_ENTRIES": dumps(slim_entries),
            "PROJECT_MAP": dumps(pmap),
        },
    )


def build_time_kantata(slim_entries, pmap):
    render_template(
        "time-kantata",
        {
            "GENERATED_LABEL": generated_label(),
            "ALL_ENTRIES": dumps(slim_entries),
            "PROJECT_MAP": dumps(pmap),
        },
    )


# --------------------------------------------------------------------------
# Tasks
# --------------------------------------------------------------------------

def build_tasks():
    data = load_json("estimate_log.json")
    entries = data["entries"]
    if not entries:
        return

    window_start = TODAY - datetime.timedelta(days=14)
    recent = [e for e in entries if datetime.date.fromisoformat(e["date"]) >= window_start]
    if not recent:
        recent = entries[-75:]

    n = len(recent)
    within = [e for e in recent if abs(e["variance"]) <= 0.25]
    accuracy_pct = round(len(within) / n * 100) if n else 0
    missed = [e for e in recent if abs(e["variance"]) > 0.25]
    avg_miss = (sum(abs(e["variance"]) for e in missed) / len(missed)) if missed else 0.0
    over = [e for e in missed if e["variance"] > 0]
    under = [e for e in missed if e["variance"] < 0]

    total_est = sum(e["est_hours"] for e in recent)
    total_act = sum(e["actual_hours"] for e in recent)

    status_counts = collections.Counter(e["status"] for e in recent)
    done = status_counts.get("Done", 0)
    carried = status_counts.get("Carried", 0)
    dropped = status_counts.get("Dropped", 0)

    daily = collections.defaultdict(lambda: {"est": 0.0, "act": 0.0, "n": 0})
    for e in recent:
        d = daily[e["date"]]
        d["est"] += e["est_hours"]
        d["act"] += e["actual_hours"]
        d["n"] += 1
    estvact = [
        {
            "label": fmt_month_day(datetime.date.fromisoformat(d)),
            "full": fmt_month_day(datetime.date.fromisoformat(d)),
            "est": round(daily[d]["est"], 2),
            "act": round(daily[d]["act"], 2),
            "n": daily[d]["n"],
        }
        for d in sorted(daily.keys())
    ]

    top_variance = sorted(recent, key=lambda e: -abs(e["variance"]))[:8]
    variance_out = [
        {
            "item": e["item"],
            "date": fmt_month_day(datetime.date.fromisoformat(e["date"])),
            "est": e["est_hours"],
            "act": e["actual_hours"],
            "status": e["status"],
        }
        for e in top_variance
    ]

    threads_map = collections.defaultdict(list)
    for e in entries:
        threads_map[e["item"]].append(e)
    multi = {k: v for k, v in threads_map.items() if len(v) > 1}
    multi_sorted = sorted(multi.items(), key=lambda kv: -len(kv[1]))[:20]
    threads_out = []
    for item, es in multi_sorted:
        es_sorted = sorted(es, key=lambda e: e["date"])
        threads_out.append(
            {
                "item": item,
                "days": len(es_sorted),
                "first": fmt_month_day(datetime.date.fromisoformat(es_sorted[0]["date"])),
                "last": fmt_month_day(datetime.date.fromisoformat(es_sorted[-1]["date"])),
                "est": round(sum(x["est_hours"] for x in es_sorted), 2),
                "act": round(sum(x["actual_hours"] for x in es_sorted), 2),
                "status": es_sorted[-1]["status"],
            }
        )

    render_template(
        "tasks",
        {
            "GENERATED_LABEL": generated_label(),
            "ACCURACY_PCT": str(accuracy_pct),
            "WITHIN_COUNT": str(len(within)),
            "TOTAL_COUNT": str(n),
            "DONE_COUNT": str(done),
            "CARRIED_COUNT": str(carried),
            "DROPPED_COUNT": str(dropped),
            "DONE_PCT": trim_num(done / n * 100, 1) if n else "0",
            "CARRIED_PCT": trim_num(carried / n * 100, 1) if n else "0",
            "DROPPED_PCT": trim_num(dropped / n * 100, 1) if n else "0",
            "UNDER_COUNT": str(len(under)),
            "OVER_COUNT": str(len(over)),
            "AVG_MISS": trim_num(avg_miss, 1),
            "TOTAL_EST": trim_num(total_est, 2),
            "TOTAL_ACT": trim_num(total_act, 1),
            "ESTVACT_JSON": dumps(estvact),
            "VARIANCE_JSON": dumps(variance_out),
            "THREADS_JSON": dumps(threads_out),
        },
    )


def main():
    entries, slim_entries, pmap = load_time_log()
    build_time_stats(entries)
    build_time_detail(slim_entries, pmap)
    build_time_kantata(slim_entries, pmap)
    build_tasks()
    print(f"[{NOW.isoformat(timespec='seconds')}] generated time-stats.html, time-detail.html, time-kantata.html, tasks.html")


if __name__ == "__main__":
    main()
