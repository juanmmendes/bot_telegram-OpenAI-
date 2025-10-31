from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Optional
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def _build_session() -> requests.Session:
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST"}),
    )
    adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20, max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    session.headers.update(
        {
            "Connection": "keep-alive",
            "User-Agent": "UniversityAIBot/1.0",
        }
    )
    return session


@dataclass
class TelegramClient:
    token: str
    request_timeout: int = 20
    session: Optional[requests.Session] = None

    API_URL_TEMPLATE = "https://api.telegram.org/bot{token}/{method}"

    def __post_init__(self) -> None:
        if self.session is None:
            self.session = _build_session()

    def _url(self, method: str) -> str:
        return self.API_URL_TEMPLATE.format(token=self.token, method=method)

    def get_updates(self, offset: Optional[int] = None, timeout: int = 25) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "timeout": timeout,
            "allowed_updates": json.dumps(["message", "edited_message"]),
        }
        if offset is not None:
            payload["offset"] = offset

        response = self.session.get(self._url("getUpdates"), params=payload, timeout=self.request_timeout)
        response.raise_for_status()
        return response.json()

    def send_message(
        self,
        chat_id: int,
        text: str,
        *,
        parse_mode: Optional[str] = "HTML",
        reply_to: Optional[int] = None,
        keyboard: Optional[list[list[str]]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to is not None:
            payload["reply_to_message_id"] = reply_to
        if keyboard:
            payload["reply_markup"] = json.dumps(
                {
                    "keyboard": keyboard,
                    "resize_keyboard": True,
                    "one_time_keyboard": False,
                }
            )

        response = self.session.post(self._url("sendMessage"), json=payload, timeout=self.request_timeout)
        response.raise_for_status()
        return response.json()

    def send_chat_action(self, chat_id: int, action: str = "typing") -> None:
        payload = {"chat_id": chat_id, "action": action}
        response = self.session.post(self._url("sendChatAction"), data=payload, timeout=self.request_timeout)
        response.raise_for_status()

    def delete_webhook(self, drop_pending_updates: bool = False) -> Dict[str, Any]:
        payload = {"drop_pending_updates": str(drop_pending_updates).lower()}
        response = self.session.post(self._url("deleteWebhook"), data=payload, timeout=self.request_timeout)
        response.raise_for_status()
        return response.json()

    def get_file(self, file_id: str) -> Dict[str, Any]:
        response = self.session.get(self._url("getFile"), params={"file_id": file_id}, timeout=self.request_timeout)
        response.raise_for_status()
        return response.json()

    def download_file(self, file_path: str) -> bytes:
        file_url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        response = self.session.get(file_url, timeout=self.request_timeout)
        response.raise_for_status()
        return response.content
