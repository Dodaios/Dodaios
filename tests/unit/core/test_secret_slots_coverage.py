"""Every credential the package saves has a name ``dodaios.core.secret_slots`` knows.

The one-time copy to the renamed credential service and the uninstaller can
only visit names they can list. This file reads every ``set_secret(...)`` and
``set_password(...)`` call in ``dodaios/``: a key spelled as a literal or a
module constant must be in ``KNOWN_SECRET_KEYS``, and a key computed at
runtime must come from a module listed in ``DYNAMIC_SLOT_SOURCES``. A new
credential slot therefore cannot ship without saying how it is found again.
"""

from __future__ import annotations

import ast
import functools
import importlib.util
import warnings
from dataclasses import dataclass
from pathlib import Path

import pytest

from dodaios.core.secret_slots import DYNAMIC_SLOT_SOURCES, KNOWN_SECRET_KEYS

_ROOT = Path(__file__).resolve().parents[3]
_PACKAGE = _ROOT / "dodaios"

# Modules that implement a credential store: they receive the key as a
# parameter from the callers checked below, or keep a store of their own.
_STORE_IMPLEMENTATIONS = {
    "dodaios.core.config": "set_secret itself and the backend probe",
    "dodaios.core.keychain_bundle": "the macOS vault wrapper",
    "dodaios.core.identity_migration": "the copy engine, keys come from secret_slots",
    "dodaios.core.identity_credentials": "runs the copy over secret_slots' names",
    "dodaios.board.sync": "its own service (jarvis-board), outside the renamed one",
}


@dataclass(frozen=True)
class SecretWrite:
    module: str
    line: int
    # The literal name, or None when it is computed at runtime.
    name: str | None
    expression: str


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(_ROOT).with_suffix("").parts)


def _top_level_strings(tree: ast.Module) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets = [node.target]
        value = getattr(node, "value", None)
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            for target in targets:
                if isinstance(target, ast.Name):
                    found[target.id] = value.value
    return found


def _imported_names(tree: ast.AST, module: str) -> dict[str, tuple[str, str]]:
    """``local name -> (module, name)`` for every ``from x import y`` in the file."""
    found: dict[str, tuple[str, str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        origin = node.module or ""
        if node.level:
            package = module.split(".")[: -node.level]
            origin = ".".join([*package, origin] if origin else package)
        for alias in node.names:
            found[alias.asname or alias.name] = (origin, alias.name)
    return found


def _parse(source: str) -> ast.Module:
    with warnings.catch_warnings():
        # A stray escape in some docstring is not this test's business.
        warnings.simplefilter("ignore", DeprecationWarning)
        warnings.simplefilter("ignore", SyntaxWarning)
        return ast.parse(source)


def _module_strings(module: str) -> dict[str, str]:
    path = _ROOT.joinpath(*module.split(".")).with_suffix(".py")
    if not path.is_file():
        path = _ROOT.joinpath(*module.split("."), "__init__.py")
    if not path.is_file():
        return {}
    return _top_level_strings(_parse(path.read_text(encoding="utf-8-sig")))


def _callee(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _key_argument(call: ast.Call) -> ast.expr | None:
    """The key a credential write names, if this call is one."""
    callee = _callee(call.func)
    if callee == "set_secret" and call.args:
        return call.args[0]
    if callee == "set_password" and len(call.args) >= 2:
        return call.args[1]
    # ``asyncio.to_thread(set_secret, key, value)`` and the like.
    for index, argument in enumerate(call.args[:-1]):
        if _callee(argument) == "set_secret":
            return call.args[index + 1]
    return None


def secret_writes(source: str, module: str) -> list[SecretWrite]:
    tree = _parse(source)
    constants = _top_level_strings(tree)
    imports = _imported_names(tree, module)
    writes: list[SecretWrite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        key = _key_argument(node)
        if key is None:
            continue
        name: str | None = None
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            name = key.value
        elif isinstance(key, ast.Name) and key.id in constants:
            name = constants[key.id]
        elif isinstance(key, ast.Name) and key.id in imports:
            origin, original = imports[key.id]
            name = _module_strings(origin).get(original)
        writes.append(SecretWrite(module, node.lineno, name, ast.unparse(key)))
    return writes


@functools.cache
def _shipped_modules() -> tuple[tuple[str, str], ...]:
    files = [
        path
        for path in _PACKAGE.rglob("*.py")
        if "node_modules" not in path.parts and "frontend" not in path.parts
    ]
    return tuple((_module_name(path), path.read_text(encoding="utf-8-sig")) for path in files)


def _all_writes() -> list[SecretWrite]:
    writes: list[SecretWrite] = []
    for module, source in _shipped_modules():
        if module in _STORE_IMPLEMENTATIONS:
            continue
        writes.extend(secret_writes(source, module))
    return writes


def _offenders(writes: list[SecretWrite]) -> list[str]:
    offenders: list[str] = []
    for write in writes:
        if write.name is not None:
            if write.name not in KNOWN_SECRET_KEYS:
                offenders.append(
                    f"{write.module}:{write.line}: {write.name!r} is not in KNOWN_SECRET_KEYS"
                )
        elif write.module not in DYNAMIC_SLOT_SOURCES:
            offenders.append(
                f"{write.module}:{write.line}: computed key {write.expression!r}, "
                "but the module is not in DYNAMIC_SLOT_SOURCES"
            )
    return offenders


def test_every_saved_credential_name_can_be_found_again() -> None:
    writes = _all_writes()
    # The scan sees the package: fixed names and computed ones alike.
    assert len([w for w in writes if w.name is not None]) >= 6
    assert len([w for w in writes if w.name is None]) >= 10
    assert _offenders(writes) == [], (
        "list the name in dodaios/core/secret_slots.py:\n" + "\n".join(_offenders(writes))
    )


def test_every_fixed_name_is_still_saved_or_read_somewhere() -> None:
    # A name nothing spells any more is dead weight in the copy and the
    # uninstaller; it should leave the table with its last user.
    sources = "\n".join(source for _module, source in _shipped_modules())
    for name in KNOWN_SECRET_KEYS:
        assert f'"{name}"' in sources, name


@pytest.mark.parametrize("module", sorted(DYNAMIC_SLOT_SOURCES))
def test_every_dynamic_source_is_a_real_module(module: str) -> None:
    assert importlib.util.find_spec(module) is not None, module


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ('set_secret("brand_new_slot", value)\n', ["'brand_new_slot' is not in KNOWN"]),
        ('SLOT = "brand_new_slot"\nset_secret(SLOT, value)\n', ["'brand_new_slot' is not in"]),
        ('keyring.set_password(SERVICE, f"x_{item}", value)\n', ["computed key"]),
        ("asyncio.to_thread(set_secret, make_slot(row), value)\n", ["computed key"]),
        ('set_secret("telegram_bot_token", value)\n', []),
    ],
)
def test_the_scan_has_teeth(source: str, expected: list[str]) -> None:
    found = _offenders(secret_writes(source, "dodaios.some_new_module"))
    assert len(found) == len(expected)
    for message, fragment in zip(found, expected, strict=True):
        assert fragment in message
