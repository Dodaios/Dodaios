"""Put one node of each type into a demo instance, for the README's Nodes clip.

    JARVIS_DATA_DIR=/tmp/dodaios-demo/state/data \
    JARVIS_CONFIG=/tmp/dodaios-demo/state/dodaios.toml \
    HOME=/tmp/dodaios-demo/home python scripts/readme_demo/seed_nodes.py

Run it with the demo instance's environment (the paths demo-instance.sh
prints), so the nodes land where that instance reads them. The content is the
example each type ships with (``EXAMPLE`` in ``dodaios/nodes/kinds/*.py``),
written through the node store and checked by the same ``normalize`` as
everything the assistant writes. No model makes them. Prints "<type> <id>" per
node; the newest comes first in the library.
"""

from __future__ import annotations

import copy
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


def main() -> None:
    store = NodeStore()
    now = time.time()
    for type_name, title, spec, hours in NODES:
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
