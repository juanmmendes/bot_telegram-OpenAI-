from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


class BaseStateStore(ABC):
    """Interface for persisting chat state snapshots."""

    @abstractmethod
    def load(self, chat_id: int) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def save(self, chat_id: int, payload: Dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def delete(self, chat_id: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_chat_ids(self) -> Iterable[int]:
        raise NotImplementedError


class NullStateStore(BaseStateStore):
    """No-op store used when persistence is disabled."""

    def load(self, chat_id: int) -> Optional[Dict[str, Any]]:
        return None

    def save(self, chat_id: int, payload: Dict[str, Any]) -> None:
        return

    def delete(self, chat_id: int) -> None:
        return

    def list_chat_ids(self) -> Iterable[int]:
        return []


class JSONStateStore(BaseStateStore):
    """Persists chat states in individual JSON files."""

    def __init__(self, base_path: Path) -> None:
        self.base_path = base_path
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _file_for(self, chat_id: int) -> Path:
        return self.base_path / f"chat_{chat_id}.json"

    def load(self, chat_id: int) -> Optional[Dict[str, Any]]:
        file_path = self._file_for(chat_id)
        if not file_path.exists():
            return None
        try:
            with file_path.open("r", encoding="utf-8") as handler:
                return json.load(handler)
        except json.JSONDecodeError:
            # Corrupted file: remove to avoid repeated failures
            file_path.unlink(missing_ok=True)
            return None

    def save(self, chat_id: int, payload: Dict[str, Any]) -> None:
        file_path = self._file_for(chat_id)
        with file_path.open("w", encoding="utf-8") as handler:
            json.dump(payload, handler, ensure_ascii=False, indent=2)

    def delete(self, chat_id: int) -> None:
        self._file_for(chat_id).unlink(missing_ok=True)

    def list_chat_ids(self) -> Iterable[int]:
        for file_path in self.base_path.glob("chat_*.json"):
            name = file_path.stem.removeprefix("chat_")
            if name.isdigit():
                yield int(name)


def create_state_store(path: Optional[str]) -> BaseStateStore:
    if not path:
        return NullStateStore()
    return JSONStateStore(Path(path))

