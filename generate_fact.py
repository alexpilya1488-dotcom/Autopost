"""
Генерация факта и текста озвучки.

Основная нейронка — Gemini (бесплатный тариф).
Если Gemini недоступен (закончилась дневная/минутная квота, сетевая ошибка
и т.п.) — автоматически переключаемся на Groq (тоже есть бесплатный тариф),
без остановки пайплайна.

Ключи брать из переменных окружения, не хранить в коде:
  GEMINI_API_KEY — https://aistudio.google.com/apikey
  GROQ_API_KEY   — https://console.groq.com/keys
"""

import os
import json
import random
import requests
import google.generativeai as genai

TOPICS = [
    "рекорды Гиннесса",
    "человеческое тело: странности и особенности",
    "повседневные предметы и их неожиданное прошлое",
    "еда: удивительные факты",
    "деньги и цены: забавные факты",
    "слова и языки: странности и происхождение",
    "привычки и правила в разных странах",
    "странные законы",
    "знаменитости: малоизвестные факты",
    "детство, школа и повседневная жизнь: то, о чём не знали",
]

PROMPT_TEMPLATE = """Ты — сценарист коротких видео с интересными фактами для YouTube Shorts.
Тема: {topic}.

Придумай ОДИН факт на эту тему, который будет понятен и близок обычному
человеку — НЕ сложную науку и не занудную теорию, а что-то простое, но
удивительное: неожиданный рекорд, курьёз, странность из повседневной жизни
или вещь, о которой большинство людей просто не знали. Проверь, что факт
достоверный и его легко пересказать в двух словах другу.

Напиши для него:
1. title — короткий цепляющий заголовок видео (до 60 символов)
2. script — текст озвучки от лица дерзкого мультяшного персонажа по имени
   "Фактик": 4-6 коротких предложений, разговорный стиль, с эмоциями
   (удивление/сарказм/восторг), без канцелярита. Ровно один факт, без воды.
3. description — короткое описание видео для YouTube (2-3 предложения) + 5 хэштегов
4. tags — список из 8-10 ключевых слов для YouTube (массив строк)

Верни СТРОГО валидный JSON без markdown-обёртки, вот такой формы:
{{"title": "...", "script": "...", "description": "...", "tags": ["...", "..."]}}
"""

GEMINI_MODEL = "gemini-2.0-flash"
# llama-3.3-70b-versatile в Groq устарела — актуальная рекомендованная замена:
GROQ_MODEL = "openai/gpt-oss-120b"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def _generate_with_gemini(prompt: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не задан")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(GEMINI_MODEL)
    response = model.generate_content(prompt)
    return response.text.strip()


def _generate_with_groq(prompt: str) -> str:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY не задан — резервная нейронка недоступна")

    resp = requests.post(
        GROQ_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": GROQ_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def _clean_json_text(raw: str) -> str:
    """Убирает markdown-обёртку ```json ... ```, если модель всё же её добавила."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return raw


def generate_fact(topic: str | None = None) -> dict:
    """Возвращает dict с title/script/description/tags для одного видео.
    Сначала пробует Gemini, при любой ошибке (квота, сеть, что угодно)
    молча переключается на Groq — пайплайн не останавливается."""
    chosen_topic = topic or random.choice(TOPICS)
    prompt = PROMPT_TEMPLATE.format(topic=chosen_topic)

    try:
        raw = _generate_with_gemini(prompt)
        used = "gemini"
    except Exception as gemini_error:
        print(f"   [!] Gemini недоступен ({gemini_error}). Переключаюсь на Groq...")
        raw = _generate_with_groq(prompt)
        used = "groq"

    data = json.loads(_clean_json_text(raw))
    data["topic"] = chosen_topic
    print(f"   (сгенерировано через: {used})")
    return data


if __name__ == "__main__":
    fact = generate_fact()
    print(json.dumps(fact, ensure_ascii=False, indent=2))
