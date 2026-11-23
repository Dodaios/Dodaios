"""Command definitions: missions.

Split mechanically out of ``dodaios.commands.registry._build_registry``; the order of
the assembled registry is pinned by tests/unit/commands/test_registry_snapshot.py.
"""
from __future__ import annotations

from dodaios.commands.registry import (
    AppCommand,
    _str_param,
)


def build() -> tuple[AppCommand, ...]:
    return (
        AppCommand(
            id="missions-list",
            title="List missions",
            description=(
                "List Dodaios-Agent missions and their status, newest first, one page at a "
                "time. Set active to see only the ones that have not ended yet, or state "
                "for specific states. The answer has total (all matches) and next_cursor: "
                "pass it as cursor for the next page."
            ),
            method="GET",
            path="/api/missions",
            params={"type": "object", "properties": {
                "active": {
                    "type": "boolean",
                    "description": "Only missions still pending, running or waiting.",
                },
                "state": {
                    "type": "string",
                    "description": (
                        "Comma-separated mission states, e.g. RUNNING,PENDING or COMPLETED."
                    ),
                },
                "limit": {
                    "type": "integer", "minimum": 1, "maximum": 100, "default": 20,
                    "description": "How many missions per page (default 20).",
                },
                "cursor": {
                    "type": "string",
                    "description": "next_cursor of the previous page, for the older ones.",
                },
            }},
            worker_allowed=True,
            ui_section="agents",
            voice_aliases={
                "de": ("zeig mir die missionen",),  # i18n-allow: input vocab
                "en": ("show me the missions",),
                "es": ("muéstrame las misiones",),  # i18n-allow: input vocab
                "pt": ("mostra-me as missões",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="mission-result",
            title="Read a mission result",
            description=(
                "Read the signed summary and actual deliverable contents of one "
                "completed Dodaios-Agent mission. Use this after listing missions "
                "when the user asks what a mission found or produced."
            ),
            method="GET",
            path="/api/missions/{mission_id}/result",
            worker_allowed=True,
            params={
                "type": "object",
                "properties": {
                    "mission_id": _str_param(
                        "Mission id whose result should be read.", min_length=1
                    ),
                },
                "required": ["mission_id"],
            },
            path_params=("mission_id",),
            ui_section="agents",
            voice_aliases={
                "de": ("was hat die mission herausgefunden",),  # i18n-allow: input vocab
                "en": ("what did the mission find",),
                "es": ("qué encontró la misión",),  # i18n-allow: input vocab
                "pt": ("o que encontrou a missão",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="mission-cancel",
            title="Cancel a mission",
            description="Cancel a running Dodaios-Agent mission by id.",
            method="POST",
            path="/api/missions/{mission_id}/cancel",
            params={
                "type": "object",
                "properties": {
                    "mission_id": _str_param("Mission id to cancel.", min_length=1),
                },
                "required": ["mission_id"],
            },
            path_params=("mission_id",),
            dangerous=True,
            ui_section="agents",
            voice_aliases={
                "de": ("brich die mission ab",),  # i18n-allow: input vocab
                "en": ("cancel the mission",),
                "es": ("cancela la misión",),  # i18n-allow: input vocab
                "pt": ("cancela a missão",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="mission-amend",
            title="Correct a running mission",
            description=(
                "Give a mission that is still running the user's correction or changed "
                "wish, in their words, without restarting it. The running worker cannot "
                "be interrupted: the next attempt gets the correction. Read applies in the "
                "result and tell the user that, never that it is already done. A mission "
                "that has ended refuses; start a new one for the change."
            ),
            method="POST",
            path="/api/missions/{mission_id}/amend",
            params={
                "type": "object",
                "properties": {
                    "mission_id": _str_param("Mission id to correct.", min_length=1),
                    "instruction": _str_param(
                        "The correction, complete in itself.", min_length=1, max_length=4000
                    ),
                },
                "required": ["mission_id", "instruction"],
            },
            path_params=("mission_id",),
            ui_section="agents",
            voice_aliases={
                "de": ("sag der mission sie soll es anders machen",),  # i18n-allow: input vocab
                "en": ("tell the mission to do it differently",),
                "es": ("dile a la misión que lo haga de otra forma",),  # i18n-allow: input vocab
                "pt": ("diz à missão para fazer de outra forma",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="tasks-list",
            title="List tasks",
            description=(
                "List scheduled and running tasks (agent routines), newest first, one page "
                "at a time. The answer has total (all matches) and next_cursor: pass it as "
                "cursor for the next page."
            ),
            method="GET",
            path="/api/tasks",
            params={"type": "object", "properties": {
                "state": {
                    "type": "string",
                    "description": "Comma-separated task states, e.g. scheduled,running.",
                },
                "limit": {
                    "type": "integer", "minimum": 1, "maximum": 100, "default": 20,
                    "description": "How many tasks per page (default 20).",
                },
                "cursor": {
                    "type": "string",
                    "description": "next_cursor of the previous page, for the older ones.",
                },
            }},
            worker_allowed=True,
            ui_section="agents",
            voice_aliases={
                "de": ("zeig mir meine aufgaben",),  # i18n-allow: input vocab
                "en": ("show me my tasks",),
                "es": ("muéstrame mis tareas",),  # i18n-allow: input vocab
                "pt": ("mostra-me as minhas tarefas",),  # i18n-allow: input vocab
            },
        ),
        AppCommand(
            id="task-cancel",
            title="Cancel a task",
            description="Cancel a running or scheduled task by id.",
            method="POST",
            path="/api/tasks/{task_id}/cancel",
            params={
                "type": "object",
                "properties": {
                    "task_id": _str_param("Task id to cancel.", min_length=1),
                },
                "required": ["task_id"],
            },
            path_params=("task_id",),
            dangerous=True,
            ui_section="agents",
            voice_aliases={
                "de": ("brich die aufgabe ab",),  # i18n-allow: input vocab
                "en": ("cancel the task",),
                "es": ("cancela la tarea",),  # i18n-allow: input vocab
                "pt": ("cancela a tarefa",),  # i18n-allow: input vocab
            },
        ),
    )
