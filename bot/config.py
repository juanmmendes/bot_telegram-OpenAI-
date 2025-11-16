from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    openai_api_key: str
    openai_model: str = "gpt-4o-mini"
    polling_timeout: int = 25
    request_timeout: int = 20
    response_buffer_seconds: float = 2.5
    openai_transcription_model: str = "gpt-4o-mini-transcribe"
    chat_state_dir: Optional[str] = None
    metrics_file_path: Optional[str] = None


def get_settings(env_path: Optional[str] = None) -> Settings:
    """Load configuration from environment variables."""
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    openai_model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    transcription_model = os.getenv("OPENAI_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe").strip() or "gpt-4o-mini-transcribe"
    buffer_value = os.getenv("RESPONSE_BUFFER_SECONDS", "").strip()
    chat_state_dir = os.getenv("CHAT_STATE_DIR", "").strip() or None
    metrics_file_path = os.getenv("METRICS_FILE", "").strip() or None

    if buffer_value:
        try:
            response_buffer_seconds = float(buffer_value)
        except ValueError as exc:
            raise RuntimeError("RESPONSE_BUFFER_SECONDS deve ser um numero (ex.: 2.5).") from exc
    else:
        response_buffer_seconds = 2.5

    if not metrics_file_path and chat_state_dir:
        metrics_file_path = str(Path(chat_state_dir) / "metrics.json")

    missing = []
    if not telegram_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not openai_api_key:
        missing.append("OPENAI_API_KEY")

    if missing:
        missing_vars = ", ".join(missing)
        raise RuntimeError(
            f"Missing required environment variables: {missing_vars}. "
            "Create a .env file or export the variables before running the bot."
        )

    return Settings(
        telegram_bot_token=telegram_token,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        response_buffer_seconds=response_buffer_seconds,
        openai_transcription_model=transcription_model,
        chat_state_dir=chat_state_dir,
        metrics_file_path=metrics_file_path,
    )
