"""Entry point for the Telegram + OpenAI bot."""

from bot import BotApp


def main() -> None:
    app = BotApp()
    app.run()


if __name__ == "__main__":
    main()
