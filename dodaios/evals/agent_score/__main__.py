"""CLI: ``python -m dodaios.evals.agent_score [--db PATH] [--results-dir DIR] ...``

Read-only over the chat store; writes ``agent-score-<stamp>.json`` into the
results directory (default ``eval-results/``). Calls no model.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from pathlib import Path

from . import build_report, format_table, load_config


def _default_db() -> Path:
    from dodaios.core import config as cfg

    return Path(cfg.DATA_DIR) / "agent_chat.db"


def _preparation(since_ms: int) -> dict | None:
    """The prepared-in-advance counts, or ``None`` before anything was ever prepared."""
    from dodaios.core import config as cfg
    from dodaios.lead_triggers.prepared import PreparedStore

    path = Path(cfg.DATA_DIR) / "prepared_items.db"
    if not path.exists():
        return None
    store = PreparedStore(path)
    try:
        return store.stats(since_ms)
    finally:
        store.close()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m dodaios.evals.agent_score", description=__doc__)
    p.add_argument("--db", type=Path, help="agent_chat.db (default: the app data directory's)")
    p.add_argument(
        "--results-dir",
        type=Path,
        default=Path("eval-results"),
        help="routing eval results to read and the report to write",
    )
    p.add_argument("--config", type=Path, help="JSON file with importance / weight overrides")
    p.add_argument("--since-days", type=float, help="only turns from the last N days")
    p.add_argument("--json", action="store_true", help="print the JSON instead of the table")
    p.add_argument("--no-write", action="store_true", help="do not write the JSON report")
    args = p.parse_args(argv)

    with contextlib.suppress(Exception):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    cfg_path = args.config
    if cfg_path is None:
        from dodaios.core.paths import user_data_dir

        cfg_path = user_data_dir() / "agent_score.json"
    since = int((time.time() - args.since_days * 86400) * 1000) if args.since_days else 0
    from dodaios.trust.ask_log import ask_log
    from dodaios.trust.audit import audit_log

    report = build_report(
        args.db or _default_db(),
        args.results_dir,
        load_config(cfg_path),
        since_ms=since,
        audit=audit_log(),
        preparation=_preparation(since),
        asks=ask_log(),
    )
    print(json.dumps(report, indent=2) if args.json else format_table(report))
    if not args.no_write:
        args.results_dir.mkdir(parents=True, exist_ok=True)
        out = args.results_dir / f"agent-score-{time.strftime('%Y%m%d-%H%M%S')}.json"
        out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nreport written: {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
