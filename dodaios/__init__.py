"""Dodaios — a voice-driven, cross-platform meta-orchestrator."""

__version__ = "4.0.1"

import os as _os

# loguru's "diagnose" mode prints every local variable of every frame in a
# logged traceback, tokens and API keys included, and it is on by default for
# its stderr sink and every logger.add() that does not say otherwise. Turn it
# off for the whole process (and the helper processes, which inherit the
# environment) before anything imports loguru. A developer can still opt in
# by setting LOGURU_DIAGNOSE=YES.
_os.environ.setdefault("LOGURU_DIAGNOSE", "NO")
del _os

# A variable written as ``DODAIOS_<NAME>`` is moved to the ``JARVIS_<NAME>``
# spelling the code reads. Done here, on the first import of the package, so
# every entry point (the app, the CLIs, the MCP servers, each helper process)
# sees it before any reader runs. A dictionary pass; see
# dodaios/core/env_prefix.py for the precedence.
from dodaios.core.env_prefix import adopt_environment as _adopt_environment  # noqa: E402

# Every httpx client in the process shares one parsed CA bundle instead of
# re-parsing it (~200 ms of CPU) per client. Patches httpx lazily, the moment
# it is first imported; importing ``jarvis`` itself still loads nothing heavy.
from dodaios.core.shared_tls import install_when_imported as _install_shared_tls  # noqa: E402

_adopt_environment()
_install_shared_tls()
del _adopt_environment, _install_shared_tls

# numpy and scipy each start one BLAS thread per CPU core and commit 32 MB for
# every one (~1 GB per process on a 16-thread Windows box). Cap that pool the
# moment either package is first imported; nothing is loaded here.
from dodaios.core.blas_threads import install_when_imported as _install_blas_cap  # noqa: E402

_install_blas_cap()
del _install_blas_cap
