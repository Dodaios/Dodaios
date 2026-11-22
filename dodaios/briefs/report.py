"""What the record of orders says: ``python -m dodaios.briefs.report``.

Reads ``briefs.db`` and prints how briefs fared: how many were written, how
many the check sent back and for what, what the agents received, how their
runs ended and how the done-when points held. It also sets the two against
each other, which is the question the record exists for: do orders whose first
draft was clean end better than those that had to be revised?

Reads only, asks no model, writes nothing. With few orders on record the
shares are small numbers and say little; the counts are printed beside them.

    python -m dodaios.briefs.report                 # the last 30 days
    python -m dodaios.briefs.report --since-days 7
    python -m dodaios.briefs.report --json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from typing import Any

from dodaios.briefs import log as log_module

__all__ = ["build", "main", "render"]


def _loads(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except ValueError:  # an unreadable cell counts as empty
        return []
    return parsed if isinstance(parsed, list) else []


def _share(part: int, whole: int) -> str:
    return f"{part} of {whole}" + (f" ({round(100 * part / whole)} %)" if whole else "")


def _held(delivery: dict[str, Any]) -> str:
    """How a delivery's done-when points fared: ``all``, ``some``, ``against`` or ``none``."""
    points = [p for p in _loads(delivery.get("acceptance")) if isinstance(p, dict)]
    if not points:
        return "none"
    verdicts = [str(p.get("verdict") or "") for p in points]
    if "contradicted" in verdicts:
        return "against"
    return "all" if all(v == "confirmed" for v in verdicts) else "some"


def build(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """The report's numbers from the record's rows (orders with their deliveries)."""
    orders = len(rows)
    sent = [row for row in rows if row.get("sent_ms")]
    sent_back = [row for row in rows if row.get("sent_back")]
    first_findings: Counter[str] = Counter()
    left_findings: Counter[str] = Counter()
    for row in rows:
        for finding in _loads(row.get("first_findings")):
            if isinstance(finding, dict) and finding.get("severity") == "revise":
                first_findings[str(finding.get("code") or "")] += 1
        if row.get("sent_ms"):
            for finding in _loads(row.get("findings_json")):
                if isinstance(finding, dict) and finding.get("severity") == "revise":
                    left_findings[str(finding.get("code") or "")] += 1
    deliveries = [d for row in rows for d in row.get("deliveries") or []]
    ended = [d for d in deliveries if d.get("outcome")]
    # Done-when points are judged for a run that reported it was done; a run
    # that failed or was stopped claims nothing.
    held = Counter(_held(d) for d in ended if d.get("outcome") == "completed")
    by_first: dict[str, Counter[str]] = {"clean": Counter(), "revised": Counter()}
    for row in rows:
        group = "revised" if row.get("sent_back") else "clean"
        for delivery in row.get("deliveries") or []:
            if delivery.get("outcome") == "completed":
                by_first[group][_held(delivery)] += 1
    return {
        "orders": orders,
        "sent": len(sent),
        "sent_back_once": len(sent_back),
        "prepared_first": sum(1 for row in rows if row.get("prepared")),
        "by_writer": dict(Counter(str(row.get("writer") or "") for row in rows)),
        "by_kind": dict(Counter(str(row.get("kind") or "") for row in rows)),
        "found_in_first_draft": dict(first_findings.most_common()),
        "still_found_when_sent": dict(left_findings.most_common()),
        "deliveries": len(deliveries),
        "by_family": dict(Counter(str(d.get("family") or "") for d in deliveries)),
        "by_effort": dict(Counter(
            f"{d.get('effort') or 'default'} ({d.get('effort_source') or 'default'})"
            for d in deliveries
        )),
        "ended": len(ended),
        "by_outcome": dict(Counter(str(d.get("outcome") or "") for d in ended)),
        "done_when": dict(held),
        "questions_asked": sum(int(d.get("questions") or 0) for d in deliveries),
        "done_when_by_first_draft": {k: dict(v) for k, v in by_first.items()},
    }


def render(report: dict[str, Any], *, days: int) -> str:
    """The report as text for a terminal."""
    orders = report["orders"]
    lines = [
        f"Briefs for coding agents, last {days} days",
        "",
        f"Orders written:            {orders}",
        f"  sent:                    {_share(report['sent'], orders)}",
        f"  sent back once:          {_share(report['sent_back_once'], orders)}",
        f"  looked up before written: {_share(report['prepared_first'], orders)}",
        f"  by writer:               {report['by_writer']}",
        f"  by kind of work:         {report['by_kind']}",
    ]
    if report["found_in_first_draft"]:
        lines += ["", "What the check found in first drafts:"]
        lines += [f"  {code}: {count}" for code, count in report["found_in_first_draft"].items()]
    if report["still_found_when_sent"]:
        lines += ["", "Still found in briefs that were sent:"]
        lines += [f"  {code}: {count}" for code, count in report["still_found_when_sent"].items()]
    lines += [
        "",
        f"Deliveries (one per agent): {report['deliveries']}",
        f"  by model family:         {report['by_family']}",
        f"  by effort:               {report['by_effort']}",
        f"  runs that ended:         {_share(report['ended'], report['deliveries'])}",
        f"  how they ended:          {report['by_outcome']}",
        f"  questions the agents asked: {report['questions_asked']}",
    ]
    held = report["done_when"]
    if held:
        lines += [
            "",
            "Done-when points of runs that reported done "
            "(all confirmed / some open / contradicted / none named):",
            f"  {held.get('all', 0)} / {held.get('some', 0)} / {held.get('against', 0)} "
            f"/ {held.get('none', 0)}",
        ]
        for group, label in (("clean", "first draft clean"), ("revised", "first draft sent back")):
            counts = report["done_when_by_first_draft"].get(group) or {}
            total = sum(counts.values())
            lines.append(f"  {label}: all confirmed in {_share(counts.get('all', 0), total)}")
    if not orders:
        lines += ["", "No order is on record for this period."]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m dodaios.briefs.report",
        description="How briefs for coding agents fared, from the record of orders.",
    )
    parser.add_argument("--since-days", type=int, default=30, help="how far back to read")
    parser.add_argument("--json", action="store_true", help="print the numbers as JSON")
    args = parser.parse_args(argv)
    store = log_module.get_log()
    if store is None:
        print("The record of orders could not be opened.", file=sys.stderr)
        return 1
    since_ms = int((time.time() - max(1, args.since_days) * 86_400) * 1000)
    report = build(store.rows(since_ms=since_ms))
    print(json.dumps(report, ensure_ascii=False, indent=1) if args.json
          else render(report, days=args.since_days))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
