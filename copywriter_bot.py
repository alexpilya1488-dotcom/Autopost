"""
Телеграм-бот-помощник для копирайтинга/фриланса: получает от вас бриф в
личке боту, готовит ЧЕРНОВИК текста (Gemini, с фолбэком на Groq — тот же
паттерн, что и в generate_fact.py), присылает обратно. Дальше вы сами
проверяете/правите и отправляете клиенту — бот не общается с клиентами,
никуда не публикует и не берёт заказы сам, только ускоряет черновик.

Отвечает ТОЛЬКО вам (TELEGRAM_USER_ID) — если боту напишет кто-то другой,
он промолчит и не станет тратить на это AI-квоту.

Как получить токен бота:
  1. В Telegram напишите @BotFather -> /newbot -> следуйте инструкциям.
  2. Выданный токен -> секрет GitHub TELEGRAM_BOT_TOKEN.

Как узнать свой chat_id (= TELEGRAM_USER_ID):
  1. Напишите что угодно своему новому боту (он пока не ответит — это ок,
     воркфлоу ещё не настроен).
  2. Открой в браузере: https://api.telegram.org/bot<ТВОЙ_ТОКЕН>/getUpdates
  3. В ответе найди "chat":{"id": ЧИСЛО, ...} — это и есть chat_id.
  4. Число -> секрет GitHub TELEGRAM_USER_ID.

Работает через long-polling с сохранением offset между запусками
(TELEGRAM_STATE_FILE, коммитится обратно воркфлоу-раннером — тот же
паттерн, что и edits_state.json). Раннер запускается по расписанию каждые
~15 минут (.github/workflows/copywriter-bot.yml) — задержка перед
черновиком в среднем в пределах этого интервала, без своего сервера.
"""

import json
import os

import requests

from generate_fact import _generate_with_gemini, _generate_with_groq

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
STATE_FILE = "telegram_copywriter_state.json"

COPY_PROMPT_TEMPLATE = """Ты — опытный копирайтер-фрилансер. Клиент прислал бриф на текст.
Подготовь ГОТОВЫЙ черновик текста по этому брифу — не план и не вопросы, а
финальный текст, который можно почти без правок отправить клиенту. Если в
брифе не хватает деталей (тон, объём, площадка) — сделай разумные
предположения сам и не проси уточнений, просто напиши.

Бриф от клиента:
---
{brief}
---

Верни ТОЛЬКО готовый текст черновика, без пояснений от себя и без
вводных фраз вида "Вот ваш текст:" — сразу сам текст.
"""


def _tg_call(method: str, **params) -> dict:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("Задай переменную окружения TELEGRAM_BOT_TOKEN")

    resp = requests.post(TELEGRAM_API.format(token=token, method=method), data=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API ошибка ({method}): {data}")
    return data["result"]


def _load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {"last_update_id": 0}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _draft_copy(brief: str) -> str:
    prompt = COPY_PROMPT_TEMPLATE.format(brief=brief)
    try:
        raw = _generate_with_gemini(prompt)
        used = "gemini"
    except Exception as gemini_error:
        print(f"   [!] Gemini недоступен ({gemini_error}). Переключаюсь на Groq...")
        raw = _generate_with_groq(prompt)
        used = "groq"
    print(f"   (черновик сгенерирован через: {used})")
    return raw.strip()


def run() -> None:
    allowed_user_id = os.environ.get("TELEGRAM_USER_ID")
    if not allowed_user_id:
        raise RuntimeError("Задай переменную окружения TELEGRAM_USER_ID")

    state = _load_state()
    # timeout=0 — короткий неблокирующий запрос: этот скрипт запускается по
    # расписанию как разовый прогон, а не живёт постоянно, поэтому обычный
    # long-poll (ожидание новых сообщений) тут не нужен и не нужен.
    updates = _tg_call("getUpdates", offset=state["last_update_id"] + 1, timeout=0)

    if not updates:
        print("Новых сообщений нет.")
        return

    for update in updates:
        state["last_update_id"] = update["update_id"]
        message = update.get("message")
        if not message or "text" not in message:
            continue

        chat_id = str(message["chat"]["id"])
        if chat_id != str(allowed_user_id):
            print(f"   [!] Игнорирую сообщение от постороннего chat_id={chat_id}")
            continue

        brief = message["text"]
        print(f"Бриф получен: {brief[:80]}...")
        _tg_call("sendMessage", chat_id=chat_id, text="Готовлю черновик...")

        try:
            draft = _draft_copy(brief)
        except Exception as e:
            _tg_call("sendMessage", chat_id=chat_id, text=f"Не получилось сгенерировать: {e}")
            continue

        _tg_call("sendMessage", chat_id=chat_id, text=draft)

    _save_state(state)


if __name__ == "__main__":
    run()
