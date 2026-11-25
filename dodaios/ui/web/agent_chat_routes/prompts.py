"""Approvals, questions, credentials and plans the agent asks about."""

from __future__ import annotations

from typing import Any

from fastapi import (
    APIRouter,
    HTTPException,
    Request,
)

from dodaios.agent_chat.credential_requests import CredentialRequestBusy
from dodaios.agent_chat.service import (
    DECISIONS,
    RULE_BREADTHS,
    RULE_NARROWS,
    RULE_SCOPES,
    SessionBusy,
)
from dodaios.society.credentials import CredentialError
from dodaios.ui.web import agent_chat_routes as _r
from dodaios.ui.web.agent_chat_routes.models import (
    ApprovalBody,
    ApprovalRuleBody,
    CredentialBody,
    PlanBody,
    QuestionAnswerBody,
    QuestionReplyBody,
    QuestionSkipBody,
    QuestionSubmitBody,
)

router = APIRouter()


@router.post("/sessions/{session_id}/approvals/{approval_id}")
async def resolve_approval(
    session_id: str, approval_id: str, body: ApprovalBody, request: Request
) -> dict[str, Any]:
    svc = await _r._async_service(request)
    if body.decision not in DECISIONS:
        raise HTTPException(status_code=400, detail=f"decision must be one of {list(DECISIONS)}")
    if body.scope and body.scope not in RULE_SCOPES:
        raise HTTPException(status_code=400, detail=f"scope must be one of {list(RULE_SCOPES)}")
    if body.breadth and body.breadth not in RULE_BREADTHS:
        raise HTTPException(status_code=400, detail=f"breadth must be one of {list(RULE_BREADTHS)}")
    if body.narrow and body.narrow not in RULE_NARROWS:
        raise HTTPException(status_code=400, detail=f"narrow must be one of {list(RULE_NARROWS)}")
    if body.narrow and body.scope != "chat":
        raise HTTPException(status_code=400, detail="a narrow rule needs scope chat")
    try:
        ok = svc.resolve_approval(
            session_id,
            approval_id,
            body.decision,
            scope=body.scope,
            breadth=body.breadth,
            narrow=body.narrow,
            feedback=body.feedback,
            edits=body.edits or None,
            review=body.review.to_review() if body.review else None,
        )
    except ValueError as exc:  # an edit the action does not allow; the card stays open
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not ok:
        if await svc.close_stale_approval(session_id, approval_id):
            # The card outlived what it asked for (an app restart, a second
            # card for the same call); it is closed now and nothing ran.
            raise HTTPException(
                status_code=410,
                detail=(
                    "This request expired and nothing ran; "
                    "the agent asks again if it still needs it."
                ),
            )
        raise HTTPException(status_code=404, detail="no such pending approval")
    return {"ok": True, "approval_id": approval_id, "decision": body.decision}


@router.post("/sessions/{session_id}/approvals/{approval_id}/rule")
async def save_approval_rule(
    session_id: str, approval_id: str, body: ApprovalRuleBody, request: Request
) -> dict[str, Any]:
    """Turn a card into a standing rule after the fact ("Always allow next time")."""
    svc = await _r._async_service(request)
    if body.kind not in ("always_allow", "require_approval"):
        raise HTTPException(status_code=400, detail="kind must be always_allow or require_approval")
    if body.breadth not in RULE_BREADTHS:
        raise HTTPException(status_code=400, detail="breadth must be action or app")
    try:
        rule = await svc.save_approval_rule(
            session_id,
            approval_id,
            kind=body.kind,
            scope=body.scope,
            breadth=body.breadth,
            narrow=body.narrow,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="no such approval card") from exc
    except LookupError as exc:
        raise HTTPException(status_code=409, detail="no rule fits this card here") from exc
    return {"ok": True, "approval_id": approval_id, "rule": rule}


@router.post(
    "/sessions/{session_id}/questions/{question_id}",
    summary="Answer an agent's multiple-choice question",
)
async def answer_question(
    session_id: str, question_id: str, body: QuestionAnswerBody, request: Request
) -> dict[str, Any]:
    svc = await _r._async_service(request)
    try:
        ok = svc.resolve_question(
            session_id,
            question_id,
            index=body.index,
            option_index=body.option_index,
            option_indices=body.option_indices,
            text=body.text,
        )
        if not ok:
            # Not a card a running turn waits on: an end-of-turn card, whose
            # answers go to the agent as the next message.
            ok = await svc.answer_turn_question(
                session_id,
                question_id,
                index=body.index,
                option_index=body.option_index,
                option_indices=body.option_indices,
                text=body.text,
            )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="session is busy") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="no such open question")
    return {"ok": True, "question_id": question_id}


@router.post(
    "/sessions/{session_id}/questions/{question_id}/skip",
    summary="Close an agent's question card and let its recommendations apply",
)
async def skip_question(
    session_id: str,
    question_id: str,
    request: Request,
    body: QuestionSkipBody | None = None,
) -> dict[str, Any]:
    svc = await _r._async_service(request)
    index = body.index if body is not None else None
    try:
        ok = svc.skip_question(session_id, question_id, index) or await svc.skip_turn_question(
            session_id, question_id, index=index
        )
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="session is busy") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="no such open question")
    return {"ok": True, "question_id": question_id}


@router.post(
    "/sessions/{session_id}/questions/{question_id}/submit",
    summary="Send the person's reviewed answers to a whole question card at once",
)
async def submit_question(
    session_id: str, question_id: str, body: QuestionSubmitBody, request: Request
) -> dict[str, Any]:
    svc = await _r._async_service(request)
    try:
        ok = svc.submit_questions(
            session_id, question_id, body.answers
        ) or await svc.submit_turn_question(session_id, question_id, body.answers)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="session is busy") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="no such open question")
    return {"ok": True, "question_id": question_id}


@router.post(
    "/sessions/{session_id}/questions/{question_id}/touch",
    summary="The person is still answering a question card: restart its quiet window",
)
async def touch_question(session_id: str, question_id: str, request: Request) -> dict[str, Any]:
    svc = await _r._async_service(request)
    # An end-of-turn card has no window, so only a live card can be touched.
    return {"ok": bool(svc.touch_question(session_id, question_id))}


@router.post(
    "/sessions/{session_id}/reply-to-question",
    summary="A chat message answers the open question card",
)
async def reply_to_question(
    session_id: str, body: QuestionReplyBody, request: Request
) -> dict[str, Any]:
    svc = await _r._async_service(request)
    try:
        outcome = await svc.answer_by_message(session_id, body.text)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **outcome}


@router.post(
    "/sessions/{session_id}/credentials/{request_id}",
    summary="Save the secret an agent asked for in its secure credential field",
    openapi_extra={"x-jarvis-dangerous": True},
)
async def submit_credential(
    session_id: str, request_id: str, body: CredentialBody, request: Request
) -> dict[str, Any]:
    svc = _r._service(request)
    if not isinstance(body.value, str):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_token",
                "message": "Enter a credential as text before saving.",
            },
        )
    try:
        ok = await svc.submit_credential(session_id, request_id, body.value)
    except CredentialRequestBusy:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "request_busy",
                "message": "The credential is still being checked. Please wait.",
            },
        ) from None
    except CredentialError as exc:
        status = {
            "network_error": 503,
            "validation_timeout": 504,
            "storage_failed": 503,
        }.get(exc.code, 400)
        raise HTTPException(
            status_code=status,
            detail={
                "code": exc.code,
                "message": str(exc),
            },
        ) from None
    except Exception:
        # A third-party storage exception may include the token. Never emit
        # its message or traceback into logs, HTTP bodies or the agent timeline.
        _r.log.warning("agent chat: credential submission failed for %s", session_id)
        raise HTTPException(
            status_code=503,
            detail={
                "code": "storage_failed",
                "message": "The credential could not be stored. Try again.",
            },
        ) from None
    if not ok:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "request_closed",
                "message": "This credential field is already closed.",
            },
        )
    return {"ok": True, "request_id": request_id, "status": "saved"}


@router.post(
    "/sessions/{session_id}/credentials/{request_id}/decline",
    summary="Close an agent's credential field without providing the secret",
)
async def decline_credential(session_id: str, request_id: str, request: Request) -> dict[str, Any]:
    svc = _r._service(request)
    try:
        ok = await svc.decline_credential(session_id, request_id)
    except CredentialRequestBusy:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "request_busy",
                "message": "The credential is still being checked. Please wait.",
            },
        ) from None
    if not ok:
        raise HTTPException(
            status_code=410,
            detail={
                "code": "request_closed",
                "message": "This credential field is already closed.",
            },
        )
    return {"ok": True, "request_id": request_id, "status": "declined"}


@router.post(
    "/sessions/{session_id}/plan",
    summary="Answer a coding agent's plan card: build it, or keep planning",
)
async def resolve_plan(session_id: str, body: PlanBody, request: Request) -> dict[str, Any]:
    svc = await _r._async_service(request)
    try:
        ok = await svc.resolve_turn_plan(
            session_id,
            body.turn_id,
            body.decision,
            build_mode=body.build_mode,
            review=body.review.to_review() if body.review else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="session is busy") from exc
    if not ok:
        raise HTTPException(status_code=404, detail="no such open plan")
    return {"ok": True, "turn_id": body.turn_id, "decision": body.decision}
