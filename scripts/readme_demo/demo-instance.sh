#!/usr/bin/env bash
# Starts a throwaway first-run Dodaios instance for the README recording.
#
#   scripts/readme_demo/demo-instance.sh
#
# Everything it writes lives under DEMO_ROOT (default /tmp/dodaios-demo): its
# own home folder, data folder and config file, on its own port. It never
# touches the app you use. Each start wipes that state, so the app comes up
# with nothing set up, and puts two small sample projects into the home folder.
# DEMO_HOME moves that home folder elsewhere (a path that reads well in the
# picture, such as /home/demo); it is wiped at each start too.
# DEMO_KEEP=1 starts the instance again on the state it has, wiping nothing:
# copy DEMO_HOME and DEMO_ROOT/state away after the warm-up and back before
# each attempt, and a take that failed costs only the take.
# DEMO_PR_REPO=owner/name adds a third project: a clone of that GitHub
# repository, whose open pull requests the agents clip has reviewed
# (agents.cjs). It needs the GitHub CLI signed in to an account that can read
# the repository; the instance gets that login as GH_TOKEN.
#
# Needs a Python environment with Dodaios, ptyprocess (the terminal) and pytest
# (the sample projects' tests), and a built frontend bundle (npm run build in
# dodaios/ui/web/frontend). Choose the interpreter with PYTHON.
# The recording talks to a real model through Claude Code, which must be
# installed and signed in. The instance runs with HOME=DEMO_HOME, so on Linux
# pass the login as CLAUDE_CODE_OAUTH_TOKEN (from `claude setup-token`); the
# environment reaches Claude Code unchanged. macOS keeps the login in the
# Keychain, which the script links into DEMO_HOME.
# Run it as a normal user: as root the app shows an administrator notice.
set -eu

DEMO_ROOT="${DEMO_ROOT:-/tmp/dodaios-demo}"
DEMO_PORT="${DEMO_PORT:-47990}"
PYTHON="${PYTHON:-python}"
REPO="$(cd "$(dirname "$0")/../.." && pwd)"

if [ -z "$DEMO_ROOT" ] || [ "$DEMO_ROOT" = "/" ]; then
  echo "DEMO_ROOT must name a folder of its own" >&2
  exit 2
fi
if [ "$(id -u)" = "0" ]; then
  echo "warning: running as root, the app will show an administrator notice" >&2
fi

DEMO_HOME="${DEMO_HOME:-$DEMO_ROOT/home}"
DEMO_STATE="$DEMO_ROOT/state"
case "$DEMO_HOME" in
  ""|"/"|"${HOME:-/nonexistent}")
    echo "DEMO_HOME must name a folder of its own, not your home folder" >&2
    exit 2
    ;;
esac
PROJECT="$DEMO_HOME/projects/trailhead"

if [ -n "${DEMO_KEEP:-}" ] && [ ! -d "$DEMO_STATE/data" ]; then
  echo "DEMO_KEEP is set, but there is no instance under $DEMO_ROOT to keep" >&2
  exit 2
fi
if [ -z "${DEMO_KEEP:-}" ]; then
rm -rf "$DEMO_HOME" "$DEMO_STATE"
mkdir -p "$DEMO_STATE/data" "$PROJECT/src" "$PROJECT/tests"

# The config is the example one, with the data folder moved under DEMO_ROOT.
sed "s#^data_dir = \"./data\".*#data_dir = \"$DEMO_STATE/data\"#" \
  "$REPO/dodaios.toml.example" > "$DEMO_STATE/dodaios.toml"

# --- the sample project: a tiny hike planner with four tests -----------------
cat > "$PROJECT/README.md" <<'EOF'
# trailhead

A tiny command-line planner for day hikes: distance, climb and a pace estimate.

    python -m src.trailhead plan --distance 14.5 --climb 820

## Tests

    python -m pytest -q
EOF

cat > "$PROJECT/src/trailhead.py" <<'EOF'
"""Estimate how long a day hike takes."""
from __future__ import annotations

import argparse

FLAT_KMH = 4.5          # walking pace on level ground
CLIMB_M_PER_HOUR = 400  # extra time for every 400 m of ascent


def estimate_hours(distance_km: float, climb_m: float) -> float:
    """Naismith-style estimate: flat time plus time for the climb."""
    if distance_km < 0 or climb_m < 0:
        raise ValueError("distance and climb must not be negative")
    return distance_km / FLAT_KMH + climb_m / CLIMB_M_PER_HOUR


def format_plan(distance_km: float, climb_m: float) -> str:
    hours = estimate_hours(distance_km, climb_m)
    whole, minutes = int(hours), round((hours - int(hours)) * 60)
    return f"{distance_km:g} km, {climb_m:g} m up: about {whole} h {minutes:02d} min"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="trailhead")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan", help="estimate a hike")
    plan.add_argument("--distance", type=float, required=True, help="kilometres")
    plan.add_argument("--climb", type=float, default=0.0, help="metres of ascent")
    args = parser.parse_args(argv)
    print(format_plan(args.distance, args.climb))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF

cat > "$PROJECT/tests/test_trailhead.py" <<'EOF'
import pytest

from src.trailhead import estimate_hours, format_plan


def test_flat_walk_uses_the_walking_pace():
    assert estimate_hours(9, 0) == pytest.approx(2.0)


def test_climb_adds_time():
    assert estimate_hours(9, 400) == pytest.approx(3.0)


def test_negative_values_are_rejected():
    with pytest.raises(ValueError):
        estimate_hours(-1, 0)


def test_plan_is_readable():
    assert format_plan(14.5, 820) == "14.5 km, 820 m up: about 5 h 16 min"
EOF

: > "$PROJECT/src/__init__.py"
: > "$PROJECT/tests/__init__.py"
printf '__pycache__/\n.pytest_cache/\n' > "$PROJECT/.gitignore"

(
  cd "$PROJECT"
  git init -q -b main
  git -c user.name="Demo" -c user.email="demo@example.com" add -A
  git -c user.name="Demo" -c user.email="demo@example.com" commit -q \
    -m "Estimate hike time from distance and climb, with tests"
)

# --- the second project: a small invoicing library, with a history -------------
# Its VAT is rounded per line although docs/rounding.md asks for one rounding
# of the net total, so three of the nine invoices come out a cent too high.
# The recording has that found and fixed. The tests pass as it stands.
LEDGER="$DEMO_HOME/projects/ledger"
mkdir -p "$LEDGER/ledger" "$LEDGER/tests" "$LEDGER/data" "$LEDGER/docs"
ledger_commit() {  # <days ago> <message>: commit everything, dated in the past
  when="$("$PYTHON" -c "import datetime, sys; print((datetime.datetime.now().astimezone() - datetime.timedelta(days=int(sys.argv[1]), hours=3)).replace(microsecond=0).isoformat())" "$1")"
  (
    cd "$LEDGER"
    git add -A
    GIT_AUTHOR_DATE="$when" GIT_COMMITTER_DATE="$when" \
      git -c user.name="Demo" -c user.email="demo@example.com" commit -q -m "$2"
  )
}
(cd "$LEDGER" && git init -q -b main)
printf '__pycache__/\n.pytest_cache/\n' > "$LEDGER/.gitignore"

cat > "$LEDGER/README.md" <<'EOF'
# ledger

Invoices for the subscription business: line items, VAT and totals, read from
`data/invoices.json`.

    python -m ledger list
    python -m ledger show INV-2041

How amounts are rounded is written down in `docs/rounding.md`.

## Tests

    python -m pytest -q
EOF

cat > "$LEDGER/ledger/__init__.py" <<'EOF'
"""Invoices: line items, VAT and totals."""
EOF

cat > "$LEDGER/ledger/money.py" <<'EOF'
"""Money is a Decimal in euros. Nothing here uses a float."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")


def to_cents(amount: Decimal) -> Decimal:
    """Round half up to the cent, the way an invoice prints it."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def euros(amount: Decimal) -> str:
    return f"{to_cents(amount):,.2f} EUR"
EOF

cat > "$LEDGER/ledger/invoice.py" <<'EOF'
"""An invoice and the amounts on it."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .money import to_cents


@dataclass(frozen=True)
class Line:
    description: str
    quantity: int
    unit_price: Decimal

    @property
    def net(self) -> Decimal:
        return to_cents(self.quantity * self.unit_price)


@dataclass(frozen=True)
class Invoice:
    number: str
    customer: str
    vat_rate: Decimal
    lines: tuple[Line, ...]

    @property
    def net(self) -> Decimal:
        return sum((line.net for line in self.lines), Decimal("0"))

    @property
    def vat(self) -> Decimal:
        return sum((to_cents(line.net * self.vat_rate) for line in self.lines), Decimal("0"))

    @property
    def total(self) -> Decimal:
        return self.net + self.vat
EOF
ledger_commit 24 "Invoices with line items, VAT and totals"

cat > "$LEDGER/ledger/store.py" <<'EOF'
"""Read invoices from the JSON file the billing export writes."""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .invoice import Invoice, Line

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "invoices.json"


def load(path: Path = DEFAULT_PATH) -> dict[str, Invoice]:
    invoices = {}
    for row in json.loads(path.read_text(encoding="utf-8")):
        lines = tuple(
            Line(item["description"], int(item["quantity"]), Decimal(item["unit_price"]))
            for item in row["lines"]
        )
        invoices[row["number"]] = Invoice(
            row["number"], row["customer"], Decimal(row["vat_rate"]), lines
        )
    return invoices
EOF

cat > "$LEDGER/data/invoices.json" <<'EOF'
[
  {"number": "INV-2038", "customer": "Nordlicht Studio", "vat_rate": "0.19", "lines": [
    {"description": "Team plan, monthly", "quantity": 1, "unit_price": "49.00"}]},
  {"number": "INV-2039", "customer": "Harbor & Pine", "vat_rate": "0.19", "lines": [
    {"description": "Extra seat", "quantity": 5, "unit_price": "9.50"},
    {"description": "Storage add-on", "quantity": 1, "unit_price": "19.00"}]},
  {"number": "INV-2040", "customer": "Kestrel Logistics", "vat_rate": "0.19", "lines": [
    {"description": "Business plan, monthly", "quantity": 1, "unit_price": "149.00"},
    {"description": "Audit log add-on", "quantity": 2, "unit_price": "19.50"}]},
  {"number": "INV-2041", "customer": "Brightwell Dental", "vat_rate": "0.19", "lines": [
    {"description": "Team plan, monthly", "quantity": 1, "unit_price": "49.50"},
    {"description": "Audit log add-on", "quantity": 1, "unit_price": "19.50"},
    {"description": "Extra seat", "quantity": 1, "unit_price": "9.50"}]},
  {"number": "INV-2042", "customer": "Fernhill Bakery", "vat_rate": "0.19", "lines": [
    {"description": "Extra seat", "quantity": 12, "unit_price": "9.50"}]},
  {"number": "INV-2043", "customer": "Atlas Surveying", "vat_rate": "0.19", "lines": [
    {"description": "Team plan, monthly", "quantity": 1, "unit_price": "49.50"},
    {"description": "Extra seat", "quantity": 3, "unit_price": "9.50"},
    {"description": "SMS notifications", "quantity": 1, "unit_price": "4.50"}]},
  {"number": "INV-2044", "customer": "Juniper Health", "vat_rate": "0.19", "lines": [
    {"description": "Business plan, monthly", "quantity": 1, "unit_price": "149.00"},
    {"description": "Storage add-on", "quantity": 1, "unit_price": "19.00"},
    {"description": "Extra seat", "quantity": 4, "unit_price": "9.00"}]},
  {"number": "INV-2045", "customer": "Lumen Architects", "vat_rate": "0.19", "lines": [
    {"description": "Team plan, monthly", "quantity": 2, "unit_price": "49.50"},
    {"description": "Audit log add-on", "quantity": 1, "unit_price": "19.50"},
    {"description": "Priority support", "quantity": 1, "unit_price": "24.50"}]},
  {"number": "INV-2046", "customer": "Marrow & Finch", "vat_rate": "0.19", "lines": [
    {"description": "Team plan, monthly", "quantity": 1, "unit_price": "49.00"},
    {"description": "SMS notifications", "quantity": 1, "unit_price": "7.90"},
    {"description": "Custom domain", "quantity": 1, "unit_price": "3.90"}]}
]
EOF
ledger_commit 17 "Read invoices from the billing export"

cat > "$LEDGER/ledger/__main__.py" <<'EOF'
"""Command line: python -m ledger list | show <number>."""
from __future__ import annotations

import argparse

from .money import euros
from .store import load


def show(number: str) -> str:
    invoice = load()[number]
    rows = [f"{invoice.number}  {invoice.customer}", ""]
    for line in invoice.lines:
        rows.append(f"  {line.quantity:>3} x {line.description:<24} {euros(line.net):>14}")
    rows += [
        "",
        f"  {'Net':<30} {euros(invoice.net):>14}",
        f"  {'VAT ' + format(invoice.vat_rate, '.0%'):<30} {euros(invoice.vat):>14}",
        f"  {'Total':<30} {euros(invoice.total):>14}",
    ]
    return "\n".join(rows)


def listing() -> str:
    return "\n".join(
        f"{invoice.number}  {invoice.customer:<20} {euros(invoice.total):>14}"
        for invoice in load().values()
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="every invoice with its total")
    one = sub.add_parser("show", help="one invoice, line by line")
    one.add_argument("number")
    args = parser.parse_args(argv)
    print(listing() if args.command == "list" else show(args.number))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
EOF
ledger_commit 11 "Add the list and show commands"

cat > "$LEDGER/docs/rounding.md" <<'EOF'
# Rounding

Amounts are euros with two decimals.

- A line's net amount is quantity times unit price, rounded half up to the cent.
- VAT is calculated once, on the invoice's net total, and rounded half up to
  the cent. It is never rounded line by line: the half cents would add up.
- The total is the net total plus that VAT.

Our accounting system and the customers' follow the same rule, so an invoice
that rounds differently does not reconcile.
EOF

cat > "$LEDGER/tests/__init__.py" <<'EOF'
EOF

cat > "$LEDGER/tests/test_invoice.py" <<'EOF'
from decimal import Decimal

from ledger.invoice import Invoice, Line
from ledger.money import euros, to_cents
from ledger.store import load


def invoice(*lines: Line) -> Invoice:
    return Invoice("INV-1", "Test customer", Decimal("0.19"), lines)


def test_half_a_cent_rounds_up():
    assert to_cents(Decimal("2.345")) == Decimal("2.35")


def test_line_net_is_quantity_times_price():
    assert Line("Extra seat", 5, Decimal("9.50")).net == Decimal("47.50")


def test_single_line_invoice():
    one = invoice(Line("Team plan, monthly", 1, Decimal("49.00")))
    assert (one.net, one.vat, one.total) == (Decimal("49.00"), Decimal("9.31"), Decimal("58.31"))


def test_net_adds_the_lines():
    two = invoice(Line("Extra seat", 5, Decimal("9.50")), Line("Storage add-on", 1, Decimal("19.00")))
    assert two.net == Decimal("66.50")


def test_amounts_print_with_two_decimals():
    assert euros(Decimal("1234.5")) == "1,234.50 EUR"


def test_the_export_loads():
    invoices = load()
    assert len(invoices) == 9
    assert invoices["INV-2038"].customer == "Nordlicht Studio"
EOF
ledger_commit 6 "Write down the rounding rule, test the amounts"

cat >> "$LEDGER/README.md" <<'EOF'

## Month end

The billing export replaces `data/invoices.json` on the first of the month.
Run `python -m ledger list` and compare the totals with accounting before the
invoices go out.
EOF
ledger_commit 2 "Describe the month-end check"

# --- the third project: a repository with open pull requests -------------------
# Only with DEMO_PR_REPO. The clone is made with your own login, before the
# instance gets its own home folder.
if [ -n "${DEMO_PR_REPO:-}" ]; then
  PR_PROJECT="$DEMO_HOME/projects/${DEMO_PR_REPO##*/}"
  git clone -q "https://github.com/$DEMO_PR_REPO.git" "$PR_PROJECT"
  git -C "$PR_PROJECT" config user.name "Demo"
  git -C "$PR_PROJECT" config user.email "demo@example.com"
fi

fi   # DEMO_KEEP

# --- the instance --------------------------------------------------------------
if [ "$(uname)" = "Darwin" ]; then
  # Claude Code keeps its login in the login keychain, which macOS looks up
  # under the home folder: without this link it says "Not logged in".
  mkdir -p "$DEMO_HOME/Library"
  [ -e "$DEMO_HOME/Library/Keychains" ] || ln -s "$HOME/Library/Keychains" "$DEMO_HOME/Library/Keychains"
fi
# The instance keeps its own keys in a file under its data folder. Without
# this it would read and write the keys of the app you use (one Keychain item).
export PYTHON_KEYRING_BACKEND="keyring.backends.fail.Keyring"
# Background work (an artifact is built by a worker) runs on the Claude plan
# too. The example config names Gemini, which this instance has no key for.
export JARVIS__BRAIN__WORKER__PROVIDER="claude-api"
# The sample projects' tests need no pytest plugin. Whatever the Python
# environment has installed would only add its warnings to an agent's output.
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
# With a pull-request project the agents use the GitHub CLI. It keeps its
# login under the home folder, which the instance replaces: hand the token
# over in the environment and let git ask the CLI for it.
if [ -n "${DEMO_PR_REPO:-}" ]; then
  export GH_TOKEN="${GH_TOKEN:-$(gh auth token)}"
  export GH_PROMPT_DISABLED=1
  [ -e "$DEMO_HOME/.gitconfig" ] || printf '[credential "https://github.com"]\n\thelper =\n\thelper = !gh auth git-credential\n' > "$DEMO_HOME/.gitconfig"
fi
cd "$DEMO_HOME"
export HOME="$DEMO_HOME"
export JARVIS_DATA_DIR="$DEMO_STATE/data"
export JARVIS_CONFIG="$DEMO_STATE/dodaios.toml"
export PATH="$(dirname "$(command -v "$PYTHON")"):$PATH"

echo "demo instance: http://127.0.0.1:$DEMO_PORT/  (state in $DEMO_ROOT)"
exec "$PYTHON" -m dodaios.ui.web.launcher --headless --no-lock --port "$DEMO_PORT"
