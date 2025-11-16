from __future__ import annotations

import base64
import imghdr
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from requests import HTTPError, RequestException

from .config import Settings, get_settings
from .observability import MetricsRecorder
from .openai_client import OpenAIClient
from .services import CurrencyService
from .state_store import BaseStateStore, create_state_store
from .telegram_client import TelegramClient

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = (
    "Voce e um atendente virtual brasileiro, cordial e organizado, que responde sempre em portugues do Brasil. "
    "Mantenha um tom humano, empatico e claro, estruturando as respostas em paragrafos curtos ou listas quando ajudar na compreensao. "
    "Explique conceitos de forma simples, ofereca exemplos praticos quando fizer sentido e confirme se a pessoa ficou satisfeita com a solucao. "
    "Deixe claro que voce e um bot especializado em tirar duvidas e consultar cotacoes de moedas, entregando informacoes em tempo real sempre que for solicitado. "
    "Quando nao souber a resposta, admita a limitacao e sugira fontes confiaveis para pesquisa. "
    "Sempre que perguntarem sobre suas capacidades, informe que consegue entender mensagens escritas, audios (transcrevendo-os automaticamente) e imagens. "
    "Caso receba dados em tempo real (como cotacoes), incorpore-os de maneira clara destacando a fonte. "
    "Ao receber cotacoes antigas do Banco Central (PTAX), lembre o usuario da data solicitada e que os valores sao oficiais."
)

HELP_TEXT = (
    "Envie perguntas, audios ou imagens e eu responderei usando a API da OpenAI.\n"
    "Sou um bot tira-duvidas que tambem consulta cotacoes de moedas em tempo real, ideal para acompanhar dolar, euro e outras moedas.\n"
    "Para valores passados, mencione a moeda e a data (ex.: 'cotacao do dolar em 03/06/2024') que busco a PTAX oficial do Banco Central.\n"
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

    def to_dict(self) -> Dict[str, Any]:
        return {
            "messages": self.messages,
            "pending_parts": self.pending_parts,
            "last_message_id": self.last_message_id,
            "last_update_ts": self.last_update_ts,
            "waiting_reply": self.waiting_reply,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ChatState":
        instance = cls()
        instance.messages = payload.get("messages") or [{"role": "system", "content": SYSTEM_PROMPT}]
        instance.pending_parts = payload.get("pending_parts", [])
        instance.last_message_id = payload.get("last_message_id")
        instance.last_update_ts = payload.get("last_update_ts")
        instance.waiting_reply = payload.get("waiting_reply", False)
        instance._trim()
        return instance

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
        self.metrics = MetricsRecorder(self.settings.metrics_file_path)
        self.state_store: BaseStateStore = create_state_store(self.settings.chat_state_dir)
        self.currency = CurrencyService(request_timeout=self.settings.request_timeout)
        self.telegram = TelegramClient(
            token=self.settings.telegram_bot_token,
            request_timeout=self.settings.request_timeout,
        )
        self.openai = OpenAIClient(
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_model,
            transcription_model=self.settings.openai_transcription_model,
            metrics=self.metrics,
        )
        self.response_buffer_seconds = self.settings.response_buffer_seconds
        self.chat_states: Dict[int, ChatState] = {}
        self._hydrate_states()

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
                self.metrics.record_error("main_loop_exception")
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
        self.metrics.record_update(chat_id)
        logger.info("Mensagem recebida", extra={"chat_id": chat_id, "message_id": message_id})

        state = self._get_chat_state(chat_id)
        state.last_message_id = message_id

        text = (message.get("text") or "").strip()
        caption = (message.get("caption") or "").strip()

        command_text = text or caption
        if command_text.startswith("/"):
            if self._handle_command(chat_id, message_id, command_text, state):
                self._persist_state(chat_id, state)
            return

        if text and self._handle_shortcut(chat_id, message_id, text, state):
            self._persist_state(chat_id, state)
            return

        state_mutated = False
        media_handled = False
        voice_handled = self._process_voice_message(chat_id, message, state)
        media_handled = voice_handled or media_handled
        state_mutated = state_mutated or voice_handled
        image_handled = self._process_image_message(chat_id, message, state)
        media_handled = image_handled or media_handled
        state_mutated = state_mutated or image_handled

        if text and not media_handled:
            state.queue_text(text)
            state_mutated = True

        if state_mutated:
            self._persist_state(chat_id, state)

    def _handle_command(self, chat_id: int, message_id: int, text: str, state: ChatState) -> bool:
        command = text.split()[0].lower()
        if command == "/start":
            self._send_welcome(chat_id, message_id)
            return False
        if command == "/help":
            self.telegram.send_message(chat_id, HELP_TEXT, reply_to=message_id)
            return False
        if command == "/menu":
            self._send_menu(chat_id)
            return False
        if command == "/cotacoes":
            self._send_currency_snapshot(chat_id, DEFAULT_CURRENCY_CODES, reply_to=message_id)
            return False
        if command == "/reset":
            state.reset()
            self.telegram.send_message(chat_id, "Historico apagado. Podemos recomecar!", reply_to=message_id)
            return True
        if command == "/sobre":
            self.telegram.send_message(chat_id, ABOUT_TEXT, reply_to=message_id)
            return False

        self.telegram.send_message(chat_id, "Comando nao reconhecido. Use /help para ver as opcoes.", reply_to=message_id)
        return False

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

    def _hydrate_states(self) -> None:
        for chat_id in self.state_store.list_chat_ids():
            payload = self.state_store.load(chat_id)
            if not payload:
                continue
            try:
                self.chat_states[chat_id] = ChatState.from_dict(payload)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.warning("Falha ao carregar estado do chat %s: %s", chat_id, exc)

    def _get_chat_state(self, chat_id: int) -> ChatState:
        state = self.chat_states.get(chat_id)
        if state:
            return state
        payload = self.state_store.load(chat_id)
        if payload:
            try:
                state = ChatState.from_dict(payload)
            except Exception as exc:  # pragma: no cover - defensive path
                logger.warning("Estado serializado invalido para chat %s: %s", chat_id, exc)
                state = ChatState()
        else:
            state = ChatState()
        self.chat_states[chat_id] = state
        return state

    def _persist_state(self, chat_id: int, state: ChatState) -> None:
        try:
            self.state_store.save(chat_id, state.to_dict())
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Nao foi possivel persistir estado do chat %s: %s", chat_id, exc)

    def _delete_state(self, chat_id: int) -> None:
        self.chat_states.pop(chat_id, None)
        try:
            self.state_store.delete(chat_id)
        except Exception as exc:  # pragma: no cover - defensive path
            logger.warning("Falha ao remover estado persistido do chat %s: %s", chat_id, exc)

    def _reply_with_buffer(self, chat_id: int, state: ChatState) -> None:
        message = state.consume_pending()
        if not message:
            return

        self._persist_state(chat_id, state)

        context = self._build_realtime_context(message)
        if context:
            self._append_context_to_message(message, context)

        self.telegram.send_chat_action(chat_id, "typing")

        try:
            reply = self.openai.generate_reply(state.messages)
        except Exception as exc:
            logger.exception("Falha ao chamar a OpenAI: %s", exc)
            self.metrics.record_error("openai_call")
            fallback = (
                "Tive um problema para falar com a IA agora. "
                "Tente novamente em instantes ou envie a mensagem mais tarde."
            )
            self.telegram.send_message(chat_id, fallback, reply_to=state.last_message_id)
            return

        state.add_assistant(reply)
        self._persist_state(chat_id, state)
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
            self.metrics.record_error("audio_processing")
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
            self.metrics.record_error("image_processing")
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
            context = self.currency.fetch_currency_snapshot(codes)
        except (RequestException, ValueError) as exc:
            logger.warning("Falha ao buscar cotacoes para menu: %s", exc)
            self.metrics.record_error("currency_lookup")
            message = (
                "Nao consegui consultar as cotacoes agora. "
                "Tente novamente em instantes."
            )
            self.telegram.send_message(chat_id, message, reply_to=reply_to)
            return

        if not context:
            self.metrics.record_error("currency_lookup_empty")
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

        reference_date = self._detect_reference_date(normalized)
        if reference_date:
            today = datetime.now().date()
            reference_display = reference_date.strftime("%d/%m/%Y")

            if reference_date > today:
                return (
                    "[Contexto historico]\n"
                    f"O usuario pediu cotacoes para {reference_display}, uma data futura. "
                    "Explique que apenas datas ate hoje estao disponiveis."
                )

            try:
                historical_context = self.currency.fetch_historical_snapshot(currency_codes, reference_date)
            except (RequestException, ValueError) as exc:  # pragma: no cover - external service may fail
                logger.warning("Falha ao buscar cotacoes historicas: %s", exc)
                self.metrics.record_error("currency_context_ptax")
                return (
                    "[Contexto historico]\n"
                    f"Tentei consultar o Banco Central para {reference_display}, mas ocorreu um erro externo. "
                    "Avise que o usuario pode tentar novamente em instantes."
                )

            if historical_context:
                return historical_context

            self.metrics.record_error("currency_context_ptax_empty")
            return (
                "[Contexto historico]\n"
                f"Nao encontrei cotacoes oficiais do Banco Central para {reference_display} apos checar alguns dias uteis. "
                "Explique que apenas datas uteis com divulgacao da PTAX estao disponiveis."
            )

        try:
            data_context = self.currency.fetch_currency_snapshot(currency_codes)
        except (RequestException, ValueError) as exc:  # pragma: no cover - external service may fail
            logger.warning("Falha ao buscar cotacoes: %s", exc)
            self.metrics.record_error("currency_context")
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
    def _detect_reference_date(normalized_text: str) -> Optional[date]:
        relative_keywords = (("anteontem", 2), ("ontem", 1))
        today = datetime.now().date()
        for keyword, days in relative_keywords:
            if keyword in normalized_text:
                return today - timedelta(days=days)

        def normalize_year(token: str) -> int:
            value = int(token)
            if value < 100:
                return 2000 + value if value < 50 else 1900 + value
            return value

        def build_date(day_token: str, month_token: str, year_token: str) -> Optional[date]:
            try:
                year_value = normalize_year(year_token)
                return date(year_value, int(month_token), int(day_token))
            except ValueError:
                return None

        match = re.search(r"\b(\d{1,2})[\/\.-](\d{1,2})[\/\.-](\d{2,4})\b", normalized_text)
        if match:
            candidate = build_date(match.group(1), match.group(2), match.group(3))
            if candidate:
                return candidate

        match = re.search(r"\b(\d{4})[\/\.-](\d{1,2})[\/\.-](\d{1,2})\b", normalized_text)
        if match:
            try:
                candidate = date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            except ValueError:
                candidate = None
            if candidate:
                return candidate

        month_names = {
            "janeiro": 1,
            "fevereiro": 2,
            "marco": 3,
            "abril": 4,
            "maio": 5,
            "junho": 6,
            "julho": 7,
            "agosto": 8,
            "setembro": 9,
            "outubro": 10,
            "novembro": 11,
            "dezembro": 12,
        }
        match = re.search(
            r"\b(\d{1,2})\s+de\s+(janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})",
            normalized_text,
        )
        if match:
            day_token, month_name, year_token = match.groups()
            month_value = month_names.get(month_name)
            if month_value:
                try:
                    candidate = date(int(year_token), month_value, int(day_token))
                except ValueError:
                    candidate = None
                if candidate:
                    return candidate

        return None

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

