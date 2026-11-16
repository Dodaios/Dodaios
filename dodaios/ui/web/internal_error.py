"""A readable answer for an error no route handled.

Without this, an unhandled exception reaches the window as a bare
"Internal Server Error" text, and the UI can only show "HTTP 500" (issue
#1734: the setup wizard's first step, no way to see why). The answer names
the error type and the log file that holds the full traceback. The message
of the exception itself stays in the log: it can carry paths or keys, and
some routes answer callers that are not the person at the computer.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

INTERNAL_ERROR_CODE = "internal_error"


def _log_file() -> str:
    try:
        from dodaios.ui.desktop_log import desktop_log_path

        return str(desktop_log_path())
    except Exception:  # noqa: BLE001 - the answer must never fail itself
        return ""


def internal_error_detail(exc: BaseException) -> str:
    """One sentence: what kind of error, and where the traceback is."""
    detail = f"Something went wrong inside Dodaios ({type(exc).__name__})."
    log_file = _log_file()
    if log_file:
        detail += f" The details are in {log_file}."
    return detail


async def _answer(request: Request, exc: Exception) -> JSONResponse:
    # Starlette's ServerErrorMiddleware calls this handler, then raises the
    # exception again, so the server still logs it with the full traceback.
    return JSONResponse(
        status_code=500,
        content={"detail": internal_error_detail(exc), "code": INTERNAL_ERROR_CODE},
    )


def install_internal_error_answer(app: FastAPI) -> None:
    app.add_exception_handler(Exception, _answer)
