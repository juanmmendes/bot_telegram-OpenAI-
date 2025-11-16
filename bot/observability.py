from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional


class MetricsRecorder:
    """Collects lightweight metrics and optionally persists them to disk."""

    def __init__(self, file_path: Optional[str] = None) -> None:
        self.file_path = Path(file_path) if file_path else None
        self._lock = Lock()
        self._data: Dict[str, Any] = {
            "total_updates": 0,
            "unique_chats": [],
            "openai_calls": {"count": 0, "total_duration": 0.0, "total_prompt_tokens": 0, "total_completion_tokens": 0},
            "transcriptions": {"count": 0, "total_duration": 0.0},
            "errors": {},
            "last_updated": None,
        }
        self._seen_chats = set[int]()
        if self.file_path and self.file_path.exists():
            self._load_from_disk()

    def record_update(self, chat_id: int) -> None:
        with self._lock:
            self._data["total_updates"] += 1
            self._seen_chats.add(chat_id)
            self._persist()

    def record_openai_call(
        self,
        duration: float,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> None:
        with self._lock:
            stats = self._data["openai_calls"]
            stats["count"] += 1
            stats["total_duration"] += duration
            if prompt_tokens is not None:
                stats["total_prompt_tokens"] += prompt_tokens
            if completion_tokens is not None:
                stats["total_completion_tokens"] += completion_tokens
            self._persist()

    def record_transcription(self, duration: float) -> None:
        with self._lock:
            stats = self._data["transcriptions"]
            stats["count"] += 1
            stats["total_duration"] += duration
            self._persist()

    def record_error(self, kind: str) -> None:
        with self._lock:
            errors = self._data["errors"]
            errors[kind] = errors.get(kind, 0) + 1
            self._persist()

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._data))

    def _persist(self) -> None:
        self._data["last_updated"] = time.time()
        self._data["unique_chats"] = sorted(self._seen_chats)
        if not self.file_path:
            return

        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        with self.file_path.open("w", encoding="utf-8") as handler:
            json.dump(self._data, handler, ensure_ascii=False, indent=2)

    def _load_from_disk(self) -> None:
        try:
            with self.file_path.open("r", encoding="utf-8") as handler:
                payload = json.load(handler)
        except json.JSONDecodeError:
            return
        self._data.update(payload)
        unique = payload.get("unique_chats", [])
        self._seen_chats = set(int(chat_id) for chat_id in unique if isinstance(chat_id, int) or str(chat_id).isdigit())

    @classmethod
    def from_file(cls, file_path: Optional[str]) -> "MetricsRecorder":
        recorder = cls(file_path=file_path)
        return recorder

