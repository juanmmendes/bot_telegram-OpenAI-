"""Entry point and CLI for the Telegram + OpenAI bot."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Iterable

from bot import BotApp, get_settings
from bot.observability import MetricsRecorder
from bot.state_store import create_state_store


def _run_bot() -> None:
    app = BotApp()
    app.run()


def _load_metrics(path: str | None) -> Dict[str, Any]:
    if not path:
        return {}
    recorder = MetricsRecorder.from_file(path)
    return recorder.snapshot()


def _list_chats(path: str | None) -> Iterable[int]:
    store = create_state_store(path)
    return sorted(set(int(chat_id) for chat_id in store.list_chat_ids()))


def _reset_chat(path: str | None, chat_id: int) -> bool:
    store = create_state_store(path)
    try:
        store.delete(chat_id)
        return True
    except Exception:
        return False


def main(argv: Iterable[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ferramentas administrativas para o bot do Telegram.")
    parser.add_argument(
        "command",
        nargs="?",
        default="run",
        choices={"run", "stats", "list-chats", "reset-chat"},
        help="acao a executar (padrao: run)",
    )
    parser.add_argument("--json", action="store_true", help="exibe saida em JSON (para stats).")
    parser.add_argument("--chat-id", type=int, help="chat id usado em reset-chat.")

    args = parser.parse_args(list(argv) if argv is not None else None)
    settings = get_settings()

    if args.command == "run":
        _run_bot()
        return

    if args.command == "stats":
        metrics = _load_metrics(settings.metrics_file_path)
        if args.json:
            print(json.dumps(metrics, ensure_ascii=False, indent=2))
        else:
            if not metrics:
                print("Nenhum dado de metricas disponivel. Configure METRICS_FILE ou CHAT_STATE_DIR.", file=sys.stderr)
            else:
                total_updates = metrics.get("total_updates", 0)
                unique_chats = len(metrics.get("unique_chats", []))
                openai_stats = metrics.get("openai_calls", {})
                transcriptions = metrics.get("transcriptions", {})
                errors = metrics.get("errors", {})
                print(f"Total de updates processados: {total_updates}")
                print(f"Chats unicos atendidos: {unique_chats}")
                print(
                    "Chamadas OpenAI: {count} (prompt_tokens={prompt}, completion_tokens={completion})".format(
                        count=openai_stats.get("count", 0),
                        prompt=openai_stats.get("total_prompt_tokens", 0),
                        completion=openai_stats.get("total_completion_tokens", 0),
                    )
                )
                print(f"Transcricoes de audio: {transcriptions.get('count', 0)}")
                if errors:
                    print("Erros registrados:")
                    for kind, amount in errors.items():
                        print(f"  - {kind}: {amount}")
        return

    if args.command == "list-chats":
        chats = _list_chats(settings.chat_state_dir)
        if not chats:
            print("Nenhum estado persistido encontrado.")
        else:
            for chat_id in chats:
                print(chat_id)
        return

    if args.command == "reset-chat":
        if args.chat_id is None:
            parser.error("--chat-id eh obrigatorio para reset-chat")
        success = _reset_chat(settings.chat_state_dir, args.chat_id)
        if success:
            print(f"Estado do chat {args.chat_id} removido.")
        else:
            print(f"Nao foi possivel remover o estado do chat {args.chat_id}.", file=sys.stderr)
        return


if __name__ == "__main__":
    main()
