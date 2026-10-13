"""Dodaios — a voice-driven, cross-platform meta-orchestrator."""

__version__ = "3.1.1"

# Every httpx client in the process shares one parsed CA bundle instead of
# re-parsing it (~200 ms of CPU) per client. Patches httpx lazily, the moment
# it is first imported; importing ``jarvis`` itself still loads nothing heavy.
from jarvis.core.shared_tls import install_when_imported as _install_shared_tls

_install_shared_tls()
del _install_shared_tls

# numpy and scipy each start one BLAS thread per CPU core and commit 32 MB for
# every one (~1 GB per process on a 16-thread Windows box). Cap that pool the
# moment either package is first imported; nothing is loaded here.
from jarvis.core.blas_threads import install_when_imported as _install_blas_cap  # noqa: E402

_install_blas_cap()
del _install_blas_cap
