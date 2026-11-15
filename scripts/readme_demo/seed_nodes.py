"""Put one node of each type into a demo instance, for the README's Nodes clips.

    JARVIS_DATA_DIR=/tmp/dodaios-demo/state/data \
    JARVIS_CONFIG=/tmp/dodaios-demo/state/dodaios.toml \
    HOME=/tmp/dodaios-demo/home python scripts/readme_demo/seed_nodes.py

Run it with the demo instance's environment (the paths demo-instance.sh
prints), so the nodes land where that instance reads them. The content is the
example each type ships with (``EXAMPLE`` in ``dodaios/nodes/kinds/*.py``),
written through the node store and checked by the same ``normalize`` as
everything the assistant writes. No model makes them. Prints "<type> <id>" per
node; the newest comes first in the library.

``--workspace`` seeds the library for the clip "a node created and edited"
(clip-nodes.cjs) instead: the same examples without the whiteboard, because
the assistant makes the whiteboard in that clip, and with a sheet that has
more to read ("Launch budget": six rows, an amount column with a formula and
a total, a chart).
"""

from __future__ import annotations

import copy
import sys
import time

from dodaios.nodes.kinds import data, design, docs, motion, sheets, slides, whiteboard
from dodaios.nodes.store import NodeStore

HOUR = 3600.0

# (type, title, content, hours ago)
NODES = [
    ("data", "Shop sales, October", data.EXAMPLE, 1.5),
    ("slides", "Q3 board update", slides.EXAMPLE, 5),
    ("docs", "Hosting plans compared", docs.EXAMPLE, 9),
    ("whiteboard", "Product launch plan", whiteboard.EXAMPLE, 20),
    ("sheets", "Office supplies, March", sheets.EXAMPLE, 27),
    ("design", "Summer concert poster", design.EXAMPLE, 34),
    ("motion", "Q3 in twenty seconds", motion.EXAMPLE, 49),
]

LAUNCH_BUDGET = {
    "note": "What the launch costs, by item",
    "sheets": [
        {
            "name": "Budget",
            "columns": [
                {"key": "item", "label": "Item", "width": 230},
                {"key": "qty", "label": "Qty", "type": "number"},
                {"key": "price", "label": "Price", "type": "currency", "unit": "EUR"},
                {
                    "key": "amount",
                    "label": "Amount",
                    "type": "currency",
                    "unit": "EUR",
                    "formula": "qty * price",
                    "total": "sum",
                },
            ],
            "rows": [
                {"item": "Landing page", "qty": 1, "price": 900},
                {"item": "Demo video", "qty": 1, "price": 650},
                {"item": "Newsletter sponsorship", "qty": 2, "price": 350},
                {"item": "Beta gift cards", "qty": 20, "price": 15},
                {"item": "Launch-day ads", "qty": 4, "price": 120},
                {"item": "Stickers", "qty": 200, "price": 0.6},
            ],
            "charts": [{"type": "column", "title": "Amount", "x": "item", "series": ["amount"]}],
        }
    ],
}

# The library of the clip "a node created and edited": no whiteboard yet.
WORKSPACE = [
    ("sheets", "Launch budget", LAUNCH_BUDGET, 2.5),
    ("slides", "Q3 board update", slides.EXAMPLE, 5),
    ("docs", "Hosting plans compared", docs.EXAMPLE, 22),
    ("data", "Shop sales, October", data.EXAMPLE, 27),
    ("design", "Summer concert poster", design.EXAMPLE, 49),
    ("motion", "Q3 in twenty seconds", motion.EXAMPLE, 75),
]


def main() -> None:
    store = NodeStore()
    now = time.time()
    for type_name, title, spec, hours in WORKSPACE if "--workspace" in sys.argv[1:] else NODES:
        node = store.create(
            type=type_name,
            title=title,
            spec=copy.deepcopy(spec),
            language="en",
            now=now - hours * HOUR,
        )
        print(type_name, node.id, flush=True)


if __name__ == "__main__":
    main()
