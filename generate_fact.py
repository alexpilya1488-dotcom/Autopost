"""
Генерация факта и текста озвучки через бесплатный Gemini API.

Получить бесплатный ключ: https://aistudio.google.com/apikey
(бесплатный тариф Gemini даёт щедрую дневную квоту запросов).

Хранить ключ в переменной окружения GEMINI_API_KEY, не в коде.
"""

import os
import json
import random
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


def generate_fact(topic: str | None = None) -> dict:
    """Возвращает dict с title/script/description/tags для одного видео."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Задай переменную окружения GEMINI_API_KEY")

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")

    chosen_topic = topic or random.choice(TOPICS)
    prompt = PROMPT_TEMPLATE.format(topic=chosen_topic)

    response = model.generate_content(prompt)
    raw = response.text.strip()

    # На случай, если модель всё же обернёт ответ в ```json ... ```
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    data = json.loads(raw)
    data["topic"] = chosen_topic
    return data


if __name__ == "__main__":
    fact = generate_fact()
    print(json.dumps(fact, ensure_ascii=False, indent=2))
