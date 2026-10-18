"""Static isolation checks: the research package has no network, credential, order or app-wiring
path.
"""

import ast
import pathlib

import jarvis.trading_research as pkg

ROOT = pathlib.Path(pkg.__file__).parent
FORBIDDEN_IMPORTS = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "requests",
    "httpx",
    "aiohttp",
    "websockets",
    "subprocess",
    "keyring",
}
FORBIDDEN_TEXT = (
    "place_order",
    "cancel_order",
    "/trade/",
    "/order",
    "api_key",
    "secret",
    "get_secret",
)


def modules():
    return sorted(ROOT.glob("*.py"))


def test_no_network_or_process_imports_and_no_app_imports():
    for p in modules():
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for n in names:
                assert n.split(".")[0] not in FORBIDDEN_IMPORTS, f"{p.name} imports {n}"
                assert not n.startswith("jarvis"), f"{p.name} imports app code {n}"


def test_no_order_or_credential_strings():
    for p in modules():
        text = p.read_text(encoding="utf-8").lower()
        for s in FORBIDDEN_TEXT:
            assert s not in text, f"{p.name} contains {s!r}"


def test_nothing_in_the_app_imports_the_research_package():
    app = ROOT.parent
    for p in app.rglob("*.py"):
        if ROOT in p.parents or p.parent == ROOT:
            continue
        assert "trading_research" not in p.read_text(encoding="utf-8", errors="replace"), (
            f"{p} wires the research package"
        )
