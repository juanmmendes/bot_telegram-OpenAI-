from __future__ import annotations

import base64
import imghdr
import logging
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

import requests
from requests import HTTPError, RequestException

from .config import Settings, get_settings
from .openai_client import OpenAIClient
from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "Voce e um atendente virtual brasileiro, cordial e organizado, que responde sempre em portugues do Brasil. "
    "Mantenha um tom humano, empatico e claro, estruturando as respostas em paragrafos curtos ou listas quando ajudar na compreensao. "
    "Explique conceitos de forma simples, ofereca exemplos praticos quando fizer sentido e confirme se a pessoa ficou satisfeita com a solucao. "
    "Deixe claro que voce e um bot especializado em tirar duvidas e consultar cotacoes de moedas, entregando informacoes em tempo real sempre que for solicitado. "
    "Quando nao souber a resposta, admita a limitacao e sugira fontes confiaveis para pesquisa. "
    "Sempre que perguntarem sobre suas capacidades, informe que consegue entender mensagens escritas, audios (transcrevendo-os automaticamente) e imagens. "
    "Caso receba dados em tempo real (como cotacoes), incorpore-os de maneira clara destacando a fonte."
)

HELP_TEXT = (
    "Envie perguntas, audios ou imagens e eu responderei usando a API da OpenAI.\n"
    "Sou um bot tira-duvidas que tambem consulta cotacoes de moedas em tempo real, ideal para acompanhar dolar, euro e outras moedas.\n"
    "Audios sao transcritos automaticamente, imagens sao analisadas pelo modelo multimodal e voce pode usar o menu para verificar cotacoes a qualquer momento.\n"
    "\n"
    "Comandos disponiveis:\n"
    "/start - mensagem de boas-vindas\n"
    "/help - guia rapido\n"
    "/menu - exibe os atalhos principais\n"
    "/cotacoes - mostra as principais moedas em tempo real\n"
    "/reset - limpa o historico da conversa"
)

ABOUT_TEXT = (
    "Sou um bot de exemplo para trabalhos academicos integrando Telegram e OpenAI. "
    "Fui estruturado para ser facil de manter, seguro com variaveis de ambiente e pronto "
    "para evoluir com novas funcoes."
)

MENU_KEYBOARD = [
    ["Conversar com IA"],
    ["Verificar cotacoes"],
    ["Ajuda", "Resetar conversa"],
]

DEFAULT_CURRENCY_CODES = ["USD", "EUR", "GBP"]


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
        if command == "/cotacoes":
            self._send_currency_snapshot(chat_id, DEFAULT_CURRENCY_CODES, reply_to=message_id)
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
        if normalized == "verificar cotacoes":
            self._send_currency_snapshot(chat_id, DEFAULT_CURRENCY_CODES, reply_to=message_id)
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

        context = self._build_realtime_context(message)
        if context:
            self._append_context_to_message(message, context)

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
            "Ola! Eu sou seu assistente virtual integrado com a OpenAI, especializado em tirar duvidas e trazer cotacoes em tempo real. "
            "Posso explicar conceitos, trazer ideias para seus projetos e informar o valor atual de moedas como dolar, euro e mais. "
            "Use o menu para ver atalhos rapidos ou simplesmente me envie uma mensagem."
        )
        self.telegram.send_message(chat_id, welcome_text, reply_to=message_id)
        self._send_menu(chat_id)

    def _send_menu(self, chat_id: int) -> None:
        self.telegram.send_message(
            chat_id,
            "Selecione um atalho ou envie sua mensagem. O bot tambem pode verificar cotacoes em tempo real:",
            keyboard=MENU_KEYBOARD,
        )

    def _send_currency_snapshot(
        self,
        chat_id: int,
        codes: Sequence[str],
        reply_to: Optional[int] = None,
    ) -> None:
        try:
            context = self._fetch_currency_data(codes)
        except (RequestException, ValueError) as exc:
            logger.warning("Falha ao buscar cotacoes para menu: %s", exc)
            message = (
                "Nao consegui consultar as cotacoes agora. "
                "Tente novamente em instantes."
            )
            self.telegram.send_message(chat_id, message, reply_to=reply_to)
            return

        if not context:
            self.telegram.send_message(
                chat_id,
                "Nao encontrei cotacoes atualizadas neste momento, mas posso tentar novamente se voce quiser.",
                reply_to=reply_to,
            )
            return

        if context.startswith("[Contexto em tempo real]"):
            lines = context.splitlines()[1:]
            if lines and lines[0].lower().startswith("cotacoes consultadas"):
                lines = lines[1:]
            formatted = "\n".join(lines).strip()
        else:
            formatted = context.strip()

        if not formatted:
            formatted = "Nao recebi valores do servico externo desta vez."

        message = "Cotacoes em tempo real via AwesomeAPI:\n" + formatted
        self.telegram.send_message(chat_id, message, reply_to=reply_to)

    def _build_realtime_context(self, message: Dict[str, Any]) -> Optional[str]:
        content = message.get("content")
        text_fragments = self._extract_text_fragments(content)
        if not text_fragments:
            return None

        normalized = self._normalize_text(" ".join(text_fragments))
        currency_codes = self._detect_currency_codes(normalized)
        if not currency_codes:
            return None

        try:
            data_context = self._fetch_currency_data(currency_codes)
        except (RequestException, ValueError) as exc:  # pragma: no cover - external service may fail
            logger.warning("Falha ao buscar cotacoes: %s", exc)
            return (
                "[Contexto em tempo real]\n"
                "Solicitei cotacoes de moedas, mas o servico externo nao respondeu. "
                "Explique ao usuario que pode tentar novamente em instantes."
            )

        return data_context

    @staticmethod
    def _append_context_to_message(message: Dict[str, Any], context: str) -> None:
        if not context:
            return

        content = message.get("content")
        if isinstance(content, str):
            message["content"] = f"{content}\n\n{context}" if content else context
            return

        if isinstance(content, list):
            content.append({"type": "text", "text": context})
            return

        message["content"] = context

    @staticmethod
    def _extract_text_fragments(content: Any) -> List[str]:
        if isinstance(content, str):
            stripped = content.strip()
            return [stripped] if stripped else []

        fragments: List[str] = []
        if isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text_value = str(part.get("text", "")).strip()
                    if text_value:
                        fragments.append(text_value)
        return fragments

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = unicodedata.normalize("NFD", text)
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        return ascii_text.lower()

    @staticmethod
    def _detect_currency_codes(normalized_text: str) -> List[str]:
        keywords = {
            "dolar": "USD",
            "usd": "USD",
            "euro": "EUR",
            "eur": "EUR",
            "libra": "GBP",
            "gbp": "GBP",
            "iene": "JPY",
            "jpy": "JPY",
            "peso": "ARS",
            "ars": "ARS",
            "bitcoin": "BTC",
            "btc": "BTC",
        }

        detected: set[str] = set()
        for keyword, code in keywords.items():
            if keyword in normalized_text:
                detected.add(code)

        if "cotacao" in normalized_text or "cambio" in normalized_text:
            detected.update({"USD", "EUR"})

        return sorted(detected)

    def _fetch_currency_data(self, codes: Sequence[str]) -> Optional[str]:
        if not codes:
            return None

        pairs = ",".join(f"{code}-BRL" for code in codes)
        url = f"https://economia.awesomeapi.com.br/json/last/{pairs}"

        response = requests.get(url, timeout=self.settings.request_timeout)
        response.raise_for_status()
        payload = response.json()

        lines: List[str] = []
        timestamp_display: Optional[str] = None

        for code in codes:
            key = f"{code}BRL"
            info = payload.get(key)
            if not isinstance(info, dict):
                continue

            price_raw = info.get("bid") or info.get("ask")
            variation_raw = info.get("pctChange")
            update_reference = info.get("create_date") or info.get("timestamp")

            if price_raw is None:
                continue

            try:
                price_value = float(str(price_raw).replace(",", "."))
                price_text = f"R$ {price_value:.4f}"
            except (TypeError, ValueError):
                price_text = str(price_raw)

            variation_text = ""
            if variation_raw is not None:
                try:
                    variation_value = float(str(variation_raw).replace(",", "."))
                    variation_text = f" (variacao diaria: {variation_value:+.2f}%)"
                except (TypeError, ValueError):
                    variation_text = f" (variacao diaria: {variation_raw})"

            if update_reference and not timestamp_display:
                timestamp_display = self._format_timestamp(update_reference)

            lines.append(f"- {code}/BRL: {price_text}{variation_text}")

        if not lines:
            return None

        header = "[Contexto em tempo real]\nCotacoes consultadas via AwesomeAPI:"
        body = "\n".join(lines)
        if timestamp_display:
            return f"{header}\n{body}\nDados consultados em {timestamp_display}."
        return f"{header}\n{body}"

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        if isinstance(value, (int, float)):
            dt = datetime.fromtimestamp(float(value))
            return dt.strftime("%d/%m/%Y %H:%M:%S")

        text = str(value)
        if text.isdigit():
            try:
                dt = datetime.fromtimestamp(int(text))
                return dt.strftime("%d/%m/%Y %H:%M:%S")
            except (OSError, OverflowError, ValueError):
                return text

        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S%z"):
            try:
                dt = datetime.strptime(text, fmt)
                return dt.strftime("%d/%m/%Y %H:%M:%S")
            except ValueError:
                continue

        return text
