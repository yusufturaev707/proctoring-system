"""
Bosqich bo'yicha hisobot: `<prefix>_by_stage_*.json` (har Locust jarayoni
o'zinikini yozadi) -> `<prefix>_stages.csv` + `<prefix>_stages.html`.

    python tools/stage_report.py results/local_run1/lt

Har (bosqich, so'rov) uchun: soni, xato %, RPS (bosqich ichidagi birinchi
va oxirgi so'rov oralig'i bo'yicha), p50/p95/p99 (ms), o'rtacha javob
hajmi. Oxirida har bosqichning JAMI qatori va SLO belgisi:

    xato < 0.1%;  login va candidate/lookup p95 < 2000 ms;
    heartbeat va boshqa kichik so'rovlar p95 < 500 ms.
"""

from __future__ import annotations

import csv
import glob
import html
import json
import sys
from collections import defaultdict

SLO_LOGIN = ("auth/login", "client/candidate/lookup")
SLO_SMALL = ("client/heartbeat", "client/presence", "client/events", "client/preflight",
             "client/exam/access", "client/identity/confirm", "client/session/finish")


def percentile(hist: dict, q: float) -> int:
    total = sum(hist.values())
    if not total:
        return 0
    target = total * q
    run = 0
    for value in sorted(hist):
        run += hist[value]
        if run >= target:
            return value
    return max(hist)


def main(prefix: str) -> None:
    merged = defaultdict(lambda: {"count": 0, "fail": 0, "bytes": 0, "rt": defaultdict(int),
                                  "first": float("inf"), "last": 0.0})
    for path in glob.glob(f"{prefix}_by_stage_*.json"):
        data = json.load(open(path, encoding="utf-8"))
        for row in data["rows"]:
            m = merged[(row["phase"], row["type"], row["name"])]
            m["count"] += row["count"]
            m["fail"] += row["fail"]
            m["bytes"] += row["bytes"]
            m["first"] = min(m["first"], row["first"])
            m["last"] = max(m["last"], row["last"])
            for k, c in row["rt"].items():
                m["rt"][int(k)] += c
    if not merged:
        sys.exit(f"{prefix}_by_stage_*.json topilmadi")

    phases = defaultdict(lambda: {"count": 0, "fail": 0, "rt": defaultdict(int), "first": float("inf"), "last": 0.0})
    rows = []
    for (phase, rtype, name), m in sorted(merged.items()):
        span = max(1.0, m["last"] - m["first"])
        rows.append({
            "phase": phase, "type": rtype, "name": name, "count": m["count"],
            "error_pct": round(100.0 * m["fail"] / m["count"], 3),
            "rps": round(m["count"] / span, 2),
            "p50_ms": percentile(m["rt"], 0.50), "p95_ms": percentile(m["rt"], 0.95),
            "p99_ms": percentile(m["rt"], 0.99),
            "avg_bytes": int(m["bytes"] / m["count"]),
        })
        p = phases[phase]
        p["count"] += m["count"]
        p["fail"] += m["fail"]
        p["first"] = min(p["first"], m["first"])
        p["last"] = max(p["last"], m["last"])
        for k, c in m["rt"].items():
            p["rt"][k] += c
    for phase, p in sorted(phases.items()):
        span = max(1.0, p["last"] - p["first"])
        rows.append({
            "phase": phase, "type": "*", "name": "JAMI", "count": p["count"],
            "error_pct": round(100.0 * p["fail"] / p["count"], 3), "rps": round(p["count"] / span, 2),
            "p50_ms": percentile(p["rt"], 0.5), "p95_ms": percentile(p["rt"], 0.95),
            "p99_ms": percentile(p["rt"], 0.99), "avg_bytes": 0,
        })

    for row in rows:
        verdict = ""
        if row["name"] == "JAMI":
            verdict = "OK" if row["error_pct"] < 0.1 else "XATO>0.1%"
        elif row["name"] in SLO_LOGIN:
            verdict = "OK" if row["p95_ms"] < 2000 else "p95>2s"
        elif row["name"] in SLO_SMALL:
            verdict = "OK" if row["p95_ms"] < 500 else "p95>500ms"
        row["slo"] = verdict

    fields = list(rows[0].keys())
    with open(f"{prefix}_stages.csv", "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(r[f]))}</td>" for f in fields) + "</tr>" for r in rows
    )
    head = "".join(f"<th>{f}</th>" for f in fields)
    with open(f"{prefix}_stages.html", "w", encoding="utf-8") as fh:
        fh.write(
            "<!doctype html><meta charset='utf-8'><title>Bosqichlar hisoboti</title>"
            "<style>body{font:13px system-ui;margin:16px}table{border-collapse:collapse}"
            "td,th{border:1px solid #ccc;padding:3px 6px;text-align:right}td:nth-child(-n+3){text-align:left}"
            "</style><h1>Bosqichlar bo'yicha natija</h1>"
            f"<table><tr>{head}</tr>{body}</table>"
        )
    width = max(len(r["name"]) for r in rows)
    print(f"{'phase':<12} {'name':<{width}} {'count':>7} {'err%':>6} {'rps':>7} {'p50':>6} {'p95':>6} {'p99':>6}  slo")
    for r in rows:
        print(f"{r['phase']:<12} {r['name']:<{width}} {r['count']:>7} {r['error_pct']:>6} {r['rps']:>7} "
              f"{r['p50_ms']:>6} {r['p95_ms']:>6} {r['p99_ms']:>6}  {r['slo']}")
    print(f"\n-> {prefix}_stages.csv, {prefix}_stages.html")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "results/lt")
