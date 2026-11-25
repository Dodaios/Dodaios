"""REST + WebSocket routes for the agent chat (the typed front-page chat).

Prefix ``/api/agent-chat``:

    GET    /catalog?surface=                 provider rows + effort + permission ladders
    GET    /provider-health?surface=         which of those rows actually answer
    GET    /sessions?surface=                newest first; ``surface`` narrows to one chat
    POST   /sessions                         create (provider, model, effort, cwd,
                                             permission_mode, surface)
    GET    /sessions/{id}                    session + its persisted events
    PATCH  /sessions/{id}                    title/provider/model/effort/cwd/permission_mode
    DELETE /sessions/{id}
    POST   /sessions/{id}/messages           {text, attachments} -> starts a turn
    POST   /sessions/{id}/cancel
    POST   /sessions/{id}/approvals/{aid}    {decision: allow | allow_always | deny,
                                             scope?: agent | chat, breadth?: action | app}
    POST   /sessions/{id}/approvals/{aid}/rule  {kind: always_allow | require_approval,
                                             scope, breadth} -> a rule from a settled card
    POST   /sessions/{id}/questions/{qid}    {index, option_index | option_indices | text}
                                             -> answer one question of an agent's card
    POST   /sessions/{id}/questions/{qid}/submit  {answers: [...]} -> the whole reviewed card
    POST   /sessions/{id}/questions/{qid}/skip  close the card: recommendations apply;
                                             {index} skips that one question only
    POST   /sessions/{id}/questions/{qid}/touch  the person is still answering: restart
                                             the card's quiet window
    POST   /sessions/{id}/reply-to-question  {text} -> a chat message answers the open card
    POST   /sessions/{id}/plan               {turn_id, decision: build | keep} -> answer
                                             a coding agent's plan card
    WS     /sessions/{id}/ws?after=<seq>     snapshot, then live events
    POST   /attachments                      drop/paste/pick files for the next message
    POST   /pick-folder                      the system folder dialog (desktop only)
    GET    /check-folder?path=               does the folder exist / is it a directory
    GET    /typeahead?trigger=&surface=&provider=&cwd=&q=
                                             what the composer lists after "/", "@" or "$"

The service lives on ``app.state.agent_chat`` (built in ``server.py``); a
missing service answers 503 like every other optional subsystem.
Loopback-only like the rest of the web UI — no auth token.
"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/agent-chat", tags=["agent-chat"])

from dodaios.agent_chat.service import resolve_runner  # noqa: E402,F401
from dodaios.ui.web.agent_chat_routes import (  # noqa: E402
    catalog,
    files,
    lead,
    prompts,
    queue,
    selection,
    sessions,
    threads,
    turns,
)
from dodaios.ui.web.agent_chat_routes.catalog import (  # noqa: E402,F401
    _catalog_rows,
    _cli_auth_status,
    _cli_login_snapshot,
    _cli_subscription_connected,
    _one_provider_health,
    get_catalog,
    get_composer_tools,
    get_provider_health,
    get_typeahead,
)
from dodaios.ui.web.agent_chat_routes.common import (  # noqa: E402,F401
    _CLI_RUNNERS,
    _HEALTH_SWEEP_S,
    _HEALTH_TTL_S,
    _REATTACH_DELAY_S,
    _STANDING_ACTIONS,
    _STANDING_STATUS,
    _WARMING,
    _WS_PING_S,
    HIDDEN_SURFACES,
    SURFACE_NAMES,
    _health_cache,
    _service_from_state,
    log,
)
from dodaios.ui.web.agent_chat_routes.files import (  # noqa: E402,F401
    _folder_check,
    attach_files,
    attachment_file,
    check_folder,
    pick_folder,
    session_stream,
)
from dodaios.ui.web.agent_chat_routes.helpers import (  # noqa: E402,F401
    _async_service,
    _cli_installed,
    _folder_for,
    _live_cli_models,
    _service,
    _session_or_bound_agent_chat,
    _validate_computer,
    _validate_cwd,
    _ws_service,
    schedule_turn_reattach,
)
from dodaios.ui.web.agent_chat_routes.lead import (  # noqa: E402,F401
    _lead_session_id,
    _standing_refused,
    _trigger_service,
    _trigger_view,
    act_on_lead_standing,
    dismiss_lead_life_admin_item,
    finish_lead_life_admin_item,
    get_lead_brief,
    get_lead_channels,
    get_lead_life_admin,
    get_lead_prepared,
    get_lead_proactive,
    get_lead_session,
    get_lead_standing,
    get_lead_standing_task,
    get_lead_triggers,
    get_thread_link,
    lead_fresh_start,
    list_lead_files,
    list_lead_threads,
    patch_lead_standing,
    post_lead_checkin,
    post_lead_standing,
    post_lead_trigger_event,
    prepare_lead_life_admin_item,
    promote_lead_trigger_policy,
    put_lead_brief,
    put_lead_life_admin,
    put_lead_prepared_settings,
    put_lead_proactive,
    put_lead_triggers,
    resolve_lead_prepared,
)

# Every name the old single module exposed stays importable from here, and the
# helpers read each other through this module so a patch on it takes effect.
from dodaios.ui.web.agent_chat_routes.models import (  # noqa: E402,F401
    ApprovalBody,
    ApprovalRuleBody,
    ChatSelectionBody,
    CreateSessionBody,
    CredentialBody,
    ForkSessionBody,
    FromTerminalBody,
    LeadBriefBody,
    LeadCheckinBody,
    LeadLifeAdminBody,
    LeadProactiveBody,
    LeadStandingBody,
    LeadStandingPatchBody,
    LeadTriggerEventBody,
    MessageBody,
    PatchSessionBody,
    PickFolderBody,
    PlanBody,
    PlanCommentBody,
    PlanReviewBody,
    PreloadBody,
    ProviderHealthResponse,
    ProviderHealthRow,
    QuestionAnswerBody,
    QuestionReplyBody,
    QuestionSkipBody,
    QuestionSubmitBody,
    QueuedEditBody,
    SurfaceName,
    VoiceChatBody,
    VoiceChatResponse,
)
from dodaios.ui.web.agent_chat_routes.prompts import (  # noqa: E402,F401
    answer_question,
    decline_credential,
    reply_to_question,
    resolve_approval,
    resolve_plan,
    save_approval_rule,
    skip_question,
    submit_credential,
    submit_question,
    touch_question,
)
from dodaios.ui.web.agent_chat_routes.queue import (  # noqa: E402,F401
    discard_queued,
    edit_queued,
    get_queue,
    resume_queue,
    send_queued_now,
    side_thread_to_main,
    stop_side_thread,
)
from dodaios.ui.web.agent_chat_routes.selection import (  # noqa: E402,F401
    _archived_voice_history,
    _reported_running,
    _voice_chat_answer,
    get_chat_control,
    get_voice_chat,
    list_chat_commands,
    put_voice_chat,
    run_chat_command,
    save_chat_selection,
)
from dodaios.ui.web.agent_chat_routes.sessions import (  # noqa: E402,F401
    _cli_title,
    _team_sessions,
    _title_chats,
    create_session,
    list_sessions,
    search_sessions,
)
from dodaios.ui.web.agent_chat_routes.threads import (  # noqa: E402,F401
    _ask_aside,
    delete_session,
    dismiss_aside,
    fork_session,
    get_context_window,
    get_session,
    list_subagents,
    patch_session,
    post_message,
    thread_from_terminal,
)
from dodaios.ui.web.agent_chat_routes.turns import (  # noqa: E402,F401
    _preload_local_model,
    _preload_provider_model,
    cancel_turn,
    preload_model,
    warm_session,
)

router.include_router(selection.router)
router.include_router(catalog.router)
router.include_router(sessions.router)
router.include_router(lead.router)
router.include_router(threads.router)
router.include_router(turns.router)
router.include_router(queue.router)
router.include_router(prompts.router)
router.include_router(files.router)
