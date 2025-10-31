from __future__ import annotations

import io
import mimetypes
from typing import Any, Dict, List

from openai import OpenAI


class OpenAIClient:
    def __init__(self, api_key: str, model: str, transcription_model: str) -> None:
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.transcription_model = transcription_model

    def generate_reply(self, messages: List[Dict[str, Any]], temperature: float = 0.7) -> str:
        """Send the conversation to OpenAI and return the assistant reply."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=700,
        )
        return response.choices[0].message.content.strip()

    def transcribe_audio(self, data: bytes, mime_type: str | None = None) -> str:
        """Transcribe audio bytes using the configured OpenAI transcription model."""
        guessed_extension = self._extension_from_mime(mime_type)
        audio_buffer = io.BytesIO(data)
        filename = f"audio.{guessed_extension}"
        audio_buffer.name = filename
        audio_buffer.seek(0)

        if mime_type:
            file_payload = (filename, audio_buffer, mime_type)
        else:
            file_payload = (filename, audio_buffer)

        response = self.client.audio.transcriptions.create(
            model=self.transcription_model,
            file=file_payload,
        )

        # SDK retorna objeto com atributo text; fazemos fallback para dict/str
        text = getattr(response, "text", None)
        if text:
            return text.strip()
        if isinstance(response, dict):
            return str(response.get("text", "")).strip()
        if isinstance(response, str):
            return response.strip()
        return ""

    @staticmethod
    def _extension_from_mime(mime_type: str | None) -> str:
        if not mime_type:
            return "mp3"
        extension = mimetypes.guess_extension(mime_type)
        if extension:
            clean = extension.lstrip(".")
            if clean in {"oga", "ogg"}:
                return "ogg"
            return clean
        if mime_type == "audio/ogg":
            return "ogg"
        return "mp3"
