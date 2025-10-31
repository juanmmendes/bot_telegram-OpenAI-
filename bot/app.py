from __future__ import annotations

import base64
import imghdr
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from requests import HTTPError

from .config import Settings, get_settings
from .openai_client import OpenAIClient
from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "Voce e um assistente virtual universitario que responde sempre em portugues do Brasil. "
    "Use um tom acolhedor e objetivo, explique conceitos de forma simples e ofereca exemplos "
    "quando fizer sentido. Caso nao saiba a resposta, admita e sugira caminhos para pesquisar."
)

HELP_TEXT = (
    "Envie perguntas, audios ou imagens e eu responderei usando a API da OpenAI.\n"
    "Audios sao transcritos automaticamente e imagens sao analisadas pelo modelo multimodal.\n"
    "\n"
    "Comandos disponiveis:\n"
    "/start - mensagem de boas-vindas\n"
    "/help - guia rapido\n"
    "/menu - exibe os atalhos principais\n"
    "/reset - limpa o historico da conversa"
)

ABOUT_TEXT = (
    "Sou um bot de exemplo para trabalhos academicos integrando Telegram e OpenAI. "
    "Fui estruturado para ser facil de manter, seguro com variaveis de ambiente e pronto "
    "para evoluir com novas funcoes."
)

MENU_KEYBOARD = [
    ["Conversar com IA"],
    ["Ajuda", "Resetar conversa"],
]


@dataclass
class ChatState:
    messages: List[Dict[str, Any]] = field(default_factory=list)
    pending_parts: List[Dict[str, Any]] = field(default_factory=list)
    last_message_id: Optional[int] = None
    last_update_ts: Optional[float] = None
    waiting_reply: bool = False

    MAX_HISTORY: int = 10

    def __post_init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.pending_parts.clear()
        self.last_message_id = None
        self.last_update_ts = None
        self.waiting_reply = False

    def queue_text(self, content: str) -> None:
        text = content.strip()
        if not text:
            return
        self._queue_part({"type": "text", "text": text})

    def queue_image(self, image_b64: str, caption: Optional[str] = None, mime_type: str = "image/jpeg") -> None:
        if caption:
            self.queue_text(caption)
        data_url = f"data:{mime_type};base64,{image_b64}"
        self._queue_part({"type": "image_url", "image_url": {"url": data_url}})

    def _queue_part(self, part: Dict[str, Any]) -> None:
        self.pending_parts.append(part)
        self.last_update_ts = time.time()
        self.waiting_reply = True

    def add_assistant(self, content: str) -> None:
        self.messages.append({"role": "assistant", "content": content})
        self._trim()

    def consume_pending(self) -> Optional[Dict[str, Any]]:
        if not self.pending_parts:
            return None
        merged_parts: List[Dict[str, Any]] = []
        text_buffer: List[str] = []

        for part in self.pending_parts:
            if part.get("type") == "text":
                text_buffer.append(part["text"])
            else:
                if text_buffer:
                    merged_parts.append({"type": "text", "text": "\n".join(text_buffer)})
                    text_buffer = []
                merged_parts.append(part)

        if text_buffer:
            merged_parts.append({"type": "text", "text": "\n".join(text_buffer)})

        self.pending_parts.clear()
        self.waiting_reply = False

        if len(merged_parts) == 1 and merged_parts[0]["type"] == "text":
            content: Any = merged_parts[0]["text"]
        else:
            content = merged_parts

        message = {"role": "user", "content": content}
        self.messages.append(message)
        self._trim()
        return message

    def should_flush(self, buffer_seconds: float) -> bool:
        if not self.waiting_reply or not self.pending_parts:
            return False
        if self.last_update_ts is None:
            return False
        return time.time() - self.last_update_ts >= buffer_seconds

    def _trim(self) -> None:
        system_message = self.messages[0]
        history = self.messages[1:]
        if len(history) > self.MAX_HISTORY:
            history = history[-self.MAX_HISTORY :]
        self.messages = [system_message] + history


class BotApp:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.telegram = TelegramClient(
            token=self.settings.telegram_bot_token,
            request_timeout=self.settings.request_timeout,
        )
        self.openai = OpenAIClient(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_model,
            transcription_model=self.settings.openai_transcription_model,
        )
        self.response_buffer_seconds = self.settings.response_buffer_seconds
        self.chat_states: Dict[int, ChatState] = {}

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
        logger.info("Bot iniciado. Aguardando mensagens...")
        offset: int | None = None

        try:
            self.telegram.delete_webhook()
            logger.info("Webhook removido (modo polling habilitado).")
        except HTTPError as exc:
            logger.warning("Nao foi possivel remover o webhook: %s", exc)

        while True:
            try:
                self._flush_buffers_if_needed()
                timeout = self._select_timeout()
                try:
                    updates = self.telegram.get_updates(offset=offset, timeout=timeout)
                except HTTPError as exc:
                    if exc.response is not None and exc.response.status_code == 409:
                        logger.warning("Conflito 409 detectado. Tentando remover webhook e repetindo polling.")
                        self.telegram.delete_webhook()
                        time.sleep(1)
                        continue
                    raise
                if updates.get("ok", False):
                    for update in updates.get("result", []):
                        offset = update["update_id"] + 1
                        self._handle_update(update)
                else:
                    time.sleep(1)
                self._flush_buffers_if_needed()
            except KeyboardInterrupt:
                logger.info("Interrupcao solicitada pelo usuario. Encerrando...")
                break
            except Exception as exc:
                logger.exception("Erro no loop principal: %s", exc)
                time.sleep(1.5)
                self._flush_buffers_if_needed()

    def _handle_update(self, update: Dict[str, object]) -> None:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, dict):
            return

        chat = message.get("chat")
        if not isinstance(chat, dict) or "id" not in chat:
            return

        chat_id = int(chat["id"])
        message_id = int(message.get("message_id", 0))
        state = self.chat_states.setdefault(chat_id, ChatState())
        state.last_message_id = message_id

        text = (message.get("text") or "").strip()
        caption = (message.get("caption") or "").strip()

        command_text = text or caption
        if command_text.startswith("/"):
            self._handle_command(chat_id, message_id, command_text, state)
            return

        if text and self._handle_shortcut(chat_id, message_id, text, state):
            return

        media_handled = False
        media_handled = self._process_voice_message(chat_id, message, state) or media_handled
        media_handled = self._process_image_message(chat_id, message, state) or media_handled

        if text and not media_handled:
            state.queue_text(text)

    def _handle_command(self, chat_id: int, message_id: int, text: str, state: ChatState) -> None:
        command = text.split()[0].lower()
        if command == "/start":
            self._send_welcome(chat_id, message_id)
            return
        if command == "/help":
            self.telegram.send_message(chat_id, HELP_TEXT, reply_to=message_id)
            return
        if command == "/menu":
            self._send_menu(chat_id)
            return
        if command == "/reset":
            state.reset()
            self.telegram.send_message(chat_id, "Historico apagado. Podemos recomecar!", reply_to=message_id)
            return
        if command == "/sobre":
            self.telegram.send_message(chat_id, ABOUT_TEXT, reply_to=message_id)
            return

        self.telegram.send_message(chat_id, "Comando nao reconhecido. Use /help para ver as opcoes.", reply_to=message_id)

    def _handle_shortcut(self, chat_id: int, message_id: int, text: str, state: ChatState) -> bool:
        normalized = text.lower()
        if normalized == "ajuda":
            self.telegram.send_message(chat_id, HELP_TEXT, reply_to=message_id)
            return True
        if normalized == "resetar conversa":
            state.reset()
            self.telegram.send_message(chat_id, "Historico apagado. Pode mandar sua proxima pergunta!", reply_to=message_id)
            return True
        if normalized == "conversar com ia":
            self.telegram.send_message(chat_id, "Ok, me conte como posso ajudar hoje.", reply_to=message_id)
            return True
        return False

    def _flush_buffers_if_needed(self) -> None:
        for chat_id, state in list(self.chat_states.items()):
            if state.should_flush(self.response_buffer_seconds):
                self._reply_with_buffer(chat_id, state)

    def _select_timeout(self) -> int:
        if any(state.waiting_reply for state in self.chat_states.values()):
            short_timeout = max(1, int(self.response_buffer_seconds))
            return min(self.settings.polling_timeout, short_timeout)
        return self.settings.polling_timeout

    def _reply_with_buffer(self, chat_id: int, state: ChatState) -> None:
        message = state.consume_pending()
        if not message:
            return

        self.telegram.send_chat_action(chat_id, "typing")

        try:
            reply = self.openai.generate_reply(state.messages)
        except Exception as exc:
            logger.exception("Falha ao chamar a OpenAI: %s", exc)
            fallback = (
                "Tive um problema para falar com a IA agora. "
                "Tente novamente em instantes ou envie a mensagem mais tarde."
            )
            self.telegram.send_message(chat_id, fallback, reply_to=state.last_message_id)
            return

        state.add_assistant(reply)
        self.telegram.send_message(chat_id, reply, reply_to=state.last_message_id, parse_mode=None)

    def _process_voice_message(self, chat_id: int, message: Dict[str, Any], state: ChatState) -> bool:
        voice_payload = message.get("voice") or message.get("audio")
        if not isinstance(voice_payload, dict):
            return False

        file_id = voice_payload.get("file_id")
        if not file_id:
            return False

        mime_type = voice_payload.get("mime_type") or "audio/ogg"
        caption = (message.get("caption") or "").strip()
        try:
            audio_bytes = self._download_file_bytes(file_id)
            transcription = self.openai.transcribe_audio(audio_bytes, mime_type)
        except Exception as exc:
            logger.exception("Erro ao processar audio: %s", exc)
            self.telegram.send_message(
                chat_id,
                "Nao consegui entender o audio agora. Pode tentar novamente ou enviar em texto?",
                reply_to=state.last_message_id,
            )
            return True

        transcript_text = transcription or "Audio recebido, mas a transcricao veio vazia."
        if caption:
            state.queue_text(caption)
        state.queue_text(f"[Audio do usuario]\n{transcript_text}")
        return True

    def _process_image_message(self, chat_id: int, message: Dict[str, Any], state: ChatState) -> bool:
        photos = message.get("photo")
        document = message.get("document")
        caption = (message.get("caption") or "").strip()
        handled = False

        if isinstance(photos, list) and photos:
            photo_info = photos[-1]
            handled = self._queue_image_from_file(chat_id, photo_info, caption, state) or handled

        if isinstance(document, dict):
            mime_type = document.get("mime_type", "")
            if mime_type.startswith("image/"):
                handled = self._queue_image_from_file(chat_id, document, caption, state) or handled

        return handled

    def _queue_image_from_file(
        self,
        chat_id: int,
        file_info: Dict[str, Any],
        caption: str,
        state: ChatState,
    ) -> bool:
        file_id = file_info.get("file_id")
        if not file_id:
            return False

        try:
            image_bytes = self._download_file_bytes(file_id)
            image_b64 = base64.b64encode(image_bytes).decode("ascii")
        except Exception as exc:
            logger.exception("Erro ao baixar imagem: %s", exc)
            self.telegram.send_message(
                chat_id,
                "Nao consegui abrir a imagem que voce enviou. Pode tentar novamente?",
                reply_to=state.last_message_id,
            )
            return True

        prompt = caption or "Analise a imagem enviada e comente os pontos principais."
        mime_type = self._guess_image_mime(file_info.get("mime_type"), image_bytes)
        state.queue_image(image_b64, prompt, mime_type)
        return True

    def _download_file_bytes(self, file_id: str) -> bytes:
        file_data = self.telegram.get_file(file_id)
        if not file_data.get("ok"):
            raise RuntimeError("Telegram retornou erro ao buscar o arquivo.")

        result = file_data.get("result") or {}
        file_path = result.get("file_path")
        if not file_path:
            raise RuntimeError("Telegram nao retornou file_path.")

        return self.telegram.download_file(file_path)

    @staticmethod
    def _guess_image_mime(declared_mime: Optional[str], data: bytes, fallback: str = "image/jpeg") -> str:
        if declared_mime:
            return declared_mime
        detected = imghdr.what(None, data)
        mapping = {
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "bmp": "image/bmp",
            "tiff": "image/tiff",
            "webp": "image/webp",
        }
        if detected:
            return mapping.get(detected, fallback)
        return fallback

    def _send_welcome(self, chat_id: int, message_id: int) -> None:
        welcome_text = (
            "Ola! Eu sou seu assistente virtual integrado com a OpenAI. "
            "Posso tirar duvidas, explicar conceitos ou dar ideias para seus projetos. "
            "Use o menu para ver atalhos rapidos ou simplesmente me envie uma mensagem."
        )
        self.telegram.send_message(chat_id, welcome_text, reply_to=message_id)
        self._send_menu(chat_id)

    def _send_menu(self, chat_id: int) -> None:
        self.telegram.send_message(
            chat_id,
            "Selecione um atalho ou envie sua mensagem:",
            keyboard=MENU_KEYBOARD,
        )
