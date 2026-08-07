"""
Генерация факта и текста озвучки через бесплатный Gemini API, с
автоматическим переключением на Groq при недоступности/лимите Gemini.

Ключи: GEMINI_API_KEY (aistudio.google.com/apikey) и
GROQ_API_KEY (console.groq.com).
"""

import os
import json
import random
import requests
import google.generativeai as genai

TOPICS = [
    "наука", "космос", "история", "животные", "технологии",
    "человеческое тело", "география", "океан", "изобретения", "искусство",
]

BASE_SHORTS_TAGS = ["shorts", "shortsvideo", "факты", "интересныефакты", "фактик"]

PROMPT_TEMPLATE = """Ты — сценарист коротких видео с интересными фактами для YouTube Shorts.
Тема: {topic}.

Придумай ОДИН неочевидный, проверяемый и интересный факт на эту тему.
Напиши для него:
1. title — короткий цепляющий заголовок видео (до 60 символов)
2. script — текст озвучки от лица дерзкого мультяшного персонажа по имени
   "Фактик": 4-6 коротких предложений, разговорный стиль, с эмоциями
   (удивление/сарказм/восторг), без канцелярита. Ровно один факт, без воды.
3. description — короткое описание видео для YouTube (2-3 предложения), в
   конце обязательно добавь строку с хэштегами: #Shorts #факты и ещё 3-4
   хэштега по теме факта
4. tags — список из 10-12 ключевых слов и коротких фраз для поиска на
   YouTube Shorts: несколько общих (shorts, факты, интересныефакты) и
   несколько узких, конкретно про тему факта (например, если факт про
   космос — "космос", "астрономия", "планеты" и т.п.)

Верни СТРОГО валидный JSON без markdown-обёртки, вот такой формы:
{{"title": "...", "script": "...", "description": "...", "tags": ["...", "..."]}}
"""


def _parse_json_response(raw: str) -> dict:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    return json.loads(raw)


def _generate_via_gemini(prompt: str) -> dict:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY не задан")
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-2.0-flash")
    response = model.generate_content(prompt)
    return _parse_json_response(response.text)


def _generate_via_groq(prompt: str) -> dict:
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY не задан")
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": "llama-3.3-70b-versatile",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.9,
        },
        timeout=60,
    )
    resp.raise_for_status()
    text = resp.json()["choices"][0]["message"]["content"]
    return _parse_json_response(text)


def _normalize_tags(tags, topic: str) -> list[str]:
    result = []
    seen = set()

    def add(tag):
        t = str(tag).strip().lower().replace("#", "")
        if t and t not in seen:
            seen.add(t)
            result.append(t)

    for t in BASE_SHORTS_TAGS:
        add(t)
    add(topic)
    if isinstance(tags, list):
        for t in tags:
            add(t)

    return result[:15]


def generate_fact(topic: str | None = None) -> dict:
    """Возвращает dict с title/script/description/tags для одного видео."""
    chosen_topic = topic or random.choice(TOPICS)
    prompt = PROMPT_TEMPLATE.format(topic=chosen_topic)

    try:
        data = _generate_via_gemini(prompt)
        print("Факт сгенерирован через Gemini")
    except Exception as gemini_err:
        print(f"Gemini недоступен ({gemini_err}), пробую Groq...")
        try:
            data = _generate_via_groq(prompt)
            print("Факт сгенерирован через Groq")
        except Exception as groq_err:
            raise RuntimeError(
                f"Не удалось сгенерировать факт ни через Gemini, ни через Groq.\n"
                f"Gemini: {gemini_err}\nGroq: {groq_err}"
            )

    data["topic"] = chosen_topic
    data["tags"] = _normalize_tags(data.get("tags"), chosen_topic)

    if "#shorts" not in data.get("description", "").lower():
        data["description"] = data.get("description", "").rstrip() + "\n\n#Shorts #факты #интересныефакты"

    return data


if __name__ == "__main__":
    fact = generate_fact()
    print(json.dumps(fact, ensure_ascii=False, indent=2))
