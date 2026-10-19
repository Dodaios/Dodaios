"""The wake runtime loads without openWakeWord's verifier-training stack.

``openwakeword/__init__`` imports ``custom_verifier_model`` (scipy +
scikit-learn, and pandas + pyarrow where installed) for a training helper the
wake path never calls. The provider's loader keeps that out of the process:
about 95 MB of private memory and over a second of import time on the boot
path. These tests pin that the saving holds, that scoring still works, and
that a failing lean import falls back to the plain one instead of costing the
wake word.
"""
from __future__ import annotations

import contextlib
import importlib.util
import subprocess
import sys
from collections.abc import Iterator

import pytest

from dodaios.plugins.wake import openwakeword_provider as provider_module
from dodaios.plugins.wake.openwakeword_provider import (
    OpenWakeWordProvider,
    _train_custom_verifier_unavailable,
    load_openwakeword_model_class,
)

needs_openwakeword = pytest.mark.skipif(
    importlib.util.find_spec("openwakeword") is None,
    reason="openwakeword not installed in this environment",
)


def _run_fresh(script: str) -> subprocess.CompletedProcess[str]:
    """Run in a fresh interpreter: another test may have imported the full stack."""
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
    )


@needs_openwakeword
def test_loader_keeps_the_training_stack_out_of_the_process() -> None:
    script = (
        "import sys\n"
        "from dodaios.plugins.wake.openwakeword_provider import (\n"
        "    load_openwakeword_model_class,\n"
        ")\n"
        "model_class = load_openwakeword_model_class()\n"
        "assert model_class.__name__ == 'Model', model_class\n"
        "loaded = [m for m in ('sklearn', 'pandas', 'pyarrow') if m in sys.modules]\n"
        "assert not loaded, f'training stack imported: {loaded}'\n"
        "assert 'openwakeword.custom_verifier_model' not in sys.modules\n"
        "print('OK')\n"
    )
    res = _run_fresh(script)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"


@needs_openwakeword
def test_training_module_still_imports_for_real_afterwards() -> None:
    script = (
        "import sys\n"
        "from dodaios.plugins.wake.openwakeword_provider import (\n"
        "    load_openwakeword_model_class,\n"
        ")\n"
        "load_openwakeword_model_class()\n"
        "import openwakeword.custom_verifier_model as real\n"
        "assert hasattr(real, 'LogisticRegression'), 'stand-in leaked'\n"
        "print('OK')\n"
    )
    res = _run_fresh(script)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"


@needs_openwakeword
def test_lean_runtime_scores_a_frame_with_the_bundled_backbones() -> None:
    """The model the lean import returns still loads and scores audio."""
    script = (
        "import sys\n"
        "from pathlib import Path\n"
        "import numpy as np\n"
        "import dodaios.assets\n"
        "from dodaios.plugins.wake.openwakeword_provider import (\n"
        "    OWW_FRAME_SAMPLES,\n"
        "    load_openwakeword_model_class,\n"
        ")\n"
        "model_class = load_openwakeword_model_class()\n"
        "import openwakeword\n"
        "resources = Path(openwakeword.__file__).parent / 'resources' / 'models'\n"
        "backbones = ('embedding_model', 'melspectrogram', 'silero_vad')\n"
        "candidates = sorted(\n"
        "    p for p in resources.glob('*.onnx') if p.stem not in backbones\n"
        ")\n"
        "if not candidates:\n"
        "    print('SKIP')\n"
        "    raise SystemExit(0)\n"
        "kwargs = {'wakeword_models': [str(candidates[0])],\n"
        "          'inference_framework': 'onnx'}\n"
        "bundled = dodaios.assets.bundled_wakeword_models()\n"
        "if bundled is not None:\n"
        "    kwargs['melspec_model_path'] = str(bundled['melspec'])\n"
        "    kwargs['embedding_model_path'] = str(bundled['embedding'])\n"
        "model = model_class(**kwargs)\n"
        "scores = model.predict(np.zeros(OWW_FRAME_SAMPLES, dtype=np.int16))\n"
        "assert scores and all(0.0 <= float(v) <= 1.0 for v in scores.values())\n"
        "assert 'sklearn' not in sys.modules\n"
        "print('OK')\n"
    )
    res = _run_fresh(script)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
    if "SKIP" in res.stdout:
        pytest.skip("no wake model file in the installed openwakeword package")


@needs_openwakeword
def test_failing_lean_import_falls_back_to_the_plain_one(monkeypatch) -> None:
    @contextlib.contextmanager
    def _broken() -> Iterator[None]:
        raise RuntimeError("lean import is not possible on this layout")
        yield  # pragma: no cover

    monkeypatch.setattr(provider_module, "_inference_only_openwakeword_import", _broken)

    model_class = load_openwakeword_model_class()

    assert model_class.__name__ == "Model"


def test_missing_runtime_still_degrades_through_the_loader(monkeypatch) -> None:
    """The retry must not undo a module that was unavailable before the call."""
    monkeypatch.setitem(sys.modules, "openwakeword.model", None)
    provider = OpenWakeWordProvider()

    provider._ensure_model()  # must NOT raise

    assert provider._runtime_unavailable is True
    assert sys.modules["openwakeword.model"] is None


def test_stand_in_training_helper_fails_loudly() -> None:
    with pytest.raises(RuntimeError, match="verifier training"):
        _train_custom_verifier_unavailable()


@needs_openwakeword
def test_concurrent_loaders_get_the_same_class() -> None:
    """The boot prefetch and the provider may load at once; both get one Model."""
    script = (
        "import sys, threading\n"
        "from dodaios.plugins.wake.openwakeword_provider import (\n"
        "    load_openwakeword_model_class,\n"
        ")\n"
        "found = []\n"
        "threads = [threading.Thread(target=lambda: found.append(\n"
        "    load_openwakeword_model_class())) for _ in range(4)]\n"
        "[t.start() for t in threads]\n"
        "[t.join(120) for t in threads]\n"
        "assert len(found) == 4 and len(set(found)) == 1, found\n"
        "assert 'sklearn' not in sys.modules\n"
        "print('OK')\n"
    )
    res = _run_fresh(script)
    assert res.returncode == 0, f"stdout={res.stdout}\nstderr={res.stderr}"
