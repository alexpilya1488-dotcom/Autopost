"""
Постоянно работающий процесс для assistant_bot.py — держит бота "живым"
24/7 через long-polling с реальным ожиданием (не раз в 15 минут, как
GitHub Actions cron), что нужно для приёма Stars-платежей (Telegram
требует ответ на pre_checkout_query в течение 10 секунд).

Запускать на VPS через systemd, не вручную в терминале "навсегда" — см.
deploy/README.md для полной инструкции по установке и systemd-юниту
deploy/assistant-bot.service.

Локальный тест (без systemd):  python run_server.py
Остановка:                      Ctrl+C
"""

import time
import traceback

from assistant_bot import run

POLL_TIMEOUT = 25  # секунд ожидания новых сообщений в каждом long-poll запросе


def main() -> None:
    print("assistant_bot: запущен в постоянном режиме (long-polling)")
    while True:
        try:
            run(poll_timeout=POLL_TIMEOUT)
        except KeyboardInterrupt:
            print("Остановлено.")
            break
        except Exception:
            print("Ошибка в цикле опроса, продолжаю через 5с:")
            traceback.print_exc()
            time.sleep(5)


if __name__ == "__main__":
    main()
