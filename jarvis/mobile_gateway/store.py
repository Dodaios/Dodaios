"""Per-device data the phone app shows: chat history, tasks, inbox and files.

Everything lives in plain files under ``<data_dir>/devices/<device_id>/``:
``history.jsonl`` and ``inbox.jsonl`` are append-only, ``tasks.json`` is
rewritten atomically, and files sit in ``from_phone/`` (uploads) and
``to_phone/`` (dropped there on the PC for the phone to fetch).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

#: Folder names a download may come from.
FILE_DIRS = ("from_phone", "to_phone")
MAX_HISTORY = 200
MAX_TASK_CHARS = 500
_UNSAFE_NAME = re.compile(r"[^\w.\- ]+")
_MAX_NAME = 120


def safe_filename(name: str) -> str:
    """A bare, harmless file name; never a path, never hidden."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = _UNSAFE_NAME.sub("_", base).strip(" .")
    return cleaned[:_MAX_NAME] or "datei"


class DeviceData:
    def __init__(self, data_dir: Path) -> None:
        self._root = data_dir / "devices"
        self._lock = threading.Lock()

    def _dir(self, device_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{1,64}", device_id):
            raise ValueError("bad device id")
        path = self._root / device_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    # -- jsonl helpers -------------------------------------------------

    def _append(self, path: Path, entry: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def _tail(self, path: Path, limit: int) -> list[dict[str, Any]]:
        try:
            with path.open(encoding="utf-8") as fh:
                lines = deque(fh, maxlen=limit)
        except FileNotFoundError:  # nothing stored yet
            return []
        out: list[dict[str, Any]] = []
        for line in lines:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # a torn last line after a crash is skipped, not fatal
        return out

    # -- history -------------------------------------------------------

    def add_history(self, device_id: str, role: str, text: str) -> None:
        with self._lock:
            path = self._dir(device_id) / "history.jsonl"
            self._append(path, {"role": role, "text": text, "ts": int(time.time())})

    def history(self, device_id: str, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return self._tail(self._dir(device_id) / "history.jsonl", min(limit, MAX_HISTORY))

    # -- inbox (Jarvis -> phone) ---------------------------------------

    def push_inbox(self, device_id: str, text: str) -> int:
        with self._lock:
            path = self._dir(device_id) / "inbox.jsonl"
            last = self._tail(path, 1)
            seq = int(last[0].get("id", 0)) + 1 if last else 1
            self._append(path, {"id": seq, "text": text, "ts": int(time.time())})
        return seq

    def inbox(self, device_id: str, after: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            entries = self._tail(self._dir(device_id) / "inbox.jsonl", MAX_HISTORY)
        return [e for e in entries if int(e.get("id", 0)) > after]

    # -- tasks ---------------------------------------------------------

    def _load_tasks(self, device_id: str) -> list[dict[str, Any]]:
        try:
            raw = json.loads((self._dir(device_id) / "tasks.json").read_text(encoding="utf-8"))
        except FileNotFoundError:  # nothing stored yet
            return []
        return [t for t in raw if isinstance(t, dict)] if isinstance(raw, list) else []

    def _save_tasks(self, device_id: str, tasks: list[dict[str, Any]]) -> None:
        path = self._dir(device_id) / "tasks.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def tasks(self, device_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._load_tasks(device_id)

    def add_task(self, device_id: str, text: str) -> dict[str, Any]:
        task = {
            "id": secrets.token_hex(6),
            "text": text[:MAX_TASK_CHARS],
            "done": False,
            "created": int(time.time()),
        }
        with self._lock:
            tasks = self._load_tasks(device_id)
            tasks.append(task)
            self._save_tasks(device_id, tasks)
        return task

    def update_task(self, device_id: str, task_id: str, *, done: bool) -> dict[str, Any] | None:
        with self._lock:
            tasks = self._load_tasks(device_id)
            for task in tasks:
                if task.get("id") == task_id:
                    task["done"] = done
                    self._save_tasks(device_id, tasks)
                    return task
        return None

    def delete_task(self, device_id: str, task_id: str) -> bool:
        with self._lock:
            tasks = self._load_tasks(device_id)
            kept = [t for t in tasks if t.get("id") != task_id]
            if len(kept) == len(tasks):
                return False
            self._save_tasks(device_id, kept)
        return True

    # -- files ---------------------------------------------------------

    def file_dir(self, device_id: str, which: str) -> Path:
        if which not in FILE_DIRS:
            raise ValueError("bad folder")
        path = self._dir(device_id) / which
        path.mkdir(exist_ok=True)
        return path

    def save_upload(self, device_id: str, name: str, data: bytes) -> str:
        folder = self.file_dir(device_id, "from_phone")
        base = safe_filename(name)
        target = folder / base
        if target.exists():
            target = folder / f"{time.strftime('%Y%m%d-%H%M%S')}_{base}"
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, target)
        return target.name

    def files(self, device_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for which in FILE_DIRS:
            for entry in sorted(self.file_dir(device_id, which).iterdir()):
                if entry.is_file() and not entry.name.endswith(".part"):
                    stat = entry.stat()
                    out.append(
                        {
                            "dir": which,
                            "name": entry.name,
                            "size": stat.st_size,
                            "mtime": int(stat.st_mtime),
                        }
                    )
        return out

    def find_file(self, device_id: str, which: str, name: str) -> Path | None:
        """The listed file called ``name``; nothing outside the folder resolves."""
        folder = self.file_dir(device_id, which)
        for entry in folder.iterdir():
            if entry.is_file() and entry.name == name and not name.endswith(".part"):
                return entry
        return None
