"""The agent-chat routes keep their paths, methods and registration order.

The routes live in the ``agent_chat_routes`` package, one router per area,
joined in one aggregator. Order matters: a literal path must stay ahead of a
parameter path that would swallow it. This pins the list as it was when the
routes were one 3,000-line module.
"""

from __future__ import annotations

from fastapi import FastAPI

from dodaios.ui.web.agent_chat_routes import router

EXPECTED_HTTP: list[tuple[str, str]] = [
    ("PUT", "/api/agent-chat/selection"),
    ("GET", "/api/agent-chat/voice-chat"),
    ("PUT", "/api/agent-chat/voice-chat"),
    ("GET", "/api/agent-chat/commands"),
    ("GET", "/api/agent-chat/sessions/{session_id}/control"),
    ("POST", "/api/agent-chat/sessions/{session_id}/commands"),
    ("GET", "/api/agent-chat/catalog"),
    ("GET", "/api/agent-chat/tools"),
    ("GET", "/api/agent-chat/typeahead"),
    ("GET", "/api/agent-chat/provider-health"),
    ("GET", "/api/agent-chat/sessions"),
    ("GET", "/api/agent-chat/sessions/search"),
    ("POST", "/api/agent-chat/sessions"),
    ("GET", "/api/agent-chat/lead"),
    ("GET", "/api/agent-chat/lead/threads"),
    ("GET", "/api/agent-chat/thread-links/{ref}"),
    ("GET", "/api/agent-chat/lead/files"),
    ("GET", "/api/agent-chat/lead/channels"),
    ("GET", "/api/agent-chat/lead/brief"),
    ("PUT", "/api/agent-chat/lead/brief"),
    ("GET", "/api/agent-chat/lead/proactive"),
    ("PUT", "/api/agent-chat/lead/proactive"),
    ("POST", "/api/agent-chat/lead/proactive/checkin"),
    ("GET", "/api/agent-chat/lead/life-admin"),
    ("PUT", "/api/agent-chat/lead/life-admin"),
    ("POST", "/api/agent-chat/lead/life-admin/items/{item_id}/prepare"),
    ("POST", "/api/agent-chat/lead/life-admin/items/{item_id}/dismiss"),
    ("POST", "/api/agent-chat/lead/life-admin/items/{item_id}/done"),
    ("GET", "/api/agent-chat/lead/standing"),
    ("POST", "/api/agent-chat/lead/standing"),
    ("GET", "/api/agent-chat/lead/standing/{standing_id}"),
    ("PATCH", "/api/agent-chat/lead/standing/{standing_id}"),
    ("POST", "/api/agent-chat/lead/standing/{standing_id}/{action}"),
    ("GET", "/api/agent-chat/lead/triggers"),
    ("PUT", "/api/agent-chat/lead/triggers"),
    ("POST", "/api/agent-chat/lead/triggers/policies/{policy_id}/promote"),
    ("GET", "/api/agent-chat/lead/prepared"),
    ("PUT", "/api/agent-chat/lead/prepared/settings"),
    ("POST", "/api/agent-chat/lead/prepared/{item_id}/{outcome}"),
    ("POST", "/api/agent-chat/lead/triggers/events"),
    ("POST", "/api/agent-chat/lead/fresh-start"),
    ("POST", "/api/agent-chat/sessions/from-terminal"),
    ("POST", "/api/agent-chat/sessions/{session_id}/fork"),
    ("GET", "/api/agent-chat/sessions/{session_id}"),
    ("GET", "/api/agent-chat/sessions/{session_id}/subagents"),
    ("GET", "/api/agent-chat/sessions/{session_id}/context"),
    ("PATCH", "/api/agent-chat/sessions/{session_id}"),
    ("DELETE", "/api/agent-chat/sessions/{session_id}"),
    ("POST", "/api/agent-chat/sessions/{session_id}/messages"),
    ("DELETE", "/api/agent-chat/sessions/{session_id}/asides/{aside_id}"),
    ("POST", "/api/agent-chat/preload"),
    ("POST", "/api/agent-chat/sessions/{session_id}/warm"),
    ("POST", "/api/agent-chat/sessions/{session_id}/cancel"),
    ("GET", "/api/agent-chat/sessions/{session_id}/queue"),
    ("POST", "/api/agent-chat/sessions/{session_id}/queue/resume"),
    ("DELETE", "/api/agent-chat/sessions/{session_id}/queue/{queue_id}"),
    ("PATCH", "/api/agent-chat/sessions/{session_id}/queue/{queue_id}"),
    ("POST", "/api/agent-chat/sessions/{session_id}/queue/{queue_id}/send-now"),
    ("POST", "/api/agent-chat/sessions/{session_id}/side-threads/{side_id}/stop"),
    ("POST", "/api/agent-chat/sessions/{session_id}/side-threads/{side_id}/to-main"),
    ("POST", "/api/agent-chat/sessions/{session_id}/approvals/{approval_id}"),
    ("POST", "/api/agent-chat/sessions/{session_id}/approvals/{approval_id}/rule"),
    ("POST", "/api/agent-chat/sessions/{session_id}/questions/{question_id}"),
    ("POST", "/api/agent-chat/sessions/{session_id}/questions/{question_id}/skip"),
    ("POST", "/api/agent-chat/sessions/{session_id}/questions/{question_id}/submit"),
    ("POST", "/api/agent-chat/sessions/{session_id}/questions/{question_id}/touch"),
    ("POST", "/api/agent-chat/sessions/{session_id}/reply-to-question"),
    ("POST", "/api/agent-chat/sessions/{session_id}/credentials/{request_id}"),
    ("POST", "/api/agent-chat/sessions/{session_id}/credentials/{request_id}/decline"),
    ("POST", "/api/agent-chat/sessions/{session_id}/plan"),
    ("POST", "/api/agent-chat/attachments"),
    ("GET", "/api/agent-chat/attachments/file"),
    ("POST", "/api/agent-chat/pick-folder"),
    ("GET", "/api/agent-chat/check-folder"),
]

EXPECTED_WEBSOCKET = "/api/agent-chat/sessions/{session_id}/ws"


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    return app


def test_http_routes_keep_their_methods_paths_and_order() -> None:
    spec = _app().openapi()["paths"]
    found = [(method.upper(), path) for path, item in spec.items() for method in item]
    # OpenAPI groups the methods of one path; compare the path order and the pairs.
    assert list(dict.fromkeys(p for _, p in found)) == list(
        dict.fromkeys(p for _, p in EXPECTED_HTTP)
    )
    assert sorted(found) == sorted(EXPECTED_HTTP)


def _walk(routes: list, found: list[str]) -> None:
    for item in routes:
        inner = getattr(item, "original_router", None)
        if inner is not None:
            _walk(list(inner.routes), found)
        elif type(item).__name__ == "APIWebSocketRoute":
            found.append(item.path)


def test_the_live_stream_websocket_is_still_registered() -> None:
    found: list[str] = []
    _walk(list(router.routes), found)
    assert [p.rsplit("/", 1)[-1] for p in found] == [EXPECTED_WEBSOCKET.rsplit("/", 1)[-1]]
