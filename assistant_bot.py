"""
Публичный многопользовательский Telegram-бот: резюме/сопроводительные
письма + редактор-корректор текста. В отличие от copywriter_bot.py (личный
инструмент, отвечает только владельцу) — этот бот открыт для всех: любой
может написать и получить готовый текст.

Монетизация (пока без Stars-платежей — см. докстринг про 10-секундный SLA
pre_checkout_query, для этого нужен постоянно работающий бот, не по
расписанию): бесплатный дневной лимит на пользователя + бонусные генерации
за рефералов. Оплата будет добавлена отдельным шагом, когда решится вопрос
с постоянным хостингом.

Команды:
  /start [ref_ID]  — приветствие; если пришли по реферальной ссылке
                     ?start=ref_<ID> — пригласившему начисляется бонус
  /resume <текст>  — готовое резюме/сопроводительное по описанию
  /edit <текст>    — вычитанный/улучшенный вариант текста

Как получить токен бота — тот же способ, что и для copywriter_bot.py
(через @BotFather), но это ДРУГОЙ, отдельный бот — секрет:
  ASSISTANT_BOT_TOKEN

Работает через long-polling с сохранением состояния (лимиты, рефералы,
offset) между запусками (ASSISTANT_STATE_FILE, коммитится обратно
воркфлоу-раннером — тот же паттерн, что и у остальных ботов в репозитории).
Раннер — cron каждые ~15 минут (.github/workflows/assistant-bot.yml) +
workflow_dispatch.
"""

import json
import os
from datetime import date, datetime, timezone

import requests

from generate_fact import _generate_with_gemini, _generate_with_groq

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
STATE_FILE = "assistant_bot_state.json"

FREE_DAILY_LIMIT = 3       # бесплатных генераций в день на пользователя
REFERRAL_BONUS = 3         # бонусных генераций пригласившему за каждого нового реферала
REFERRAL_WELCOME_BONUS = 2  # бонус новому пользователю, если он пришёл по реферальной ссылке

RESUME_PROMPT_TEMPLATE = """Ты — опытный HR-копирайтер. Составь ГОТОВЫЙ текст резюме или
сопроводительного письма (определи по контексту, что просят, если не
сказано явно — сделай резюме) на основе информации ниже. Профессиональный,
но живой тон, без канцелярита и воды. Если каких-то деталей не хватает —
сделай разумные предположения сам, не проси уточнений.

Информация от пользователя:
---
{brief}
---

Верни ТОЛЬКО готовый текст, без пояснений от себя и вводных фраз.
"""

EDIT_PROMPT_TEMPLATE = """Ты — опытный редактор и корректор текста. Улучши текст ниже: исправь
ошибки (орфография, пунктуация, грамматика), убери канцелярит и воду,
сохрани смысл, факты и авторский стиль — не переписывай радикально,
именно вычитывай и улучшай.

Текст:
---
{brief}
---

Верни ТОЛЬКО исправленный текст, без пояснений от себя, без списка правок.
"""

WELCOME_TEXT = """Привет! Я помогаю быстро готовить тексты:

/resume <опиши себя или вакансию> — готовое резюме или сопроводительное письмо
/edit <текст> — вычитка и улучшение текста

Бесплатно: {free_limit} генерации в день. Хочешь больше — приглашай друзей:
за каждого, кто зайдёт по твоей ссылке, +{referral_bonus} генераций.

Твоя реферальная ссылка:
{referral_link}
"""

NO_QUOTA_TEXT = """Лимит на сегодня закончился (бесплатно {free_limit}/день).
Пригласи друга по ссылке — получишь +{referral_bonus} генераций:
{referral_link}

Или возвращайся завтра, лимит обновится."""


def _tg_call(method: str, **params) -> dict:
    token = os.environ.get("ASSISTANT_BOT_TOKEN")
    if not token:
        raise RuntimeError("Задай переменную окружения ASSISTANT_BOT_TOKEN")

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
    return {"last_update_id": 0, "users": {}}


def _save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _get_user(state: dict, user_id: str) -> dict:
    today = date.today().isoformat()
    user = state["users"].setdefault(user_id, {
        "date": today, "used_today": 0, "bonus_uses": 0,
        "referred_by": None, "referral_count": 0,
    })
    if user["date"] != today:
        user["date"] = today
        user["used_today"] = 0
    return user


def _has_quota(user: dict) -> bool:
    return user["used_today"] < FREE_DAILY_LIMIT or user["bonus_uses"] > 0


def _consume_quota(user: dict) -> None:
    if user["used_today"] < FREE_DAILY_LIMIT:
        user["used_today"] += 1
    else:
        user["bonus_uses"] -= 1


def _referral_link(bot_username: str, user_id: str) -> str:
    return f"https://t.me/{bot_username}?start=ref_{user_id}"


def _generate(prompt_template: str, brief: str) -> str:
    prompt = prompt_template.format(brief=brief)
    try:
        raw = _generate_with_gemini(prompt)
        used = "gemini"
    except Exception as gemini_error:
        print(f"   [!] Gemini недоступен ({gemini_error}). Переключаюсь на Groq...")
        raw = _generate_with_groq(prompt)
        used = "groq"
    print(f"   (сгенерировано через: {used})")
    return raw.strip()


def _handle_start(chat_id: str, payload: str | None, state: dict, bot_username: str) -> None:
    is_new = chat_id not in state["users"]
    user = _get_user(state, chat_id)

    if is_new and payload and payload.startswith("ref_"):
        referrer_id = payload[len("ref_"):]
        if referrer_id and referrer_id != chat_id:
            referrer = _get_user(state, referrer_id)
            referrer["bonus_uses"] += REFERRAL_BONUS
            referrer["referral_count"] += 1
            user["referred_by"] = referrer_id
            user["bonus_uses"] += REFERRAL_WELCOME_BONUS
            print(f"   Реферал: {chat_id} пришёл от {referrer_id}, начислены бонусы")

    text = WELCOME_TEXT.format(
        free_limit=FREE_DAILY_LIMIT,
        referral_bonus=REFERRAL_BONUS,
        referral_link=_referral_link(bot_username, chat_id),
    )
    _tg_call("sendMessage", chat_id=chat_id, text=text)


def _handle_service(chat_id: str, prompt_template: str, brief: str, state: dict, bot_username: str) -> None:
    user = _get_user(state, chat_id)
    if not brief.strip():
        _tg_call("sendMessage", chat_id=chat_id, text="Добавь текст после команды, например:\n/resume Python-разработчик, 3 года опыта...")
        return
    if not _has_quota(user):
        text = NO_QUOTA_TEXT.format(
            free_limit=FREE_DAILY_LIMIT,
            referral_bonus=REFERRAL_BONUS,
            referral_link=_referral_link(bot_username, chat_id),
        )
        _tg_call("sendMessage", chat_id=chat_id, text=text)
        return

    _tg_call("sendMessage", chat_id=chat_id, text="Готовлю...")
    try:
        result = _generate(prompt_template, brief)
    except Exception as e:
        _tg_call("sendMessage", chat_id=chat_id, text=f"Не получилось сгенерировать: {e}")
        return

    _consume_quota(user)
    _tg_call("sendMessage", chat_id=chat_id, text=result)


def run() -> None:
    bot_username = os.environ.get("ASSISTANT_BOT_USERNAME")
    if not bot_username:
        me = _tg_call("getMe")
        bot_username = me["username"]

    state = _load_state()
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
        text = message["text"].strip()
        print(f"Сообщение от {chat_id}: {text[:80]}...")

        if text.startswith("/start"):
            parts = text.split(maxsplit=1)
            payload = parts[1].strip() if len(parts) > 1 else None
            _handle_start(chat_id, payload, state, bot_username)
        elif text.startswith("/resume"):
            brief = text[len("/resume"):].strip()
            _handle_service(chat_id, RESUME_PROMPT_TEMPLATE, brief, state, bot_username)
        elif text.startswith("/edit"):
            brief = text[len("/edit"):].strip()
            _handle_service(chat_id, EDIT_PROMPT_TEMPLATE, brief, state, bot_username)
        else:
            _tg_call("sendMessage", chat_id=chat_id, text="Не понял команду. Напиши /start, чтобы увидеть, что я умею.")

    _save_state(state)


if __name__ == "__main__":
    run()
